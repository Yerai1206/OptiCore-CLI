"""Carga y valida las acciones antes de ejecutar cualquier operación."""
import json
from pathlib import Path

from opticore.core.errors import OptiCoreError


class ConfigError(OptiCoreError):
    """La configuración contiene un error que el usuario puede corregir."""


def cargar_acciones(ruta: Path | None = None) -> dict:
    ruta = ruta or (Path('acciones.json') if Path('acciones.json').is_file() else Path(__file__).parent.parent / 'acciones.json')
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"No se puede leer acciones.json: {exc}") from exc
    if not isinstance(datos, dict) or datos.get("version") != 1:
        raise ConfigError("Campo version: debe ser 1.")
    acciones = datos.get("acciones")
    if not isinstance(acciones, list) or not acciones:
        raise ConfigError("Campo acciones: debe ser una lista no vacía.")
    ids = set()
    for i, accion in enumerate(acciones, 1):
        if not isinstance(accion, dict):
            raise ConfigError(f"Acción {i}: debe ser un objeto.")
        for campo in ("id", "nombre", "tipo"):
            if not isinstance(accion.get(campo), str) or not accion[campo].strip():
                raise ConfigError(f"Acción {i}: falta el campo {campo}.")
        if accion["id"] in ids:
            raise ConfigError(f"Acción {i}: id duplicado: {accion['id']}.")
        ids.add(accion["id"])
        if accion["tipo"] not in {"convertir", "tokens", "almacenamiento", "ia"}:
            raise ConfigError(f"Acción {i}: tipo no admitido: {accion['tipo']}.")
        if accion["tipo"] == "ia" and (not isinstance(accion.get("instruccion"), str) or not accion["instruccion"].strip()):
            raise ConfigError(f"Acción {i}: falta instruccion para IA.")
    return {a["id"]: a for a in acciones}
