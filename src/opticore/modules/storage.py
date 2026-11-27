"""Recorrido acotado, cancelable y sin seguir enlaces."""
import heapq
import os
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from collections.abc import Callable, Iterator

from opticore.core.errors import OptiCoreError
from opticore.core.paths import checked, is_link


@dataclass
class Scan:
    root: str
    files: int = 0
    bytes: int = 0
    skipped: int = 0
    partial: bool = False
    largest: list[tuple[int, str]] = field(default_factory=list)
    folders: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def walk(root: Path, report: Scan, cancel: Event | None = None,
         progress: Callable[[int], None] | None = None, limit: int = 200_000) -> Iterator[tuple[Path, os.stat_result]]:
    root = checked(root)
    if not root.is_dir():
        raise OptiCoreError("Selecciona una carpeta.")
    stack = [root]
    seen = 0
    while stack:
        if cancel and cancel.is_set():
            report.partial = True
            break
        folder = stack.pop()
        try:
            checked(folder, root)
            with os.scandir(folder) as entries:
                for entry in entries:
                    seen += 1
                    if seen > limit or (cancel and cancel.is_set()):
                        report.partial = True
                        return
                    path = Path(entry.path)
                    try:
                        if is_link(path):
                            report.skipped += 1
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(path)
                        elif entry.is_file(follow_symlinks=False):
                            yield path, entry.stat(follow_symlinks=False)
                    except (OSError, OptiCoreError) as exc:
                        report.skipped += 1
                        if len(report.warnings) < 20:
                            report.warnings.append(str(exc))
                    if progress and seen % 250 == 0:
                        progress(seen)
        except (OSError, OptiCoreError) as exc:
            report.skipped += 1
            if len(report.warnings) < 20:
                report.warnings.append(str(exc))


def analyze(root: Path, cancel: Event | None = None, progress=None) -> Scan:
    report = Scan(str(root.absolute()))
    top: list[tuple[int, str]] = []
    for path, info in walk(root, report, cancel, progress):
        report.files += 1
        report.bytes += info.st_size
        item = (info.st_size, str(path))
        if len(top) < 100:
            heapq.heappush(top, item)
        else:
            heapq.heappushpop(top, item)
        relative = path.relative_to(Path(report.root).resolve())
        group = relative.parts[0] if len(relative.parts) > 1 else "(raíz)"
        report.folders[group] = report.folders.get(group, 0) + info.st_size
    report.largest = sorted(top, reverse=True)
    report.partial |= report.skipped > 0
    return report
