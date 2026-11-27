"""Limpieza conservadora: cuarentena local y restauración sin sobreescritura."""
import json
import os
import subprocess
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path

from opticore.core.errors import OptiCoreError
from opticore.core.paths import checked
from opticore.core.state import State
from opticore.modules.storage import Scan, walk


def user_temp() -> Path:
    # No confiar en TEMP/TMP: pueden apuntar a carpetas arbitrarias.
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise OptiCoreError("No se encuentra LOCALAPPDATA; limpieza deshabilitada.")
    return Path(local) / "Temp"


def signature(path: Path) -> list[int]:
    info = path.stat(follow_symlinks=False)
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]


def recycle_file(path: Path) -> None:
    """Envía un archivo a la papelera de Windows sin interpretar su nombre como código."""
    if os.name != 'nt':
        raise OptiCoreError('La papelera de esta función solo está disponible en Windows.')
    script = ("$ErrorActionPreference = 'Stop'; Add-Type -AssemblyName Microsoft.VisualBasic; "
              '[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile('
              '$env:OPTICORE_RECYCLE_TARGET, '
              '[Microsoft.VisualBasic.FileIO.UIOption]::OnlyErrorDialogs, '
              '[Microsoft.VisualBasic.FileIO.RecycleOption]::SendToRecycleBin)')
    env = os.environ.copy()
    env['OPTICORE_RECYCLE_TARGET'] = str(path)
    proceso = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                             env=env, capture_output=True, text=True, timeout=30)
    if proceso.returncode:
        raise OptiCoreError('Windows no pudo enviar este archivo a la papelera; puede estar en uso o sin permisos.')


@dataclass(frozen=True)
class Candidate:
    path: str
    size: int
    signature: list[int]


class Cleaner:
    def __init__(self, state: State, root: Path | None = None):
        self.state = state
        self.root = checked(root or user_temp())
        # root se inyecta únicamente para pruebas; interfaces usan siempre user_temp().
        if self.root == Path(self.root.anchor) or self.root == Path.home().resolve():
            raise OptiCoreError("Ruta de limpieza demasiado amplia.")
        protected = [Path(os.environ.get("SystemRoot", "C:/Windows")), Path(os.environ.get("ProgramFiles", "C:/Program Files"))]
        if any(self.root.is_relative_to(p.resolve()) for p in protected):
            raise OptiCoreError("Ruta protegida de Windows.")
        if root is None and not self.root.is_relative_to(Path.home().resolve()):
            raise OptiCoreError("La carpeta temporal debe estar dentro del perfil del usuario.")

    def scan(self, days: int = 7, cancel=None, progress=None) -> tuple[list[Candidate], Scan]:
        if days < 7:
            raise OptiCoreError("La antigüedad mínima es de 7 días.")
        report = Scan(str(self.root))
        result = []
        cutoff = time.time() - days * 86400
        for path, info in walk(self.root, report, cancel, progress):
            report.files += 1
            if path.suffix.lower() in {".tmp", ".temp"} and info.st_mtime < cutoff:
                result.append(Candidate(str(path), info.st_size, signature(path)))
                if len(result) >= 5000:
                    report.partial = True
                    break
        report.partial |= report.skipped > 0
        self.state.log("clean.scan", {"candidates": len(result), "partial": report.partial})
        return result, report

    def apply(self, candidates: list[Candidate], *, confirmed: bool = False, dry_run: bool = True) -> list[dict]:
        if not dry_run and not confirmed:
            raise OptiCoreError("Se requiere confirmación explícita.")
        results = []
        quarantine = self.state.folder / "quarantine"
        for item in candidates:
            move_id = None
            try:
                path = checked(Path(item.path), self.root)
                if not path.is_file() or path.suffix.lower() not in {".tmp", ".temp"}:
                    raise OptiCoreError("Archivo no permitido.")
                if signature(path) != item.signature or path.stat().st_mtime >= time.time() - 7 * 86400:
                    raise OptiCoreError("El archivo cambió desde la vista previa.")
                if dry_run:
                    results.append({"path": str(path), "status": "simulado"})
                    continue
                quarantine.mkdir(exist_ok=True)
                checked(quarantine)
                target = quarantine / uuid.uuid4().hex
                with self.state.connect() as db:
                    cursor = db.execute("INSERT INTO moves(source,target,signature,status) VALUES (?,?,?,?)",
                                        (str(path), str(target), json.dumps(item.signature), "pending"))
                    move_id = cursor.lastrowid
                # Solo rename: si cruza volúmenes o está bloqueado se omite, sin borrar/copy fallback.
                checked(path, self.root)
                if signature(path) != item.signature:
                    raise OptiCoreError("El archivo cambió antes de moverlo.")
                os.rename(path, target)
                with self.state.connect() as db:
                    db.execute("UPDATE moves SET status='quarantined' WHERE id=?", (move_id,))
                results.append({"id": move_id, "path": str(path), "status": "cuarentena"})
            except (OSError, OptiCoreError) as exc:
                results.append({"id": move_id, "path": item.path, "status": "omitido", "error": str(exc)})
        self.state.log("clean.simulate" if dry_run else "clean.apply", results)
        return results

    def recycle(self, candidates: list[Candidate], *, confirmed: bool = False) -> list[dict]:
        """Solo temporales antiguos revisados; nunca elimina fuera de la carpeta permitida."""
        if not confirmed:
            raise OptiCoreError('Confirma antes de enviar archivos a la papelera.')
        results = []
        for item in candidates:
            try:
                path = checked(Path(item.path), self.root)
                if not path.is_file() or path.suffix.lower() not in {'.tmp', '.temp'}:
                    raise OptiCoreError('El archivo ya no es un temporal permitido.')
                if signature(path) != item.signature or path.stat().st_mtime >= time.time() - 7 * 86400:
                    raise OptiCoreError('El archivo cambió desde la revisión.')
                recycle_file(path)
                results.append({'path': str(path), 'status': 'papelera'})
            except (OSError, OptiCoreError, subprocess.SubprocessError) as exc:
                results.append({'path': item.path, 'status': 'omitido', 'error': str(exc)})
        self.state.log('clean.recycle', results)
        return results

    def moves(self) -> list[dict]:
        with self.state.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM moves WHERE status IN ('pending','quarantined') ORDER BY id DESC")]

    def restore(self, move_id: int, *, confirmed: bool = False) -> None:
        if not confirmed:
            raise OptiCoreError("Confirma la restauración.")
        with self.state.connect() as db:
            row = db.execute("SELECT * FROM moves WHERE id=?", (move_id,)).fetchone()
        if not row or row["status"] not in {"pending", "quarantined"}:
            raise OptiCoreError("Operación no restaurable.")
        source = Path(row["source"])
        target = checked(Path(row["target"]), checked(self.state.folder / "quarantine"))
        if signature(target) != json.loads(row["signature"]):
            raise OptiCoreError("El archivo en cuarentena cambió.")
        checked(source.parent, self.root)
        if source.exists() or source.is_symlink():
            raise OptiCoreError("El destino ya existe; no se sobrescribe.")
        # En Windows rename falla si existe el destino, incluso si aparece tras validar.
        if os.name != "nt":
            raise OptiCoreError("La restauración está habilitada solo en Windows.")
        os.rename(target, source)
        with self.state.connect() as db:
            db.execute("UPDATE moves SET status='restored' WHERE id=?", (move_id,))
        self.state.log("clean.restore", {"id": move_id, "path": str(source)})
