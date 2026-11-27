"""Validaciones de rutas: no atravesar enlaces ni reparse points de Windows."""
import stat
from pathlib import Path

from opticore.core.errors import OptiCoreError


def is_link(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def checked(path: Path, root: Path | None = None) -> Path:
    absolute = Path(path.absolute())
    for part in (absolute, *absolute.parents):
        if part.exists() or part.is_symlink():
            if is_link(part):
                raise OptiCoreError(f"No se permiten enlaces o uniones: {part}")
    resolved = absolute.resolve(strict=True)
    if root is not None and not resolved.is_relative_to(root.resolve(strict=True)):
        raise OptiCoreError("La ruta sale de la carpeta permitida.")
    return resolved
