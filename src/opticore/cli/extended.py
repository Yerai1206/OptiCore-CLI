"""Comandos que delegan en los mismos servicios que la TUI."""
import json
import time
from dataclasses import asdict
from functools import wraps
from pathlib import Path
import sqlite3

import typer

from opticore.core.errors import OptiCoreError
from opticore.core.state import State
from opticore.modules.cleaner import Cleaner, Candidate
from opticore.modules.documents import convert, extract, count, save
from opticore.modules.storage import analyze


def guarded(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (OptiCoreError, OSError, sqlite3.Error, ValueError) as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(1) from exc
    return wrapped


def emit(value):
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2))


def register(app, system):
    disk = typer.Typer(help="Analiza carpetas sin modificar archivos.")
    clean = typer.Typer(help="Temporales antiguos: simulación y cuarentena recuperable.")
    ai = typer.Typer(help="Conversión y tokens locales, sin API.")
    config = typer.Typer(help="Configuración persistente.")
    app.add_typer(disk, name="disk")
    app.add_typer(clean, name="clean")
    app.add_typer(ai, name="ai")
    app.add_typer(config, name="config")

    @disk.command("analyze")
    @guarded
    def disk_analyze(path: Path):
        result = analyze(path)
        State().log("disk.analyze", {"root": result.root, "files": result.files, "bytes": result.bytes, "partial": result.partial})
        emit(asdict(result))

    @system.command("monitor")
    @guarded
    def monitor(samples: int = typer.Option(5, min=1, max=3600)):
        """Muestras cada segundo; Ctrl+C para salir."""
        from opticore.modules.system import snapshot
        for i in range(samples):
            emit(snapshot().to_dict())
            if i < samples - 1:
                time.sleep(1)

    @clean.command("scan")
    @guarded
    def scan():
        state = State()
        items, report = Cleaner(state).scan(state.get("clean_days", 7))
        state.set("clean_plan", [asdict(c) for c in items])
        emit({"candidates": [{"index": i + 1, **asdict(c)} for i, c in enumerate(items)], "partial": report.partial, "warnings": report.warnings})

    @clean.command("apply")
    @guarded
    def apply(review: bool = False, execute: bool = False):
        state = State()
        items = [Candidate(**c) for c in state.get("clean_plan", [])]
        if not items:
            raise OptiCoreError("Ejecuta clean scan primero; no hay candidatos.")
        if not review:
            raise OptiCoreError("Usa --review para seleccionar y previsualizar.")
        for i, item in enumerate(items, 1):
            typer.echo(f"{i}. {item.path} ({item.size} bytes)")
        selected = typer.prompt("Números separados por coma; vacío cancela", default="", show_default=False)
        if not selected.strip():
            raise typer.Exit()
        indexes = sorted(set(int(i.strip()) for i in selected.split(",")))
        if any(i < 1 or i > len(items) for i in indexes):
            raise OptiCoreError("Selección fuera de rango.")
        chosen = [items[i - 1] for i in indexes]
        if execute:
            typer.echo("La cuarentena no libera espacio del disco.")
            if not typer.confirm(f"¿Mover {len(chosen)} archivos a cuarentena?", default=False):
                raise typer.Exit()
        emit(Cleaner(state).apply(chosen, confirmed=execute, dry_run=not execute))

    @clean.command("quarantine")
    @guarded
    def quarantine():
        emit(Cleaner(State()).moves())

    @clean.command("restore")
    @guarded
    def restore(operation: int):
        if typer.confirm(f"¿Restaurar operación {operation} sin sobrescribir?", default=False):
            Cleaner(State()).restore(operation, confirmed=True)
            typer.echo("Restaurado.")

    @ai.command("convert")
    @guarded
    def document_convert(path: Path, output: Path = typer.Option(...), encoding: str | None = None,
                         budget: int | None = typer.Option(None, min=64), query: str = ""):
        result = convert(path, encoding=encoding or State().get("encoding", "cl100k_base"), budget=budget, query=query)
        save(result, output)
        State().log("ai.convert", {**result.report(), "output": str(output)})
        emit(result.report())

    @ai.command("analyze")
    @guarded
    def document_analyze(path: Path, encoding: str | None = None):
        encoding = encoding or State().get("encoding", "cl100k_base")
        text = extract(path)
        from collections import Counter
        from opticore.modules.documents import split_blocks
        repeated = Counter(split_blocks(text))
        emit({"source": str(path), "encoding": encoding, "tokens": count(text, encoding), "characters": len(text),
              "repeated_blocks": [{"preview": text[:120], "occurrences": n} for text, n in repeated.items() if n > 1]})

    @app.command("history")
    @guarded
    def history():
        emit(State().history())

    @config.command("show")
    @guarded
    def settings():
        state = State()
        emit({"data_dir": str(state.folder), "clean_days": state.get("clean_days", 7), "encoding": state.get("encoding", "cl100k_base")})

    @config.command("set")
    @guarded
    def set_config(key: str, value: str):
        if key == "clean_days" and 7 <= int(value) <= 3650:
            value = int(value)
        elif key != "encoding" or value not in {"cl100k_base", "o200k_base"}:
            raise OptiCoreError("Opciones: clean_days (7–3650), encoding (cl100k_base u o200k_base).")
        State().set(key, value)
        typer.echo("Configuración guardada.")
