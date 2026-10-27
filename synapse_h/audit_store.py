"""Durable, append-only storage for audit events (SQLite).

* Rows cannot be updated or deleted: triggers abort any UPDATE or DELETE.
* Every row stores the SHA-256 of the previous row's hash plus its own content,
  so editing the file outside the app (or dropping the triggers) breaks the
  chain, and ``verify`` reports where.

SQLite on local disk is suitable for a single server or a pilot workstation.
Streamlit Community Cloud's filesystem is reset on restart, so a hosted
deployment needs a managed database with the same append-only rules.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path

GENESIS = "0" * 64

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    seq        INTEGER PRIMARY KEY,
    t          REAL NOT NULL,
    case_id    TEXT NOT NULL,
    event      TEXT NOT NULL,
    payload    TEXT NOT NULL,
    prev_hash  TEXT NOT NULL,
    hash       TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
"""


def _canonical(entry: dict) -> str:
    return json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _digest(prev_hash: str, payload: str) -> str:
    return hashlib.sha256((prev_hash + payload).encode()).hexdigest()


class SQLiteAuditStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()

    def append(self, entry: dict) -> dict:
        """Persist one event; ``seq`` is assigned by the store so concurrent sessions never collide."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute("SELECT seq, hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
                seq, prev = (row[0] + 1, row[1]) if row else (1, GENESIS)
                entry = {**entry, "seq": seq}
                payload = _canonical(entry)
                self._conn.execute(
                    "INSERT INTO audit_events (seq, t, case_id, event, payload, prev_hash, hash) VALUES (?,?,?,?,?,?,?)",
                    (seq, entry["t"], entry["case_id"], entry["event"], payload, prev, _digest(prev, payload)))
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return entry

    def load(self) -> list[dict]:
        rows = self._conn.execute("SELECT payload FROM audit_events ORDER BY seq").fetchall()
        return [json.loads(r[0]) for r in rows]

    def verify(self) -> list[str]:
        """Problems found in the hash chain (empty list = intact)."""
        problems, prev, expected_seq = [], GENESIS, 1
        for seq, payload, prev_hash, h in self._conn.execute(
                "SELECT seq, payload, prev_hash, hash FROM audit_events ORDER BY seq"):
            if seq != expected_seq:
                problems.append(f"seq {expected_seq}–{seq - 1} missing")
            if prev_hash != prev:
                problems.append(f"seq {seq}: previous-hash link broken")
            if _digest(prev_hash, payload) != h:
                problems.append(f"seq {seq}: content does not match its hash")
            if json.loads(payload).get("seq") != seq:
                problems.append(f"seq {seq}: payload seq differs")
            prev, expected_seq = h, seq + 1
        return problems

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "SQLiteAuditStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
