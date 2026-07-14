"""SQLite cache for backend query responses — re-runs never re-hit the network (plan §2)."""

import json
import sqlite3
import time
from pathlib import Path

from cite_check.models import ScholarRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS queries (
    backend    TEXT NOT NULL,
    query      TEXT NOT NULL,
    response   TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (backend, query)
)
"""


class QueryCache:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def get(self, backend: str, query: str) -> list[ScholarRecord] | None:
        row = self._conn.execute(
            "SELECT response FROM queries WHERE backend = ? AND query = ?", (backend, query)
        ).fetchone()
        if row is None:
            return None
        return [ScholarRecord.model_validate(item) for item in json.loads(row[0])]

    def put(self, backend: str, query: str, records: list[ScholarRecord]) -> None:
        payload = json.dumps([r.model_dump(mode="json") for r in records])
        self._conn.execute(
            "INSERT OR REPLACE INTO queries VALUES (?, ?, ?, ?)",
            (backend, query, payload, time.time()),
        )
        self._conn.commit()

    def clear(self) -> int:
        cursor = self._conn.execute("DELETE FROM queries")
        self._conn.commit()
        return cursor.rowcount

    def close(self) -> None:
        self._conn.close()
