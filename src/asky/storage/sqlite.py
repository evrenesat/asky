"""SQLite implementation of unified message and session storage."""

import json
import os
import sqlite3
from datetime import datetime
from typing import List, Optional

from asky.config import DB_PATH
from asky.storage.interface import (
    HistoryRepository,
    ImageTranscriptRecord,
    Interaction,
    RoomSessionBinding,
    Session,
    SessionOverrideFile,
    TranscriptRecord,
)


# Session dataclass (kept from session.py)
SESSION_NAME_PREVIEW_MAX_CHARS = 30
TERMINAL_CONTEXT_PREFIX = "terminal context (last "
TERMINAL_CONTEXT_QUERY_MARKER = "\n\nQuery:\n"
RESEARCH_SOURCE_MODES = {"web_only", "local_only", "mixed"}


def _extract_session_name_source(user_content: str) -> str:
    """Return user query text suitable for session naming."""
    normalized = (user_content or "").replace("\r\n", "\n").strip()
    if not normalized:
        return ""
    if not normalized.lower().startswith(TERMINAL_CONTEXT_PREFIX):
        return normalized

    marker_index = normalized.find(TERMINAL_CONTEXT_QUERY_MARKER)
    if marker_index < 0:
        return normalized

    extracted_query = normalized[
        marker_index + len(TERMINAL_CONTEXT_QUERY_MARKER) :
    ].strip()
    return extracted_query or normalized


def _build_session_name_from_user_content(user_content: str) -> str:
    """Create a human-readable session name from user message text."""
    source_text = _extract_session_name_source(user_content)
    if not source_text:
        return "New Session"

    first_non_empty_line = ""
    for line in source_text.splitlines():
        stripped = line.strip()
        if stripped:
            first_non_empty_line = stripped
            break

    if not first_non_empty_line:
        return "New Session"

    if len(first_non_empty_line) <= SESSION_NAME_PREVIEW_MAX_CHARS:
        return first_non_empty_line
    return first_non_empty_line[:SESSION_NAME_PREVIEW_MAX_CHARS] + "..."


def _normalize_research_source_mode(value: Optional[str]) -> Optional[str]:
    """Normalize persisted research source mode values."""
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if not normalized:
        return None
    if normalized not in RESEARCH_SOURCE_MODES:
        return None
    return normalized


def _serialize_local_corpus_paths(paths: Optional[List[str]]) -> Optional[str]:
    """Serialize corpus path list for DB persistence."""
    if paths is None:
        return None
    serialized = [str(item) for item in paths if str(item).strip()]
    return json.dumps(serialized)


