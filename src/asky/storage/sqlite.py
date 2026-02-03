"""SQLite implementation of HistoryRepository."""

import os
import sqlite3
from datetime import datetime, timedelta
from typing import List, Optional, Union

from asky.config import DB_PATH
from asky.storage.interface import HistoryRepository, Interaction


class SQLiteHistoryRepository(HistoryRepository):
    """SQLite-backed conversation history storage."""

    def init_db(self) -> None:
        """Initialize the SQLite database and create tables if they don't exist."""
        os.makedirs(DB_PATH.parent, exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                query TEXT,
                query_summary TEXT,
                answer_summary TEXT,
                answer TEXT,
                model TEXT
            )
        """
        )
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
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS session_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER,
                role TEXT,
                content TEXT,
                summary TEXT,
                token_count INTEGER,
                created_at TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
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
        """Save a query and its answer to the history database."""
        self.init_db()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "INSERT INTO history (timestamp, query, query_summary, answer_summary, answer, model) VALUES (?, ?, ?, ?, ?, ?)",
            (
                datetime.now().isoformat(),
                query,
                query_summary,
                answer_summary,
                answer,
                model,
            ),
        )
        conn.commit()
        conn.close()

    def get_history(self, limit: int) -> List[Interaction]:
        """Fetch the most recent N history records."""
        self.init_db()
        conn = sqlite3.connect(DB_PATH)
        # Return as list of Interaction objects
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT id, timestamp, query, query_summary, answer_summary, answer, model FROM history ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        rows = c.fetchall()
        results = [
            Interaction(
                id=r["id"],
                timestamp=r["timestamp"],
                query=r["query"],
                query_summary=r["query_summary"],
                answer_summary=r["answer_summary"],
                answer=r["answer"],
                model=r["model"],
            )
            for r in rows
        ]
        conn.close()
        return results

    def get_interaction_context(self, ids: List[int], full: bool = False) -> str:
        """Combine query and answer from multiple interactions into a single context string."""
        self.init_db()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        placeholders = ",".join(["?"] * len(ids))
        if full:
            c.execute(
                f"SELECT query, answer FROM history WHERE id IN ({placeholders}) ORDER BY id ASC",
                tuple(ids),
            )
        else:
            c.execute(
                f"SELECT query_summary, answer_summary FROM history WHERE id IN ({placeholders}) ORDER BY id ASC",
                tuple(ids),
            )
        rows = c.fetchall()
        conn.close()
        context_parts = []
        for r in rows:
            q = r[0] if r[0] else "..."
            a = r[1] if r[1] else "..."
            context_parts.append(f"Query: {q}")
            context_parts.append(f"Answer: {a}")
        return "\n\n".join(context_parts)

    def cleanup_db(
        self,
        days: Optional[Union[int, str]] = None,
        delete_all: bool = False,
        ids: Optional[str] = None,
    ) -> int:
        """Remove entries based on days, all, or specific IDs."""
        # For backward compatibility with positional arguments
        if isinstance(days, str):
            ids = days
            days = None

        self.init_db()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        if delete_all:
            c.execute("DELETE FROM history")
        elif ids:
            if "-" in ids:
                try:
                    start_id, end_id = map(int, ids.split("-"))
                    if start_id > end_id:
                        start_id, end_id = end_id, start_id
                    c.execute(
                        "DELETE FROM history WHERE id BETWEEN ? AND ?",
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
                        f"DELETE FROM history WHERE id IN ({placeholders})",
                        tuple(id_list),
                    )
                except ValueError:
                    print("Error: Invalid list format. Use comma-separated integers.")
                    conn.close()
                    return 0
            else:
                try:
                    target_id = int(ids.strip())
                    c.execute("DELETE FROM history WHERE id = ?", (target_id,))
                except ValueError:
                    print("Error: Invalid ID format. Use an integer.")
                    conn.close()
                    return 0
        elif days is not None:
            try:
                days_int = int(days)
                cutoff_date = (datetime.now() - timedelta(days=days_int)).isoformat()
                c.execute("DELETE FROM history WHERE timestamp < ?", (cutoff_date,))
            except (ValueError, TypeError):
                conn.close()
                return 0
        else:
            conn.close()
            return 0

        deleted_count = c.rowcount
        conn.commit()
        conn.close()
        return deleted_count

    def get_db_record_count(self) -> int:
        """Return the number of records in the history database."""
        self.init_db()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM history")
        count = c.fetchone()[0]
        conn.close()
        return count
