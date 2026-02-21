"""SQLite implementation of unified message and session storage."""

import os
import sqlite3
from datetime import datetime
from typing import List, Optional

from asky.config import DB_PATH
from asky.storage.interface import HistoryRepository, Interaction, Session


# Session dataclass (kept from session.py)


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
                compacted_summary TEXT,
                max_turns INTEGER
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

    def save_interaction(
        self,
        query: str,
        answer: str,
        model: str,
        query_summary: str = "",
        answer_summary: str = "",
    ) -> None:
        """Save a query and its answer as two separate message rows (User + Assistant)."""
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
        c = conn.cursor()
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
            conn.close()
            return ""

        placeholders = ",".join(["?"] * len(final_ids))

        # Fetch content and summary
        c.execute(
            f"SELECT id, role, content, summary FROM messages WHERE id IN ({placeholders}) ORDER BY id ASC",
            tuple(final_ids),
        )
        rows = c.fetchall()

        context_parts = []
        updates = []  # To hold IDs and their newly generated summaries

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
                    # Lazy Summarization: Only if the text is longer than the configured threshold
                    from asky.config import SUMMARIZATION_LAZY_THRESHOLD_CHARS

                    if content and len(content) > SUMMARIZATION_LAZY_THRESHOLD_CHARS:
                        from asky.summarization import generate_summaries
                        from asky.core.api_client import get_llm_msg

                        # Generate the missing summary based on role
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

        # Batch update any newly generated summaries back into the database
        if updates:
            c.executemany("UPDATE messages SET summary = ? WHERE id = ?", updates)
            conn.commit()

        conn.close()
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
    ) -> int:
        """Create a new session and return its ID."""
        conn = self._get_conn()
        c = conn.cursor()
        timestamp = datetime.now().isoformat()
        c.execute(
            "INSERT INTO sessions (name, model, created_at, memory_auto_extract, max_turns) VALUES (?, ?, ?, ?, ?)",
            (name, model, timestamp, int(memory_auto_extract), max_turns),
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
            "SELECT id, name, model, created_at, compacted_summary, memory_auto_extract, max_turns FROM sessions WHERE name = ? ORDER BY created_at DESC",
            (name,),
        )
        rows = c.fetchall()
        conn.close()
        return [
            Session(
                id=r["id"],
                name=r["name"],
                model=r["model"],
                created_at=r["created_at"],
                compacted_summary=r["compacted_summary"],
                memory_auto_extract=bool(r["memory_auto_extract"]),
                max_turns=r["max_turns"],
            )
            for r in rows
        ]

    def get_session_by_id(self, session_id: int) -> Optional[Session]:
        """Look up a session by ID."""
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT id, name, model, created_at, compacted_summary, memory_auto_extract, max_turns FROM sessions WHERE id = ?",
            (session_id,),
        )
        row = c.fetchone()
        conn.close()
        if row:
            return Session(
                id=row["id"],
                name=row["name"],
                model=row["model"],
                created_at=row["created_at"],
                compacted_summary=row["compacted_summary"],
                memory_auto_extract=bool(row["memory_auto_extract"]),
                max_turns=row["max_turns"],
            )
        return None

    def get_session_by_name(self, name: str) -> Optional[Session]:
        """Look up the most recent session by name."""
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT id, name, model, created_at, compacted_summary, memory_auto_extract, max_turns FROM sessions WHERE name = ? ORDER BY created_at DESC LIMIT 1",
            (name,),
        )
        row = c.fetchone()
        conn.close()
        if row:
            return Session(
                id=row["id"],
                name=row["name"],
                model=row["model"],
                created_at=row["created_at"],
                compacted_summary=row["compacted_summary"],
                memory_auto_extract=bool(row["memory_auto_extract"]),
                max_turns=row["max_turns"],
            )
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
            (timestamp, session_id, role, content, summary, model, token_count) 
            VALUES (?, ?, ?, ?, ?, '', ?)""",
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

    def list_sessions(self, limit: int) -> List[Session]:
        """List recently created sessions."""
        conn = self._get_conn()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT id, name, model, created_at, compacted_summary, memory_auto_extract, max_turns FROM sessions ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        rows = c.fetchall()
        conn.close()
        return [
            Session(
                id=r["id"],
                name=r["name"],
                model=r["model"],
                created_at=r["created_at"],
                compacted_summary=r["compacted_summary"],
                memory_auto_extract=bool(r["memory_auto_extract"]),
                max_turns=r["max_turns"],
            )
            for r in rows
        ]

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
        session_name = "New Session"
        if user_content:
            lines = user_content.split("\\n")
            first_line = lines[0].strip()
            session_name = (
                (first_line[:30] + "...") if len(first_line) > 30 else first_line
            )

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
