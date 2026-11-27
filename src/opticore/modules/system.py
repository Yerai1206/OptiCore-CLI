"""Diagnóstico de solo lectura. No modifica ajustes del sistema."""

from dataclasses import asdict, dataclass
from pathlib import Path
import platform

import psutil

from opticore.core.errors import OptiCoreError


@dataclass(frozen=True)
class SystemSnapshot:
    os: str
    processor: str
    logical_cpus: int
    cpu_percent: float
    ram_total: int
    ram_available: int
    ram_percent: float
    disk_path: str
    disk_total: int
    disk_free: int

    def to_dict(self) -> dict[str, str | int | float]:
        return asdict(self)


def snapshot(disk_path: Path | None = None) -> SystemSnapshot:
    """Muestrea CPU durante 100 ms; almacenamiento del volumen indicado."""
    try:
        path = (disk_path or Path.home()).resolve(strict=True)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage(str(path))
        return SystemSnapshot(
            os=platform.platform(),
            processor=platform.processor() or platform.machine() or "No disponible",
            logical_cpus=psutil.cpu_count() or 0,
            cpu_percent=psutil.cpu_percent(interval=0.1),
            ram_total=ram.total, ram_available=ram.available, ram_percent=ram.percent,
            disk_path=str(path.anchor), disk_total=disk.total, disk_free=disk.free,
        )
    except (OSError, RuntimeError, psutil.Error) as exc:
        raise OptiCoreError(f"No se pudo consultar el sistema: {exc}") from exc


def format_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if abs(amount) < 1024 or unit == "PiB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    raise AssertionError("Unidad no alcanzable")


def display_rows(data: SystemSnapshot) -> list[tuple[str, str]]:
    return [
        ("Sistema", data.os), ("Procesador", data.processor),
        ("CPU lógicas", str(data.logical_cpus)), ("Uso CPU (muestra)", f"{data.cpu_percent:.1f}%"),
        ("RAM total", format_bytes(data.ram_total)),
        ("RAM disponible", format_bytes(data.ram_available)),
        ("Uso RAM", f"{data.ram_percent:.1f}%"),
        ("Volumen", data.disk_path), ("Disco total", format_bytes(data.disk_total)),
        ("Disco libre", format_bytes(data.disk_free)),
    ]
