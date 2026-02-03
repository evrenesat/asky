"""Session storage and data models for asky."""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
import sqlite3
import os

from asky.config import DB_PATH


@dataclass
class SessionMessage:
    id: Optional[int]
    session_id: int
    role: str
    content: str
    summary: str
    token_count: int
    created_at: str


@dataclass
class Session:
    id: int
    name: Optional[str]
    model: str
    created_at: str
    ended_at: Optional[str]
    is_active: bool
    compacted_summary: Optional[str]


class SessionRepository:
    """Handles persistent session storage."""

    def __init__(self):
        self.db_path = DB_PATH

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    def create_session(self, model: str, name: Optional[str] = None) -> int:
        """Create a new session and return its ID."""
        conn = self._get_conn()
        c = conn.cursor()
        timestamp = datetime.now().isoformat()
        c.execute(
            "INSERT INTO sessions (name, model, created_at, is_active) VALUES (?, ?, ?, 1)",
            (name, model, timestamp),
        )
        session_id = c.lastrowid
        conn.commit()
        conn.close()
        return session_id

    def get_active_session(self) -> Optional[Session]:
        """Return the most recently created active session."""
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM sessions WHERE is_active = 1 ORDER BY created_at DESC LIMIT 1"
        )
        row = c.fetchone()
        conn.close()
        if row:
            return Session(**dict(row))
        return None

    def get_session_by_id(self, session_id: int) -> Optional[Session]:
        """Look up a session by ID."""
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        row = c.fetchone()
        conn.close()
        if row:
            return Session(**dict(row))
        return None

    def get_session_by_name(self, name: str) -> Optional[Session]:
        """Look up a session by name."""
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM sessions WHERE name = ? ORDER BY created_at DESC LIMIT 1",
            (name,),
        )
        row = c.fetchone()
        conn.close()
        if row:
            return Session(**dict(row))
        return None

    def add_message(
        self, session_id: int, role: str, content: str, summary: str, token_count: int
    ) -> None:
        """Append a message to a session."""
        conn = self._get_conn()
        c = conn.cursor()
        timestamp = datetime.now().isoformat()
        c.execute(
            "INSERT INTO session_messages (session_id, role, content, summary, token_count, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, role, content, summary, token_count, timestamp),
        )
        conn.commit()
        conn.close()

    def get_session_messages(self, session_id: int) -> List[SessionMessage]:
        """Retrieve all messages for a session."""
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM session_messages WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        )
        rows = c.fetchall()
        conn.close()
        return [SessionMessage(**dict(r)) for r in rows]

    def compact_session(self, session_id: int, compacted_summary: str) -> None:
        """Replace session message history with a compacted summary."""
        conn = self._get_conn()
        c = conn.cursor()
        # Update session with summary
        c.execute(
            "UPDATE sessions SET compacted_summary = ? WHERE id = ?",
            (compacted_summary, session_id),
        )
        # Delete old messages (optional: we might want to keep them but ignore them in build_context)
        # For now, let's keep them and let build_context handle the compacted_summary logic.
        conn.commit()
        conn.close()

    def end_session(self, session_id: int) -> None:
        """Mark a session as completed."""
        conn = self._get_conn()
        c = conn.cursor()
        timestamp = datetime.now().isoformat()
        c.execute(
            "UPDATE sessions SET is_active = 0, ended_at = ? WHERE id = ?",
            (timestamp, session_id),
        )
        conn.commit()
        conn.close()

    def list_sessions(self, limit: int) -> List[Session]:
        """List recently created sessions."""
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM sessions ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        rows = c.fetchall()
        conn.close()
        return [Session(**dict(r)) for r in rows]
