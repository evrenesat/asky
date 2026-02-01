"""SQLite database functions for conversation history."""

import os
import sqlite3
from datetime import datetime
from typing import List, Optional

from asearch.config import DB_PATH


def init_db() -> None:
    """Initialize the SQLite database and create tables if they don't exist."""
    os.makedirs(DB_PATH.parent, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            query TEXT,
            query_summary TEXT,
            answer TEXT,
            answer_summary TEXT,
            model TEXT
        )
    """)
    conn.commit()
    conn.close()


def get_history(limit: int = 10) -> List[tuple]:
    """Retrieve recent history entries."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, timestamp, query, query_summary, answer_summary, model FROM history ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    rows = c.fetchall()
    conn.close()
    return rows


def get_interaction_context(ids: List[int], full: bool = False) -> str:
    """Get context from previous interactions by their IDs."""
    if not ids:
        return ""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    placeholders = ",".join(["?"] * len(ids))
    query_str = f"SELECT id, query, query_summary, answer, answer_summary FROM history WHERE id IN ({placeholders})"
    c.execute(query_str, ids)
    results = c.fetchall()
    conn.close()

    context_parts = []
    for row in results:
        rid, query, q_sum, answer, a_sum = row
        q_text = q_sum if q_sum else query
        a_text = answer if full else a_sum
        context_parts.append(f"Query {rid}: {q_text}\nAnswer {rid}: {a_text}")

    return "\n\n".join(context_parts)


def cleanup_db(target: Optional[str], delete_all: bool = False) -> None:
    """Delete history records by ID, range, list, or all."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    try:
        if delete_all:
            c.execute("DELETE FROM history")
            c.execute("DELETE FROM sqlite_sequence WHERE name='history'")
            print("dataset cleaned completely.")
        elif target:
            _delete_by_target(c, target)
        else:
            print(
                "Error: No target specified for cleanup. Use --all or provide IDs/range."
            )

        conn.commit()
    except Exception as e:
        print(f"Error during cleanup: {e}")
    finally:
        conn.close()


def _delete_by_target(cursor: sqlite3.Cursor, target: str) -> None:
    """Helper to delete records by target specification."""
    # Check for range (e.g., "1-5")
    if "-" in target:
        try:
            start, end = map(int, target.split("-"))
            if start > end:
                start, end = end, start
            cursor.execute(
                "DELETE FROM history WHERE id >= ? AND id <= ?", (start, end)
            )
            print(f"deleted records from {start} to {end}.")
        except ValueError:
            print("Error: Invalid range format. Use 'start-end' (e.g., 1-5).")
    # Check for comma-separated list (e.g., "1,3,5")
    elif "," in target:
        try:
            ids = [int(x.strip()) for x in target.split(",")]
            placeholders = ",".join(["?"] * len(ids))
            cursor.execute(f"DELETE FROM history WHERE id IN ({placeholders})", ids)
            print(f"deleted records: {', '.join(map(str, ids))}.")
        except ValueError:
            print("Error: Invalid list format. Use comma-separated integers.")
    # Single ID
    else:
        try:
            rid = int(target)
            cursor.execute("DELETE FROM history WHERE id = ?", (rid,))
            print(f"deleted record {rid}.")
        except ValueError:
            print("Error: Invalid ID format. Must be an integer.")


def save_interaction(
    query: str,
    answer: str,
    model: str,
    query_summary: str = "",
    answer_summary: str = "",
) -> None:
    """Save an interaction to the database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    timestamp = datetime.now().isoformat()
    c.execute(
        """
        INSERT INTO history (timestamp, query, query_summary, answer, answer_summary, model)
        VALUES (?, ?, ?, ?, ?, ?)
    """,
        (timestamp, query, query_summary, answer, answer_summary, model),
    )
    conn.commit()
    conn.close()
