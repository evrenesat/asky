"""SQLite operations for the user_memories table."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def init_memory_table(cursor: sqlite3.Cursor) -> None:
    """Create the user_memories table if it doesn't already exist."""
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_text TEXT NOT NULL,
            tags TEXT,
            embedding BLOB,
            embedding_model TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def save_memory(db_path: Path, memory_text: str, tags: List[str] = None) -> int:
    """Insert a new memory row and return its ID."""
    if not memory_text or not memory_text.strip():
        raise ValueError("memory_text must be non-empty")
    if tags is None:
        tags = []
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute(
        "INSERT INTO user_memories (memory_text, tags, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (memory_text.strip(), json.dumps(tags), now, now),
    )
    memory_id = c.lastrowid
    conn.commit()
    conn.close()
    return memory_id


def update_memory(
    db_path: Path, memory_id: int, memory_text: str, tags: List[str] = None
) -> bool:
    """Update memory text and tags for an existing row."""
    if tags is None:
        tags = []
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute(
        "UPDATE user_memories SET memory_text = ?, tags = ?, updated_at = ? WHERE id = ?",
        (memory_text.strip(), json.dumps(tags), now, memory_id),
    )
    success = c.rowcount > 0
    conn.commit()
    conn.close()
    return success


def get_all_memories(db_path: Path, limit: int = 200) -> List[Dict[str, Any]]:
    """Return all memories ordered by created_at DESC."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        """
        SELECT id, memory_text, tags, embedding_model, created_at, updated_at
        FROM user_memories ORDER BY created_at DESC LIMIT ?
        """,
        (limit,),
    )
    rows = c.fetchall()
    conn.close()
    return [
        {
            "id": r["id"],
            "memory_text": r["memory_text"],
            "tags": json.loads(r["tags"]) if r["tags"] else [],
            "embedding_model": r["embedding_model"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]


def get_memory_by_id(db_path: Path, memory_id: int) -> Optional[Dict[str, Any]]:
    """Return a single memory row by ID, or None if not found."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        """
        SELECT id, memory_text, tags, embedding_model, created_at, updated_at
        FROM user_memories WHERE id = ?
        """,
        (memory_id,),
    )
    row = c.fetchone()
    conn.close()
    if row is None:
        return None
    return {
        "id": row["id"],
        "memory_text": row["memory_text"],
        "tags": json.loads(row["tags"]) if row["tags"] else [],
        "embedding_model": row["embedding_model"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def delete_memory_from_db(db_path: Path, memory_id: int) -> bool:
    """Delete a memory row from SQLite. Returns True if a row was deleted."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("DELETE FROM user_memories WHERE id = ?", (memory_id,))
    success = c.rowcount > 0
    conn.commit()
    conn.close()
    return success


def delete_all_memories_from_db(db_path: Path) -> int:
    """Delete all memory rows. Returns the count of deleted rows."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("DELETE FROM user_memories")
    count = c.rowcount
    conn.commit()
    conn.close()
    return count


def has_any_memories(db_path: Path) -> bool:
    """Return True if at least one memory with an embedding exists."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT 1 FROM user_memories WHERE embedding IS NOT NULL LIMIT 1")
    row = c.fetchone()
    conn.close()
    return row is not None
