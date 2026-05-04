from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pc_build_agent.config import settings


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ChatTurn:
    role: str
    content: str
    meta: dict | None = None


class SessionStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path or settings.pc_guide_db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                  id TEXT PRIMARY KEY,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_id TEXT NOT NULL,
                  role TEXT NOT NULL,
                  content TEXT NOT NULL,
                  meta TEXT,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(session_id) REFERENCES sessions(id)
                )
                """
            )
            conn.commit()

    def create_session(self) -> str:
        sid = str(uuid.uuid4())
        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (id, created_at, updated_at) VALUES (?,?,?)",
                (sid, now, now),
            )
            conn.commit()
        return sid

    def touch_session(self, session_id: str) -> None:
        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, session_id))
            conn.commit()

    def append_message(self, session_id: str, role: str, content: str, meta: dict | None = None) -> None:
        now = _utc_now_iso()
        meta_json = json.dumps(meta or {}, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content, meta, created_at) VALUES (?,?,?,?,?)",
                (session_id, role, content, meta_json, now),
            )
            conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, session_id))
            conn.commit()

    def list_turns(self, session_id: str, limit: int = 24) -> list[ChatTurn]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT role, content, meta FROM messages
                WHERE session_id=?
                ORDER BY id ASC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        turns: list[ChatTurn] = []
        for row in rows:
            meta = {}
            if row["meta"]:
                try:
                    meta = json.loads(row["meta"])
                except json.JSONDecodeError:
                    meta = {}
            turns.append(ChatTurn(role=row["role"], content=row["content"], meta=meta))
        return turns

    def session_exists(self, session_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone()
        return row is not None


def get_session_store() -> SessionStore:
    return SessionStore()
