"""SQLite implementation of unified message and session storage."""

import os
import sqlite3
from datetime import datetime
from typing import List, Optional

from asky.config import DB_PATH
from asky.storage.interface import HistoryRepository, Interaction


# Session dataclass (kept from session.py)
from dataclasses import dataclass


@dataclass
class Session:
    id: int
    name: Optional[str]
    model: str
    created_at: str
    ended_at: Optional[str]
    is_active: bool
    compacted_summary: Optional[str]


class SQLiteHistoryRepository(HistoryRepository):
    """SQLite-backed unified message and session storage."""

    def __init__(self):
        self.db_path = DB_PATH

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    def init_db(self) -> None:
        """Initialize the SQLite database and create tables if they don't exist."""
        os.makedirs(DB_PATH.parent, exist_ok=True)
        conn = self._get_conn()
        c = conn.cursor()

        # Unified messages table
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                
                -- Session fields (nullable for non-session messages)
                session_id INTEGER,
                role TEXT,
                
                -- Content fields
                content TEXT NOT NULL,
                summary TEXT,
                
                -- Legacy fields for history compatibility
                query_summary TEXT,
                answer_summary TEXT,
                
                -- Metadata
                model TEXT NOT NULL,
                token_count INTEGER,
                
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """
        )

        # Sessions table (unchanged)
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                model TEXT,
                created_at TEXT,
                ended_at TEXT,
                is_active INTEGER DEFAULT 1,
                compacted_summary TEXT
            )
        """
        )
        conn.commit()
        conn.close()

    def save_interaction(
        self,
        query: str,
        answer: str,
        model: str,
        query_summary: str = "",
        answer_summary: str = "",
    ) -> None:
        """Save a query and its answer to the messages table as a single history entry."""
        self.init_db()
        conn = self._get_conn()
        c = conn.cursor()

        # For history entries, we store the full interaction in content
        # with session_id=NULL and role=NULL
        full_content = f"Query: {query}\n\nAnswer: {answer}"

        c.execute(
            """INSERT INTO messages 
            (timestamp, session_id, role, content, summary, query_summary, answer_summary, model, token_count) 
            VALUES (?, NULL, NULL, ?, NULL, ?, ?, ?, NULL)""",
            (
                datetime.now().isoformat(),
                full_content,
                query_summary,
                answer_summary,
                model,
            ),
        )
        conn.commit()
        conn.close()

    def get_history(self, limit: int) -> List[Interaction]:
        """Fetch the most recent N history records (non-session messages)."""
        self.init_db()
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            """SELECT * FROM messages 
            WHERE session_id IS NULL 
            ORDER BY timestamp DESC LIMIT ?""",
            (limit,),
        )
        rows = c.fetchall()
        results = [
            Interaction(
                id=r["id"],
                timestamp=r["timestamp"],
                session_id=r["session_id"],
                role=r["role"],
                content=r["content"],
                summary=r["summary"],
                query_summary=r["query_summary"],
                answer_summary=r["answer_summary"],
                model=r["model"],
                token_count=r["token_count"],
            )
            for r in rows
        ]
        conn.close()
        return results

    def get_interaction_context(self, ids: List[int], full: bool = False) -> str:
        """Combine content from multiple interactions into a single context string."""
        self.init_db()
        conn = self._get_conn()
        c = conn.cursor()
        placeholders = ",".join(["?"] * len(ids))

        if full:
            c.execute(
                f"SELECT content FROM messages WHERE id IN ({placeholders}) ORDER BY id ASC",
                tuple(ids),
            )
        else:
            c.execute(
                f"SELECT query_summary, answer_summary FROM messages WHERE id IN ({placeholders}) ORDER BY id ASC",
                tuple(ids),
            )
        rows = c.fetchall()
        conn.close()

        context_parts = []
        for r in rows:
            if full:
                # Full content is already formatted
                context_parts.append(r[0] if r[0] else "...")
            else:
                # Build from summaries
                q = r[0] if r[0] else "..."
                a = r[1] if r[1] else "..."
                context_parts.append(f"Query: {q}")
                context_parts.append(f"Answer: {a}")
        return "\n\n".join(context_parts)

    def delete_messages(
        self,
        ids: Optional[str] = None,
        delete_all: bool = False,
    ) -> int:
        """Delete message history records by ID, range, list, or all."""
        self.init_db()
        conn = self._get_conn()
        c = conn.cursor()

        if delete_all:
            c.execute("DELETE FROM messages WHERE session_id IS NULL")
        elif ids:
            if "-" in ids:
                try:
                    start_id, end_id = map(int, ids.split("-"))
                    if start_id > end_id:
                        start_id, end_id = end_id, start_id
                    c.execute(
                        "DELETE FROM messages WHERE id BETWEEN ? AND ? AND session_id IS NULL",
                        (start_id, end_id),
                    )
                except ValueError:
                    print(
                        f"Error: Invalid range format. Use 'start-end' (e.g., '5-10')."
                    )
                    conn.close()
                    return 0
            elif "," in ids:
                try:
                    id_list = [int(x.strip()) for x in ids.split(",")]
                    placeholders = ",".join(["?"] * len(id_list))
                    c.execute(
                        f"DELETE FROM messages WHERE id IN ({placeholders}) AND session_id IS NULL",
                        tuple(id_list),
                    )
                except ValueError:
                    print("Error: Invalid list format. Use comma-separated integers.")
                    conn.close()
                    return 0
            else:
                try:
                    target_id = int(ids.strip())
                    c.execute(
                        "DELETE FROM messages WHERE id = ? AND session_id IS NULL",
                        (target_id,),
                    )
                except ValueError:
                    print("Error: Invalid ID format. Use an integer.")
                    conn.close()
                    return 0
        else:
            conn.close()
            return 0

        deleted_count = c.rowcount
        conn.commit()
        conn.close()
        return deleted_count

    def delete_sessions(
        self,
        ids: Optional[str] = None,
        delete_all: bool = False,
    ) -> int:
        """Delete session records and their associated messages."""
        self.init_db()
        conn = self._get_conn()
        c = conn.cursor()

        # Build list of session IDs to delete
        session_ids_to_delete = []

        if delete_all:
            c.execute("SELECT id FROM sessions")
            session_ids_to_delete = [r[0] for r in c.fetchall()]
        elif ids:
            if "-" in ids:
                try:
                    start_id, end_id = map(int, ids.split("-"))
                    if start_id > end_id:
                        start_id, end_id = end_id, start_id
                    c.execute(
                        "SELECT id FROM sessions WHERE id BETWEEN ? AND ?",
                        (start_id, end_id),
                    )
                    session_ids_to_delete = [r[0] for r in c.fetchall()]
                except ValueError:
                    print(
                        f"Error: Invalid range format. Use 'start-end' (e.g., '5-10')."
                    )
                    conn.close()
                    return 0
            elif "," in ids:
                try:
                    id_list = [int(x.strip()) for x in ids.split(",")]
                    placeholders = ",".join(["?"] * len(id_list))
                    c.execute(
                        f"SELECT id FROM sessions WHERE id IN ({placeholders})",
                        tuple(id_list),
                    )
                    session_ids_to_delete = [r[0] for r in c.fetchall()]
                except ValueError:
                    print("Error: Invalid list format. Use comma-separated integers.")
                    conn.close()
                    return 0
            else:
                try:
                    target_id = int(ids.strip())
                    c.execute("SELECT id FROM sessions WHERE id = ?", (target_id,))
                    result = c.fetchone()
                    if result:
                        session_ids_to_delete = [result[0]]
                except ValueError:
                    print("Error: Invalid ID format. Use an integer.")
                    conn.close()
                    return 0
        else:
            conn.close()
            return 0

        if not session_ids_to_delete:
            conn.close()
            return 0

        # Cascade delete: first delete session messages, then sessions
        placeholders = ",".join(["?"] * len(session_ids_to_delete))
        c.execute(
            f"DELETE FROM messages WHERE session_id IN ({placeholders})",
            tuple(session_ids_to_delete),
        )

        c.execute(
            f"DELETE FROM sessions WHERE id IN ({placeholders})",
            tuple(session_ids_to_delete),
        )

        deleted_count = c.rowcount
        conn.commit()
        conn.close()
        return deleted_count

    def get_db_record_count(self) -> int:
        """Return the number of non-session records in the messages table."""
        self.init_db()
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM messages WHERE session_id IS NULL")
        count = c.fetchone()[0]
        conn.close()
        return count

    # Session management methods (from SessionRepository)

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

    def save_message(
        self, session_id: int, role: str, content: str, summary: str, token_count: int
    ) -> None:
        """Save a message to a session."""
        conn = self._get_conn()
        c = conn.cursor()
        timestamp = datetime.now().isoformat()
        c.execute(
            """INSERT INTO messages 
            (timestamp, session_id, role, content, summary, query_summary, answer_summary, model, token_count) 
            VALUES (?, ?, ?, ?, ?, NULL, NULL, '', ?)""",
            (timestamp, session_id, role, content, summary, token_count),
        )
        conn.commit()
        conn.close()

    def get_session_messages(self, session_id: int) -> List[Interaction]:
        """Retrieve all messages for a session."""
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY timestamp ASC",
            (session_id,),
        )
        rows = c.fetchall()
        conn.close()
        return [
            Interaction(
                id=r["id"],
                timestamp=r["timestamp"],
                session_id=r["session_id"],
                role=r["role"],
                content=r["content"],
                summary=r["summary"],
                query_summary=r["query_summary"],
                answer_summary=r["answer_summary"],
                model=r["model"],
                token_count=r["token_count"],
            )
            for r in rows
        ]

    def compact_session(self, session_id: int, compacted_summary: str) -> None:
        """Replace session message history with a compacted summary."""
        conn = self._get_conn()
        c = conn.cursor()
        # Update session with summary
        c.execute(
            "UPDATE sessions SET compacted_summary = ? WHERE id = ?",
            (compacted_summary, session_id),
        )
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
