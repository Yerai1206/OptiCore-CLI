"""Configuración e historial local, con transacciones breves."""
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def data_dir() -> Path:
    return Path(os.environ.get("OPTICORE_DATA_DIR", str(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "OptiCore")))


class State:
    def __init__(self, folder: Path | None = None):
        self.folder = folder or data_dir()
        self.folder.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY, created TEXT DEFAULT CURRENT_TIMESTAMP, kind TEXT, detail TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS moves (id INTEGER PRIMARY KEY, source TEXT, target TEXT, signature TEXT, status TEXT)")
            db.execute("PRAGMA user_version=1")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.folder / "opticore.db", timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, key: str, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key: str, value) -> None:
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, json.dumps(value)))

    def log(self, kind: str, detail) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO history(kind,detail) VALUES (?,?)", (kind, json.dumps(detail, ensure_ascii=False)))

    def history(self, limit: int = 100) -> list[dict]:
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM history ORDER BY id DESC LIMIT ?", (limit,))]