def _deserialize_local_corpus_paths(raw: Optional[str]) -> List[str]:
    """Deserialize corpus path list from DB values."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def _ensure_unique_session_name(cursor: sqlite3.Cursor, name: str) -> str:
    """Ensure a session name is unique by appending a numeric suffix if needed."""
    if not name:
        return name

    candidate = name
    counter = 1
    while True:
        cursor.execute("SELECT 1 FROM sessions WHERE name = ? LIMIT 1", (candidate,))
        if cursor.fetchone() is None:
            return candidate
        counter += 1
        candidate = f"{name}_{counter}"


def _build_unique_dedup_session_name(
    cursor: sqlite3.Cursor,
    *,
    original_name: str,
    session_id: int,
) -> str:
    """Return a collision-free deduplicated session name."""
    base = f"{original_name}__dedup_{int(session_id)}"
    candidate = base
    counter = 1
    while True:
        cursor.execute(
            "SELECT 1 FROM sessions WHERE name = ? AND id != ? LIMIT 1",
            (candidate, int(session_id)),
        )
        if cursor.fetchone() is None:
            return candidate
        counter += 1
        candidate = f"{base}_{counter}"


class SQLiteHistoryRepository(HistoryRepository):
    """SQLite-backed unified message and session storage."""

    def __init__(self):
        self.db_path = DB_PATH

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    def _session_from_row(self, row: sqlite3.Row) -> Session:
        """Build a Session dataclass from a sqlite row."""
        return Session(
            id=row["id"],
            name=row["name"],
            model=row["model"],
            created_at=row["created_at"],
            compacted_summary=row["compacted_summary"],
            memory_auto_extract=bool(row["memory_auto_extract"]),
            max_turns=row["max_turns"],
            last_used_at=row["last_used_at"],
            research_mode=bool(row["research_mode"] or 0),
            research_source_mode=_normalize_research_source_mode(
                row["research_source_mode"]
            ),
            research_local_corpus_paths=_deserialize_local_corpus_paths(
                row["research_local_corpus_paths"]
            ),
        )

    def _transcript_from_row(self, row: sqlite3.Row) -> TranscriptRecord:
        """Build a transcript dataclass from a sqlite row."""
        return TranscriptRecord(
            id=int(row["id"]),
            session_id=int(row["session_id"]),
            session_transcript_id=int(row["session_transcript_id"]),
            jid=str(row["jid"] or ""),
            created_at=str(row["created_at"] or ""),
            status=str(row["status"] or ""),
            audio_url=str(row["audio_url"] or ""),
            audio_path=str(row["audio_path"] or ""),
            transcript_text=str(row["transcript_text"] or ""),
            error=str(row["error"] or ""),
            duration_seconds=row["duration_seconds"],
            used=bool(row["used"] or 0),
        )

    def _room_binding_from_row(self, row: sqlite3.Row) -> RoomSessionBinding:
        """Build a room-binding dataclass from a sqlite row."""
        return RoomSessionBinding(
            room_jid=str(row["room_jid"] or ""),
            session_id=int(row["session_id"]),
            updated_at=str(row["updated_at"] or ""),
        )

    def _image_transcript_from_row(self, row: sqlite3.Row) -> ImageTranscriptRecord:
        """Build an image transcript dataclass from a sqlite row."""
        return ImageTranscriptRecord(
            id=int(row["id"]),
            session_id=int(row["session_id"]),
            session_image_id=int(row["session_image_id"]),
            jid=str(row["jid"] or ""),
            created_at=str(row["created_at"] or ""),
            status=str(row["status"] or ""),
            image_url=str(row["image_url"] or ""),
            image_path=str(row["image_path"] or ""),
            transcript_text=str(row["transcript_text"] or ""),
            error=str(row["error"] or ""),
            duration_seconds=row["duration_seconds"],
            used=bool(row["used"] or 0),
        )

    def _session_override_from_row(self, row: sqlite3.Row) -> SessionOverrideFile:
        """Build a session override file dataclass from a sqlite row."""
        return SessionOverrideFile(
            session_id=int(row["session_id"]),
            filename=str(row["filename"] or ""),
            content=str(row["content"] or ""),
            updated_at=str(row["updated_at"] or ""),
        )

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
                
                -- Session fields (nullable for non-session unique messages)
                session_id INTEGER,
                role TEXT NOT NULL,
                
                -- Content fields
                content TEXT NOT NULL,
                summary TEXT,
                
                -- Metadata
                model TEXT NOT NULL,
                token_count INTEGER,
                
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """
        )

        # Sessions table
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                model TEXT,
                created_at TEXT,
                compacted_summary TEXT,
                memory_auto_extract INTEGER DEFAULT 0,
                max_turns INTEGER,
                last_used_at TEXT,
                research_mode INTEGER DEFAULT 0,
                research_source_mode TEXT,
                research_local_corpus_paths TEXT
            )
        """
        )

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS transcripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                session_transcript_id INTEGER NOT NULL,
                jid TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL,
                audio_url TEXT,
                audio_path TEXT,
                transcript_text TEXT,
                error TEXT,
                duration_seconds REAL,
                used INTEGER DEFAULT 0,
                FOREIGN KEY (session_id) REFERENCES sessions(id),
                UNIQUE (session_id, session_transcript_id)
            )
            """
        )

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS room_session_bindings (
                room_jid TEXT PRIMARY KEY,
                session_id INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
            """
        )

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS image_transcripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                session_image_id INTEGER NOT NULL,
                jid TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL,
                image_url TEXT,
                image_path TEXT,
                transcript_text TEXT,
                error TEXT,
                duration_seconds REAL,
                used INTEGER DEFAULT 0,
                FOREIGN KEY (session_id) REFERENCES sessions(id),
                UNIQUE (session_id, session_image_id)
            )
            """
        )

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS session_override_files (
                session_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                content TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (session_id, filename),
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
            """
        )

        # Schema migration: add memory_auto_extract column to existing sessions tables
        try:
            c.execute(
                "ALTER TABLE sessions ADD COLUMN memory_auto_extract INTEGER DEFAULT 0"
            )
        except sqlite3.OperationalError:
            pass  # column already exists

        # Schema migration: add max_turns column to existing sessions tables
        try:
            c.execute("ALTER TABLE sessions ADD COLUMN max_turns INTEGER")
        except sqlite3.OperationalError:
            pass  # column already exists

        # Schema migration: add last_used_at column to existing sessions tables
        try:
            c.execute("ALTER TABLE sessions ADD COLUMN last_used_at TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists

        # Schema migration: add research_mode column to existing sessions tables
        try:
            c.execute("ALTER TABLE sessions ADD COLUMN research_mode INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # column already exists

        # Schema migration: add research_source_mode column to existing sessions tables
        try:
            c.execute("ALTER TABLE sessions ADD COLUMN research_source_mode TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists

        # Schema migration: add research_local_corpus_paths column
        try:
            c.execute(
                "ALTER TABLE sessions ADD COLUMN research_local_corpus_paths TEXT"
            )
        except sqlite3.OperationalError:
            pass  # column already exists

        self._deduplicate_legacy_session_names(c)

        c.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_name
               ON sessions(name) WHERE name IS NOT NULL"""
        )

        # User memories table
        from asky.memory.store import init_memory_table

        init_memory_table(c)

        # Schema migration: add session_id to user_memories if missing
        try:
            c.execute("ALTER TABLE user_memories ADD COLUMN session_id INTEGER")
            # Existing memories have NULL session_id -> effectively Global.
        except sqlite3.OperationalError:
            pass  # column already exists

        conn.commit()
        conn.close()

    def _deduplicate_legacy_session_names(self, cursor: sqlite3.Cursor) -> int:
        """Rename duplicate legacy session names so unique index creation succeeds."""
        cursor.execute(
            """
            SELECT name
            FROM sessions
            WHERE name IS NOT NULL
            GROUP BY name
            HAVING COUNT(*) > 1
            """
        )
        duplicate_names = [
            str(row[0]) for row in cursor.fetchall() if row[0] is not None
        ]
        if not duplicate_names:
            return 0

        updated = 0
        for name in duplicate_names:
            cursor.execute(
                """
                SELECT id
                FROM sessions
                WHERE name = ?
                ORDER BY created_at DESC, id DESC
                """,
                (name,),
            )
            ids = [int(row[0]) for row in cursor.fetchall()]
            if len(ids) <= 1:
                continue

            # Keep the newest session on the original name, rename older ones.
            for session_id in ids[1:]:
                new_name = _build_unique_dedup_session_name(
                    cursor,
                    original_name=name,
                    session_id=session_id,
                )
                cursor.execute(
                    "UPDATE sessions SET name = ? WHERE id = ?",
                    (new_name, session_id),
                )
                updated += 1
        return updated

    def save_interaction(
        self,
        query: str,
        answer: str,
        model: str,
        query_summary: str = "",
        answer_summary: str = "",
    ) -> int:
        """Save a query and its answer as two separate message rows (User + Assistant).

        Returns the ID of the assistant message.
        """
        self.init_db()
        conn = self._get_conn()
        c = conn.cursor()

        timestamp = datetime.now().isoformat()

        # 1. Save User Message
        c.execute(
            """INSERT INTO messages 
            (timestamp, session_id, role, content, summary, model, token_count) 
            VALUES (?, NULL, 'user', ?, ?, ?, NULL)""",
            (timestamp, query, query_summary, model),
        )

        # 2. Save Assistant Message
        c.execute(
            """INSERT INTO messages 
            (timestamp, session_id, role, content, summary, model, token_count) 
            VALUES (?, NULL, 'assistant', ?, ?, ?, NULL)""",
            (timestamp, answer, answer_summary, model),
        )
        assistant_id = c.lastrowid

        conn.commit()
        conn.close()
        return assistant_id

    def reserve_interaction(self, model: str) -> tuple[int, int]:
        """Insert placeholder empty messages to reserve IDs before rendering.

        Returns (user_id, assistant_id).
        """
        self.init_db()
        conn = self._get_conn()
        c = conn.cursor()

        timestamp = datetime.now().isoformat()

        # Insert placeholder user message
        c.execute(
            """INSERT INTO messages 
            (timestamp, session_id, role, content, summary, model, token_count) 
            VALUES (?, NULL, 'user', '', '', ?, NULL)""",
            (timestamp, model),
        )
        user_id = c.lastrowid

        # Insert placeholder assistant message
        c.execute(
            """INSERT INTO messages 
            (timestamp, session_id, role, content, summary, model, token_count) 
            VALUES (?, NULL, 'assistant', '', '', ?, NULL)""",
            (timestamp, model),
        )
        assistant_id = c.lastrowid

        conn.commit()
        conn.close()
        return user_id, assistant_id

    def update_interaction(
        self,
        user_id: int,
        assistant_id: int,
        query: str,
        answer: str,
        model: str,
        query_summary: str = "",
        answer_summary: str = "",
    ) -> None:
        """Update placeholder messages with real content."""
        conn = self._get_conn()
        c = conn.cursor()

        # Update User Message
        c.execute(
            "UPDATE messages SET content=?, summary=?, model=? WHERE id=?",
            (query, query_summary, model, user_id),
        )

        # Update Assistant Message
        c.execute(
            "UPDATE messages SET content=?, summary=?, model=? WHERE id=?",
            (answer, answer_summary, model, assistant_id),
        )

        conn.commit()
        conn.close()

    def get_history(self, limit: int) -> List[Interaction]:
        """Fetch the most recent history interactions (paired from messages)."""
        self.init_db()
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # We need to fetch enough messages to form 'limit' pairs.
        # Safest is to fetch limit * 2 (assuming perfect pairs) but we might have orphans.
        # Let's fetch limit * 3 to be safe and trim later.
        fetch_limit = limit * 3

        c.execute(
            """SELECT * FROM messages 
            WHERE session_id IS NULL 
            ORDER BY timestamp DESC, id DESC LIMIT ?""",
            (fetch_limit,),
        )
        rows = c.fetchall()
        conn.close()

        interactions = []
        # Process rows in temporal order (ASC) to pair them?
        # Rows are DESC (Newest first).
        # Expected pattern: [Asst, User, Asst, User, ...]

        i = 0
        while i < len(rows):
            current = rows[i]

            # If we find an assistant message, look for the next one being a user message (older)
            if current["role"] == "assistant":
                # Check next message
                if i + 1 < len(rows):
                    next_msg = rows[i + 1]
                    if next_msg["role"] == "user":
                        # Found a pair: next_msg (User) -> current (Assistant)
                        interactions.append(
                            Interaction(
                                id=current["id"],  # Use Assistant ID as Interaction ID
                                timestamp=current["timestamp"],
                                session_id=None,
                                role=None,
                                content=f"Query: {next_msg['content']}\n\nAnswer: {current['content']}",  # Legacy back-compat
                                query=next_msg["content"],
                                answer=current["content"],
                                summary=current[
                                    "summary"
                                ],  # Summary of the interaction (usually Answer summary matters more/last)
                                model=current["model"],
                                token_count=None,
                            )
                        )
                        i += 2
                        continue

                # Orphan assistant message? Treat as interaction with unknown query?
                interactions.append(
                    Interaction(
                        id=current["id"],
                        timestamp=current["timestamp"],
                        session_id=None,
                        role=None,
                        content="",
                        query="<unknown>",
                        answer=current["content"],
                        summary=current["summary"],
                        model=current["model"],
                        token_count=None,
                    )
                )
                i += 1

            elif current["role"] == "user":
                # Orphan user message (interrupted?)
                interactions.append(
                    Interaction(
                        id=current["id"],
                        timestamp=current["timestamp"],
                        session_id=None,
                        role=None,
                        content="",
                        query=current["content"],
                        answer="<no answer>",
                        summary=current["summary"],
                        model=current["model"],
                        token_count=None,
                    )
                )
                i += 1
            else:
                # Fallback for old legacy rows (role IS NULL)
                # If content contains "Query:" parse it? Or just dump content to 'answer' and put query in 'query'.
                # The old 'content' had "Query: ... Answer: ..."
                # Let's just put it all in Answer for visibility if we can't parse.
                # Or better: check for legacy columns? No, row factory keys depend on schema.
                # If schema changed, old rows still return 'role' as None.

                interactions.append(
                    Interaction(
                        id=current["id"],
                        timestamp=current["timestamp"],
                        session_id=None,
                        role=None,
                        content=current["content"],  # use content
                        query="",
                        answer="",
                        summary=current["summary"] or "",
                        model=current["model"],
                        token_count=current["token_count"],
                    )
                )
                i += 1

        return interactions[:limit]

    def get_interaction_context(self, ids: List[int], full: bool = False) -> str:
        """Combine content from multiple interactions into a single context string."""
        self.init_db()
        conn = self._get_conn()
        try:
            c = conn.cursor()

            # Smart Expansion: Include partners for global history interactions
            expanded_ids = set(ids)
            if ids:
                placeholders = ",".join(["?"] * len(ids))
                c.execute(
                    f"SELECT id, role FROM messages WHERE id IN ({placeholders}) AND session_id IS NULL",
                    tuple(ids),
                )
                rows = c.fetchall()

                for r in rows:
                    curr_id, role = r
                    if role == "assistant":
                        c.execute(
                            "SELECT id FROM messages WHERE role='user' AND id < ? AND session_id IS NULL ORDER BY id DESC LIMIT 1",
                            (curr_id,),
                        )
                        partner = c.fetchone()
                        if partner:
                            expanded_ids.add(partner[0])
                    elif role == "user":
                        c.execute(
                            "SELECT id FROM messages WHERE role='assistant' AND id > ? AND session_id IS NULL ORDER BY id ASC LIMIT 1",
                            (curr_id,),
                        )
                        partner = c.fetchone()
                        if partner:
                            expanded_ids.add(partner[0])

            final_ids = sorted(list(expanded_ids))
            if not final_ids:
                return ""

            placeholders = ",".join(["?"] * len(final_ids))

            # Fetch content and summary
            c.execute(
                f"SELECT id, role, content, summary FROM messages WHERE id IN ({placeholders}) ORDER BY id ASC",
                tuple(final_ids),
            )
            rows = c.fetchall()

            context_parts = []
            updates = []

            for r in rows:
                msg_id = r[0]
                role = r[1]
                content = r[2]
                summary = r[3]

                if full:
                    context_parts.append(content if content else "...")
                else:
                    text = summary
                    if not text:
                        from asky.config import SUMMARIZATION_LAZY_THRESHOLD_CHARS

                        if (
                            content
                            and len(content) > SUMMARIZATION_LAZY_THRESHOLD_CHARS
                        ):
                            from asky.summarization import generate_summaries
                            from asky.core.api_client import get_llm_msg

                            if role == "user":
                                sum_query, _ = generate_summaries(
                                    content, "", usage_tracker=None
                                )
                                text = sum_query
                            else:
                                _, sum_answer = generate_summaries(
                                    "", content, usage_tracker=None
                                )
                                text = sum_answer

                            if text:
                                updates.append((text, msg_id))
                        else:
                            text = content

                    prefix = "Query: " if role == "user" else "Answer: "
                    context_parts.append(f"{prefix}{text}")

            if updates:
                c.executemany("UPDATE messages SET summary = ? WHERE id = ?", updates)
                conn.commit()

            return "\n\n".join(context_parts)
        finally:
            conn.close()

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
            deleted_count = c.rowcount
            conn.commit()
            conn.close()
            return deleted_count

        if ids:
            target_ids = []
            if "-" in ids:
                try:
                    start_id, end_id = map(int, ids.split("-"))
                    if start_id > end_id:
                        start_id, end_id = end_id, start_id
                    c.execute(
                        "SELECT id FROM messages WHERE id BETWEEN ? AND ? AND session_id IS NULL",
                        (start_id, end_id),
                    )
                    target_ids = [r[0] for r in c.fetchall()]
                except ValueError:
                    print(
                        f"Error: Invalid range format. Use 'start-end' (e.g., '5-10')."
                    )
                    conn.close()
                    return 0
            elif "," in ids:
                try:
                    target_ids = [int(x.strip()) for x in ids.split(",")]
                except ValueError:
                    print("Error: Invalid list format. Use comma-separated integers.")
                    conn.close()
                    return 0
            else:
                try:
                    target_ids = [int(ids.strip())]
                except ValueError:
                    print("Error: Invalid ID format. Use an integer.")
                    conn.close()
                    return 0

            # Expand partners (Smart Delete)
            expanded_ids = set(target_ids)
            if target_ids:
                placeholders = ",".join(["?"] * len(target_ids))
                c.execute(
                    f"SELECT id, role, timestamp FROM messages WHERE id IN ({placeholders})",
                    tuple(target_ids),
                )
                rows = c.fetchall()

                for r in rows:
                    curr_id, role, ts = r

                    if role == "assistant":
                        # Look for preceding user message
                        c.execute(
                            "SELECT id FROM messages WHERE role='user' AND id < ? AND session_id IS NULL ORDER BY id DESC LIMIT 1",
                            (curr_id,),
                        )
                        partner = c.fetchone()
                        if partner:
                            expanded_ids.add(partner[0])
                    elif role == "user":
                        # Look for succeding assistant message
                        c.execute(
                            "SELECT id FROM messages WHERE role='assistant' AND id > ? AND session_id IS NULL ORDER BY id ASC LIMIT 1",
                            (curr_id,),
                        )
                        partner = c.fetchone()
                        if partner:
                            expanded_ids.add(partner[0])

            if expanded_ids:
                final_list = list(expanded_ids)
                p_holders = ",".join(["?"] * len(final_list))
                c.execute(
                    f"DELETE FROM messages WHERE id IN ({p_holders})", tuple(final_list)
                )
                deleted_count = c.rowcount
            else:
                deleted_count = 0

            conn.commit()
            conn.close()
            return deleted_count

        conn.close()
        return 0

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

    def count_sessions(self) -> int:
        """Return the total number of sessions."""
        self.init_db()
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM sessions")
        count = c.fetchone()[0]
        conn.close()
        return count

    # Session management methods (from SessionRepository)

    def create_session(
        self,
        model: str,
        name: Optional[str] = None,
        memory_auto_extract: bool = False,
        max_turns: Optional[int] = None,
        research_mode: bool = False,
        research_source_mode: Optional[str] = None,
        research_local_corpus_paths: Optional[List[str]] = None,
    ) -> int:
        """Create a new session and return its ID."""
        conn = self._get_conn()
        c = conn.cursor()
        timestamp = datetime.now().isoformat()
        normalized_mode = _normalize_research_source_mode(research_source_mode)
        if research_source_mode and normalized_mode is None:
            conn.close()
            raise ValueError(f"Invalid research_source_mode: {research_source_mode!r}")

        unique_name = _ensure_unique_session_name(c, name) if name else name

        serialized_paths = _serialize_local_corpus_paths(research_local_corpus_paths)
        c.execute(
            "INSERT INTO sessions (name, model, created_at, memory_auto_extract, max_turns, last_used_at, research_mode, research_source_mode, research_local_corpus_paths) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                unique_name,
                model,
                timestamp,
                int(memory_auto_extract),
                max_turns,
                timestamp,
                int(research_mode),
                normalized_mode,
                serialized_paths,
            ),
        )
        session_id = c.lastrowid
        conn.commit()
        conn.close()
        return session_id

    def set_session_memory_auto_extract(self, session_id: int, enabled: bool) -> None:
        """Enable or disable auto memory extraction for a session."""
        conn = self._get_conn()
        c = conn.cursor()
        c.execute(
            "UPDATE sessions SET memory_auto_extract = ? WHERE id = ?",
            (int(enabled), session_id),
        )
        conn.commit()
        conn.close()

    def get_sessions_by_name(self, name: str) -> List[Session]:
        """Return all sessions matching the given name."""
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT id, name, model, created_at, compacted_summary, memory_auto_extract, max_turns, last_used_at, research_mode, research_source_mode, research_local_corpus_paths FROM sessions WHERE name = ? ORDER BY created_at DESC",
            (name,),
        )
        rows = c.fetchall()
        conn.close()
        return [self._session_from_row(r) for r in rows]

    def get_session_by_id(self, session_id: int) -> Optional[Session]:
        """Look up a session by ID."""
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT id, name, model, created_at, compacted_summary, memory_auto_extract, max_turns, last_used_at, research_mode, research_source_mode, research_local_corpus_paths FROM sessions WHERE id = ?",
            (session_id,),
        )
        row = c.fetchone()
        conn.close()
        if row:
            return self._session_from_row(row)
        return None

    def get_session_by_name(self, name: str) -> Optional[Session]:
        """Look up the most recent session by name."""
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT id, name, model, created_at, compacted_summary, memory_auto_extract, max_turns, last_used_at, research_mode, research_source_mode, research_local_corpus_paths FROM sessions WHERE name = ? ORDER BY created_at DESC LIMIT 1",
            (name,),
        )
        row = c.fetchone()
        conn.close()
        if row:
            return self._session_from_row(row)
        return None

    def save_message(
        self, session_id: int, role: str, content: str, summary: str, token_count: int
    ) -> int:
        """Save a message to a session. Returns the message ID."""
        conn = self._get_conn()
        c = conn.cursor()
        timestamp = datetime.now().isoformat()
        c.execute(
            """INSERT INTO messages 
            (timestamp, session_id, role, content, summary, model, token_count) 
            VALUES (?, ?, ?, ?, ?, '', ?)""",
            (timestamp, session_id, role, content, summary, token_count),
        )
        msg_id = c.lastrowid
        c.execute(
            "UPDATE sessions SET last_used_at = ? WHERE id = ?", (timestamp, session_id)
        )
        conn.commit()
        conn.close()
        return msg_id

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
                query="",  # Not used for session view, content is primary
                answer="",
                summary=r["summary"],
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

    def clear_session_messages(self, session_id: int) -> int:
        """Delete all messages for a session and reset compacted_summary."""
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        deleted = c.rowcount
        c.execute(
            "UPDATE sessions SET compacted_summary = NULL WHERE id = ?", (session_id,)
        )
        conn.commit()
        conn.close()
        return deleted

    def list_sessions(self, limit: int) -> List[Session]:
        """List recently created sessions."""
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT id, name, model, created_at, compacted_summary, memory_auto_extract, max_turns, last_used_at, research_mode, research_source_mode, research_local_corpus_paths FROM sessions ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        rows = c.fetchall()
        conn.close()
        return [self._session_from_row(r) for r in rows]

    def update_session_max_turns(self, session_id: int, max_turns: int) -> None:
        """Update the maximum turns explicitly set for a session."""
        conn = self._get_conn()
        c = conn.cursor()
        c.execute(
            "UPDATE sessions SET max_turns = ? WHERE id = ?",
            (max_turns, session_id),
        )
        conn.commit()
        conn.close()

    def update_session_last_used(self, session_id: int) -> None:
        """Update the last used timestamp for a session."""
        conn = self._get_conn()
        c = conn.cursor()
        timestamp = datetime.now().isoformat()
        c.execute(
            "UPDATE sessions SET last_used_at = ? WHERE id = ?",
            (timestamp, session_id),
        )
        conn.commit()
        conn.close()

    def update_session_research_profile(
        self,
        session_id: int,
        *,
        research_mode: bool,
        research_source_mode: Optional[str],
        research_local_corpus_paths: Optional[List[str]],
    ) -> None:
        """Persist research mode/profile metadata for a session."""
        conn = self._get_conn()
        c = conn.cursor()
        normalized_mode = _normalize_research_source_mode(research_source_mode)
        if research_source_mode and normalized_mode is None:
            conn.close()
            raise ValueError(f"Invalid research_source_mode: {research_source_mode!r}")
        serialized_paths = _serialize_local_corpus_paths(research_local_corpus_paths)
        c.execute(
            "UPDATE sessions SET research_mode = ?, research_source_mode = ?, research_local_corpus_paths = ? WHERE id = ?",
            (
                int(research_mode),
                normalized_mode,
                serialized_paths,
                session_id,
            ),
        )
        conn.commit()
        conn.close()

    def get_first_message_preview(self, session_id: int, max_chars: int = 50) -> str:
        """Get the first user message from a session for display purposes."""
        conn = self._get_conn()
        c = conn.cursor()
        c.execute(
            "SELECT content FROM messages WHERE session_id = ? AND role = 'user' ORDER BY timestamp ASC LIMIT 1",
            (session_id,),
        )
        row = c.fetchone()
        conn.close()
        if row and row[0]:
            content = row[0]
            return content[:max_chars] + "..." if len(content) > max_chars else content
        return ""

    def _next_session_transcript_id(
        self, conn: sqlite3.Connection, session_id: int
    ) -> int:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COALESCE(MAX(session_transcript_id), 0) FROM transcripts WHERE session_id = ?",
            (session_id,),
        )
        row = cursor.fetchone()
        return int((row[0] if row else 0) or 0) + 1

    def _next_session_image_id(self, conn: sqlite3.Connection, session_id: int) -> int:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COALESCE(MAX(session_image_id), 0) FROM image_transcripts WHERE session_id = ?",
            (session_id,),
        )
        row = cursor.fetchone()
        return int((row[0] if row else 0) or 0) + 1

    def create_transcript(
        self,
        *,
        session_id: int,
        jid: str,
        audio_url: str,
        audio_path: str,
        status: str,
        transcript_text: str = "",
        error: str = "",
        duration_seconds: Optional[float] = None,
    ) -> TranscriptRecord:
        """Create a session-scoped transcript row."""
        self.init_db()
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        session_transcript_id = self._next_session_transcript_id(conn, session_id)
        now = datetime.now().isoformat()
        cursor.execute(
            """
            INSERT INTO transcripts
            (session_id, session_transcript_id, jid, created_at, status, audio_url, audio_path, transcript_text, error, duration_seconds, used)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                session_id,
                session_transcript_id,
                jid,
                now,
                status,
                audio_url,
                audio_path,
                transcript_text,
                error,
                duration_seconds,
            ),
        )
        transcript_row_id = int(cursor.lastrowid)
        conn.commit()
        cursor.execute("SELECT * FROM transcripts WHERE id = ?", (transcript_row_id,))
        row = cursor.fetchone()
        conn.close()
        if row is None:
            raise RuntimeError("Failed to create transcript record")
        return self._transcript_from_row(row)

    def update_transcript(
        self,
        *,
        session_id: int,
        session_transcript_id: int,
        status: str,
        transcript_text: Optional[str] = None,
        error: Optional[str] = None,
        duration_seconds: Optional[float] = None,
        used: Optional[bool] = None,
    ) -> Optional[TranscriptRecord]:
        """Update transcript status/content for one session-scoped ID."""
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        fields = ["status = ?"]
        values: list[object] = [status]

        if transcript_text is not None:
            fields.append("transcript_text = ?")
            values.append(transcript_text)
        if error is not None:
            fields.append("error = ?")
            values.append(error)
        if duration_seconds is not None:
            fields.append("duration_seconds = ?")
            values.append(float(duration_seconds))
        if used is not None:
            fields.append("used = ?")
            values.append(1 if used else 0)

        values.extend([session_id, session_transcript_id])
        cursor.execute(
            f"UPDATE transcripts SET {', '.join(fields)} WHERE session_id = ? AND session_transcript_id = ?",
            tuple(values),
        )
        conn.commit()
        cursor.execute(
            "SELECT * FROM transcripts WHERE session_id = ? AND session_transcript_id = ?",
            (session_id, session_transcript_id),
        )
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return None
        return self._transcript_from_row(row)

    def list_transcripts(
        self, *, session_id: int, limit: int = 20
    ) -> List[TranscriptRecord]:
        """List transcripts for a session in newest-first order."""
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM transcripts
            WHERE session_id = ?
            ORDER BY session_transcript_id DESC
            LIMIT ?
            """,
            (session_id, int(limit)),
        )
        rows = cursor.fetchall()
        conn.close()
        return [self._transcript_from_row(row) for row in rows]

    def get_transcript(
        self,
        *,
        session_id: int,
        session_transcript_id: int,
    ) -> Optional[TranscriptRecord]:
        """Get one transcript by session-scoped identifier."""
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM transcripts
            WHERE session_id = ? AND session_transcript_id = ?
            LIMIT 1
            """,
            (session_id, session_transcript_id),
        )
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return None
        return self._transcript_from_row(row)

    def prune_transcripts(
        self, *, session_id: int, keep: int
    ) -> List[TranscriptRecord]:
        """Prune oldest transcripts beyond the keep threshold."""
        keep_count = max(0, int(keep))
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM transcripts WHERE session_id = ?",
            (session_id,),
        )
        total_row = cursor.fetchone()
        total = int((total_row[0] if total_row else 0) or 0)
        if total <= keep_count:
            conn.close()
            return []

        delete_count = total - keep_count
        cursor.execute(
            """
            SELECT * FROM transcripts
            WHERE session_id = ?
            ORDER BY session_transcript_id ASC
            LIMIT ?
            """,
            (session_id, delete_count),
        )
        rows = cursor.fetchall()
        deleted = [self._transcript_from_row(row) for row in rows]
        if deleted:
            ids = [record.id for record in deleted]
            placeholder = ",".join("?" for _ in ids)
            cursor.execute(
                f"DELETE FROM transcripts WHERE id IN ({placeholder})",
                tuple(ids),
            )
            conn.commit()
        conn.close()
        return deleted

    def create_image_transcript(
        self,
        *,
        session_id: int,
        jid: str,
        image_url: str,
        image_path: str,
        status: str,
        transcript_text: str = "",
        error: str = "",
        duration_seconds: Optional[float] = None,
    ) -> ImageTranscriptRecord:
        """Create a session-scoped image transcript row."""
        self.init_db()
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        session_image_id = self._next_session_image_id(conn, session_id)
        now = datetime.now().isoformat()
        cursor.execute(
            """
            INSERT INTO image_transcripts
            (session_id, session_image_id, jid, created_at, status, image_url, image_path, transcript_text, error, duration_seconds, used)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                session_id,
                session_image_id,
                jid,
                now,
                status,
                image_url,
                image_path,
                transcript_text,
                error,
                duration_seconds,
            ),
        )
        transcript_row_id = int(cursor.lastrowid)
        conn.commit()
        cursor.execute(
            "SELECT * FROM image_transcripts WHERE id = ?", (transcript_row_id,)
        )
        row = cursor.fetchone()
        conn.close()
        if row is None:
            raise RuntimeError("Failed to create image transcript record")
        return self._image_transcript_from_row(row)

    def update_image_transcript(
        self,
        *,
        session_id: int,
        session_image_id: int,
        status: str,
        transcript_text: Optional[str] = None,
        error: Optional[str] = None,
        duration_seconds: Optional[float] = None,
        used: Optional[bool] = None,
    ) -> Optional[ImageTranscriptRecord]:
        """Update image transcript status/content for one session-scoped ID."""
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        fields = ["status = ?"]
        values: list[object] = [status]

        if transcript_text is not None:
            fields.append("transcript_text = ?")
            values.append(transcript_text)
        if error is not None:
            fields.append("error = ?")
            values.append(error)
        if duration_seconds is not None:
            fields.append("duration_seconds = ?")
            values.append(float(duration_seconds))
        if used is not None:
            fields.append("used = ?")
            values.append(1 if used else 0)

        values.extend([session_id, session_image_id])
        cursor.execute(
            f"UPDATE image_transcripts SET {', '.join(fields)} WHERE session_id = ? AND session_image_id = ?",
            tuple(values),
        )
        conn.commit()
        cursor.execute(
            "SELECT * FROM image_transcripts WHERE session_id = ? AND session_image_id = ?",
            (session_id, session_image_id),
        )
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return None
        return self._image_transcript_from_row(row)

    def list_image_transcripts(
        self,
        *,
        session_id: int,
        limit: int = 20,
    ) -> List[ImageTranscriptRecord]:
        """List image transcripts for a session in newest-first order."""
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM image_transcripts
            WHERE session_id = ?
            ORDER BY session_image_id DESC
            LIMIT ?
            """,
            (session_id, int(limit)),
        )
        rows = cursor.fetchall()
        conn.close()
        return [self._image_transcript_from_row(row) for row in rows]

    def get_image_transcript(
        self,
        *,
        session_id: int,
        session_image_id: int,
    ) -> Optional[ImageTranscriptRecord]:
        """Get one image transcript by session-scoped identifier."""
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM image_transcripts
            WHERE session_id = ? AND session_image_id = ?
            LIMIT 1
            """,
            (session_id, session_image_id),
        )
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return None
        return self._image_transcript_from_row(row)

    def prune_image_transcripts(
        self, *, session_id: int, keep: int
    ) -> List[ImageTranscriptRecord]:
        """Prune oldest image transcripts beyond the keep threshold."""
        keep_count = max(0, int(keep))
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM image_transcripts WHERE session_id = ?",
            (session_id,),
        )
        total_row = cursor.fetchone()
        total = int((total_row[0] if total_row else 0) or 0)
        if total <= keep_count:
            conn.close()
            return []

        delete_count = total - keep_count
        cursor.execute(
            """
            SELECT * FROM image_transcripts
            WHERE session_id = ?
            ORDER BY session_image_id ASC
            LIMIT ?
            """,
            (session_id, delete_count),
        )
        rows = cursor.fetchall()
        deleted = [self._image_transcript_from_row(row) for row in rows]
        if deleted:
            ids = [record.id for record in deleted]
            placeholder = ",".join("?" for _ in ids)
            cursor.execute(
                f"DELETE FROM image_transcripts WHERE id IN ({placeholder})",
                tuple(ids),
            )
            conn.commit()
        conn.close()
        return deleted

    def set_room_session_binding(self, *, room_jid: str, session_id: int) -> None:
        """Create or update one room -> session binding."""
        normalized_room = str(room_jid or "").strip().lower()
        if not normalized_room:
            raise ValueError("room_jid is required")
        now = datetime.now().isoformat()
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO room_session_bindings (room_jid, session_id, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(room_jid) DO UPDATE
            SET session_id = excluded.session_id,
                updated_at = excluded.updated_at
            """,
            (normalized_room, int(session_id), now),
        )
        conn.commit()
        conn.close()

    def get_room_session_binding(
        self, *, room_jid: str
    ) -> Optional[RoomSessionBinding]:
        """Fetch one room binding by room JID."""
        normalized_room = str(room_jid or "").strip().lower()
        if not normalized_room:
            return None
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT room_jid, session_id, updated_at
            FROM room_session_bindings
            WHERE room_jid = ?
            LIMIT 1
            """,
            (normalized_room,),
        )
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return None
        return self._room_binding_from_row(row)

    def list_room_session_bindings(self) -> List[RoomSessionBinding]:
        """List all room bindings."""
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT room_jid, session_id, updated_at
            FROM room_session_bindings
            ORDER BY updated_at DESC
            """
        )
        rows = cursor.fetchall()
        conn.close()
        return [self._room_binding_from_row(row) for row in rows]

    def save_session_override_file(
        self,
        *,
        session_id: int,
        filename: str,
        content: str,
    ) -> None:
        """Persist one session override file snapshot (replace semantics)."""
        normalized_name = str(filename or "").strip().lower()
        if not normalized_name:
            raise ValueError("filename is required")
        now = datetime.now().isoformat()
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO session_override_files (session_id, filename, content, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(session_id, filename) DO UPDATE
            SET content = excluded.content,
                updated_at = excluded.updated_at
            """,
            (int(session_id), normalized_name, str(content or ""), now),
        )
        conn.commit()
        conn.close()

    def get_session_override_file(
        self,
        *,
        session_id: int,
        filename: str,
    ) -> Optional[SessionOverrideFile]:
        """Fetch one override file for a session."""
        normalized_name = str(filename or "").strip().lower()
        if not normalized_name:
            return None
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT session_id, filename, content, updated_at
            FROM session_override_files
            WHERE session_id = ? AND filename = ?
            LIMIT 1
            """,
            (int(session_id), normalized_name),
        )
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return None
        return self._session_override_from_row(row)

    def list_session_override_files(
        self, *, session_id: int
    ) -> List[SessionOverrideFile]:
        """List all override files for one session."""
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT session_id, filename, content, updated_at
            FROM session_override_files
            WHERE session_id = ?
            ORDER BY filename ASC
            """,
            (int(session_id),),
        )
        rows = cursor.fetchall()
        conn.close()
        return [self._session_override_from_row(row) for row in rows]

    def copy_session_override_files(
        self,
        *,
        source_session_id: int,
        target_session_id: int,
    ) -> int:
        """Copy all override file snapshots from source to target session."""
        source_id = int(source_session_id)
        target_id = int(target_session_id)
        if source_id == target_id:
            return 0
        existing = self.list_session_override_files(session_id=source_id)
        copied = 0
        for item in existing:
            self.save_session_override_file(
                session_id=target_id,
                filename=item.filename,
                content=item.content,
            )
            copied += 1
        return copied

    def get_interaction_by_id(self, interaction_id: int) -> Optional[Interaction]:
        """Fetch a single interaction (assistant message id) with its details."""
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("SELECT * FROM messages WHERE id = ?", (interaction_id,))
        row = c.fetchone()

        if not row:
            conn.close()
            return None

        # If it's an assistant message, try to find the query
        query = ""
        answer = ""
        role = row["role"]

        if role == "assistant":
            answer = row["content"]
            # Try to find preceding user message (same session or history pair)
            if row["session_id"]:
                c.execute(
                    "SELECT content FROM messages WHERE session_id=? AND role='user' AND id < ? ORDER BY id DESC LIMIT 1",
                    (row["session_id"], interaction_id),
                )
            else:
                c.execute(
                    "SELECT content FROM messages WHERE session_id IS NULL AND role='user' AND id < ? ORDER BY id DESC LIMIT 1",
                    (interaction_id,),
                )
            q_row = c.fetchone()
            if q_row:
                query = q_row["content"]
        elif role == "user":
            query = row["content"]
            # Try to find succeeding assistant message (same session or history pair)
            if row["session_id"]:
                c.execute(
                    "SELECT content FROM messages WHERE session_id=? AND role='assistant' AND id > ? ORDER BY id ASC LIMIT 1",
                    (row["session_id"], interaction_id),
                )
            else:
                c.execute(
                    "SELECT content FROM messages WHERE session_id IS NULL AND role='assistant' AND id > ? ORDER BY id ASC LIMIT 1",
                    (interaction_id,),
                )
            a_row = c.fetchone()
            if a_row:
                answer = a_row["content"]

        conn.close()

        return Interaction(
            id=row["id"],
            timestamp=row["timestamp"],
            session_id=row["session_id"],
            role=role,
            content=row["content"],
            query=query,
            answer=answer,
            summary=row["summary"],
            model=row["model"],
            token_count=row["token_count"],
        )

    def get_last_interaction(self) -> Optional[Interaction]:
        """Fetch the most recent interaction (message) from the DB."""
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # Get the absolute last message ID
        c.execute("SELECT id FROM messages ORDER BY timestamp DESC, id DESC LIMIT 1")
        row = c.fetchone()
        conn.close()

        if row:
            return self.get_interaction_by_id(row["id"])
        return None

    def convert_history_to_session(self, interaction_id: int) -> int:
        """Convert a history interaction into a new session.

        Creates a new session and copies the interaction (user+assistant pair)
        into it. Returns the new session ID.
        """
        interaction = self.get_interaction_by_id(interaction_id)
        if not interaction:
            raise ValueError(f"Interaction {interaction_id} not found")

        if interaction.session_id is not None:
            # Already a session message, return that session ID
            return interaction.session_id

        user_content = ""
        user_summary = ""
        user_tokens = 0

        assistant_content = ""
        assistant_summary = ""
        assistant_tokens = 0

        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # If pointing to Assistant message, find User message.
        # If pointing to User message, find Assistant message.
        # We want to maintain order: User -> Assistant

        if interaction.role == "assistant":
            assistant_content = interaction.content
            assistant_summary = interaction.summary
            assistant_tokens = interaction.token_count

            # Find partner user message
            c.execute(
                "SELECT * FROM messages WHERE session_id IS NULL AND role='user' AND id < ? ORDER BY id DESC LIMIT 1",
                (interaction.id,),
            )
            u_row = c.fetchone()
            if u_row:
                user_content = u_row["content"]
                user_summary = u_row["summary"]
                user_tokens = u_row["token_count"]

        elif interaction.role == "user":
            user_content = interaction.content
            user_summary = interaction.summary
            user_tokens = interaction.token_count

            # Find partner assistant message
            c.execute(
                "SELECT * FROM messages WHERE session_id IS NULL AND role='assistant' AND id > ? ORDER BY id ASC LIMIT 1",
                (interaction.id,),
            )
            a_row = c.fetchone()
            if a_row:
                assistant_content = a_row["content"]
                assistant_summary = a_row["summary"]
                assistant_tokens = a_row["token_count"]

        conn.close()

        # Create Session Name
        session_name = _build_session_name_from_user_content(user_content)

        # Create Session
        new_session_id = self.create_session(model=interaction.model, name=session_name)

        # Copy User Message
        if user_content:
            self.save_message(
                session_id=new_session_id,
                role="user",
                content=user_content,
                summary=user_summary or "",
                token_count=user_tokens or 0,
            )

        # Copy Assistant Message
        if assistant_content:
            self.save_message(
                session_id=new_session_id,
                role="assistant",
                content=assistant_content,
                summary=assistant_summary or "",
                token_count=assistant_tokens or 0,
            )

        return new_session_id
