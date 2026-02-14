"""Research cache with TTL and background summarization."""

import hashlib
import json
import logging
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from asky.config import (
    DB_PATH,
    RESEARCH_CACHE_TTL_HOURS,
    RESEARCH_SUMMARIZATION_WORKERS,
    SUMMARIZE_PAGE_PROMPT,
)

logger = logging.getLogger(__name__)
CHUNK_FTS_TABLE_NAME = "content_chunks_fts"
BACKGROUND_SUMMARY_INPUT_CHARS = 24000
BACKGROUND_SUMMARY_MAX_OUTPUT_CHARS = 800


class ResearchCache:
    """Manages URL content caching with TTL and background processing."""

    _instance: Optional["ResearchCache"] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        """Singleton pattern to ensure single cache instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(
        self,
        db_path: str = None,
        ttl_hours: int = None,
        summarization_workers: int = None,
    ):
        # Skip re-initialization for singleton
        if self._initialized:
            return

        self.db_path = db_path or str(DB_PATH)
        self.ttl_hours = ttl_hours or RESEARCH_CACHE_TTL_HOURS
        self._summarization_workers = (
            summarization_workers or RESEARCH_SUMMARIZATION_WORKERS
        )
        self._executor: Optional[ThreadPoolExecutor] = None
        self._db_lock = threading.Lock()
        self._initialized = True
        self.init_db()

    def _get_executor(self) -> ThreadPoolExecutor:
        """Lazy initialization of thread pool executor."""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=self._summarization_workers,
                thread_name_prefix="research_summarizer",
            )
        return self._executor

    def _get_conn(self) -> sqlite3.Connection:
        """Get a database connection."""
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def init_db(self) -> None:
        """Initialize research cache tables."""
        conn = self._get_conn()
        c = conn.cursor()

        # Main research cache table
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS research_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                url_hash TEXT NOT NULL,
                content TEXT,
                title TEXT,
                summary TEXT,
                summary_status TEXT DEFAULT 'pending',
                links_json TEXT,
                fetch_timestamp TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                content_hash TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """
        )

        c.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_research_cache_url_hash
            ON research_cache(url_hash)
        """
        )

        c.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_research_cache_expires
            ON research_cache(expires_at)
        """
        )

        # Content chunks table for RAG
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS content_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cache_id INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                chunk_text TEXT NOT NULL,
                embedding BLOB,
                embedding_model TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (cache_id) REFERENCES research_cache(id) ON DELETE CASCADE,
                UNIQUE(cache_id, chunk_index)
            )
        """
        )

        c.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chunks_cache_id
            ON content_chunks(cache_id)
        """
        )
        self._init_chunk_fts_index(c)

        # Link embeddings table for relevance filtering
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS link_embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cache_id INTEGER NOT NULL,
                link_text TEXT NOT NULL,
                link_url TEXT NOT NULL,
                embedding BLOB,
                embedding_model TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (cache_id) REFERENCES research_cache(id) ON DELETE CASCADE,
                UNIQUE(cache_id, link_url)
            )
        """
        )

        c.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_link_embeddings_cache_id
            ON link_embeddings(cache_id)
        """
        )

        self._ensure_column(
            cursor=c,
            table_name="link_embeddings",
            column_name="embedding_model",
            column_sql_type="TEXT",
        )

        # Research findings table for persistent memory across sessions
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS research_findings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                finding_text TEXT NOT NULL,
                source_url TEXT,
                source_title TEXT,
                tags TEXT,
                embedding BLOB,
                embedding_model TEXT,
                created_at TEXT NOT NULL,
                session_id TEXT
            )
        """
        )

        c.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_findings_created
            ON research_findings(created_at)
        """
        )

        conn.commit()
        conn.close()
        logger.debug("Research cache database initialized")

    def _init_chunk_fts_index(self, cursor: sqlite3.Cursor) -> None:
        """Initialize FTS index and triggers for chunk_text BM25 search."""
        try:
            cursor.execute(
                f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS {CHUNK_FTS_TABLE_NAME}
                USING fts5(
                    chunk_text,
                    content='content_chunks',
                    content_rowid='id'
                )
                """
            )
            cursor.execute(
                f"""
                CREATE TRIGGER IF NOT EXISTS content_chunks_ai
                AFTER INSERT ON content_chunks
                BEGIN
                    INSERT INTO {CHUNK_FTS_TABLE_NAME}(rowid, chunk_text)
                    VALUES (new.id, new.chunk_text);
                END
                """
            )
            cursor.execute(
                f"""
                CREATE TRIGGER IF NOT EXISTS content_chunks_ad
                AFTER DELETE ON content_chunks
                BEGIN
                    INSERT INTO {CHUNK_FTS_TABLE_NAME}({CHUNK_FTS_TABLE_NAME}, rowid, chunk_text)
                    VALUES('delete', old.id, old.chunk_text);
                END
                """
            )
            cursor.execute(
                f"""
                CREATE TRIGGER IF NOT EXISTS content_chunks_au
                AFTER UPDATE ON content_chunks
                BEGIN
                    INSERT INTO {CHUNK_FTS_TABLE_NAME}({CHUNK_FTS_TABLE_NAME}, rowid, chunk_text)
                    VALUES('delete', old.id, old.chunk_text);
                    INSERT INTO {CHUNK_FTS_TABLE_NAME}(rowid, chunk_text)
                    VALUES (new.id, new.chunk_text);
                END
                """
            )

            # Ensure legacy rows (before trigger/index creation) are indexed.
            cursor.execute(
                f"INSERT INTO {CHUNK_FTS_TABLE_NAME}({CHUNK_FTS_TABLE_NAME}) VALUES('rebuild')"
            )
        except sqlite3.OperationalError as exc:
            logger.warning(f"FTS5 unavailable, BM25 lexical search disabled: {exc}")

    def _ensure_column(
        self,
        cursor: sqlite3.Cursor,
        table_name: str,
        column_name: str,
        column_sql_type: str,
    ) -> None:
        """Add a missing column for backward-compatible schema evolution."""
        cursor.execute(f"PRAGMA table_info({table_name})")
        existing_columns = {row[1] for row in cursor.fetchall()}
        if column_name in existing_columns:
            return
        cursor.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql_type}"
        )

    def _clear_stale_vectors(
        self,
        cursor: sqlite3.Cursor,
        cache_id: int,
        clear_chunks: bool,
        clear_links: bool,
    ) -> None:
        """Remove stale vector rows tied to outdated cached payloads."""
        if clear_chunks:
            cursor.execute("DELETE FROM content_chunks WHERE cache_id = ?", (cache_id,))
        if clear_links:
            cursor.execute(
                "DELETE FROM link_embeddings WHERE cache_id = ?", (cache_id,)
            )
        if clear_chunks or clear_links:
            self._clear_chroma_vectors(
                cache_id=cache_id,
                clear_chunks=clear_chunks,
                clear_links=clear_links,
            )

    def _clear_chroma_vectors(
        self,
        cache_id: int,
        clear_chunks: bool = True,
        clear_links: bool = True,
    ) -> None:
        """Best-effort cleanup of Chroma vectors for a specific cache entry."""
        try:
            from asky.research.vector_store import get_vector_store

            get_vector_store().clear_cache_embeddings(
                cache_id=cache_id,
                clear_chunks=clear_chunks,
                clear_links=clear_links,
            )
        except Exception as exc:
            logger.debug(
                "Skipping Chroma vector cleanup for cache_id=%s: %s", cache_id, exc
            )

    def _clear_chroma_vectors_bulk(
        self,
        cache_ids: List[int],
        clear_chunks: bool = True,
        clear_links: bool = True,
    ) -> None:
        """Best-effort cleanup of Chroma vectors for multiple cache entries."""
        if not cache_ids:
            return
        try:
            from asky.research.vector_store import get_vector_store

            get_vector_store().clear_cache_embeddings_bulk(
                cache_ids=cache_ids,
                clear_chunks=clear_chunks,
                clear_links=clear_links,
            )
        except Exception as exc:
            logger.debug("Skipping Chroma bulk vector cleanup: %s", exc)

    def _url_hash(self, url: str) -> str:
        """Generate hash for URL."""
        return hashlib.sha256(url.encode()).hexdigest()[:16]

    def _content_hash(self, content: str) -> str:
        """Generate hash for content change detection."""
        return hashlib.md5(content.encode()).hexdigest()

    def get_cached(self, url: str) -> Optional[Dict[str, Any]]:
        """Get cached content if valid (not expired)."""
        conn = self._get_conn()
        c = conn.cursor()

        now = datetime.now().isoformat()
        c.execute(
            """
            SELECT id, content, title, summary, summary_status, links_json,
                   fetch_timestamp, expires_at
            FROM research_cache
            WHERE url_hash = ? AND expires_at > ?
        """,
            (self._url_hash(url), now),
        )

        row = c.fetchone()
        conn.close()

        if row:
            return {
                "id": row[0],
                "content": row[1],
                "title": row[2],
                "summary": row[3],
                "summary_status": row[4],
                "links": json.loads(row[5]) if row[5] else [],
                "fetch_timestamp": row[6],
                "expires_at": row[7],
                "cached": True,
            }
        return None

    def get_cache_id(self, url: str) -> Optional[int]:
        """Get cache ID for a URL if it exists and is valid."""
        cached = self.get_cached(url)
        return cached["id"] if cached else None

    def cache_url(
        self,
        url: str,
        content: str,
        title: str,
        links: List[Dict[str, str]],
        trigger_summarization: bool = True,
    ) -> int:
        """Cache URL content and optionally trigger background summarization.

        Returns the cache ID.
        """
        now = datetime.now()
        expires = now + timedelta(hours=self.ttl_hours)
        url_hash = self._url_hash(url)
        content_hash = self._content_hash(content)
        links_json = json.dumps(links)

        with self._db_lock:
            conn = self._get_conn()
            c = conn.cursor()

            # Check if content changed (for re-summarization)
            c.execute(
                "SELECT id, content_hash, links_json FROM research_cache WHERE url_hash = ?",
                (url_hash,),
            )
            existing = c.fetchone()

            content_changed = True
            links_changed = True
            if existing:
                old_hash = existing[1]
                old_links_json = existing[2]
                content_changed = old_hash != content_hash
                links_changed = old_links_json != links_json

            c.execute(
                """
                INSERT INTO research_cache
                (url, url_hash, content, title, summary_status, links_json,
                 fetch_timestamp, expires_at, content_hash, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    content = excluded.content,
                    title = excluded.title,
                    links_json = excluded.links_json,
                    fetch_timestamp = excluded.fetch_timestamp,
                    expires_at = excluded.expires_at,
                    content_hash = excluded.content_hash,
                    updated_at = excluded.updated_at,
                    summary_status = CASE
                        WHEN research_cache.content_hash != excluded.content_hash
                        THEN 'pending'
                        ELSE research_cache.summary_status
                    END,
                    summary = CASE
                        WHEN research_cache.content_hash != excluded.content_hash
                        THEN NULL
                        ELSE research_cache.summary
                    END
            """,
                (
                    url,
                    url_hash,
                    content,
                    title,
                    links_json,
                    now.isoformat(),
                    expires.isoformat(),
                    content_hash,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )

            # Get the cache_id (either from insert or existing)
            if c.lastrowid:
                cache_id = c.lastrowid
            else:
                c.execute(
                    "SELECT id FROM research_cache WHERE url_hash = ?", (url_hash,)
                )
                result = c.fetchone()
                cache_id = result[0] if result else 0

            if existing:
                self._clear_stale_vectors(
                    cursor=c,
                    cache_id=cache_id,
                    clear_chunks=content_changed,
                    clear_links=links_changed,
                )

            conn.commit()
            conn.close()

        # Trigger background summarization if content changed
        if trigger_summarization and content_changed and content:
            self._schedule_summarization(cache_id, url, content)

        logger.debug(f"Cached URL {url} with id={cache_id}")
        return cache_id

    def _schedule_summarization(self, cache_id: int, url: str, content: str) -> None:
        """Schedule background summarization task."""

        def summarize_task():
            try:
                self._update_summary_status(cache_id, "processing")

                # Import here to avoid circular imports
                from asky.summarization import _summarize_content

                summary = _summarize_content(
                    content=content[:BACKGROUND_SUMMARY_INPUT_CHARS],
                    prompt_template=SUMMARIZE_PAGE_PROMPT,
                    max_output_chars=BACKGROUND_SUMMARY_MAX_OUTPUT_CHARS,
                )

                self._save_summary(cache_id, summary)
                logger.debug(f"Background summarization completed for {url}")

            except Exception as e:
                logger.error(f"Background summarization failed for {url}: {e}")
                self._update_summary_status(cache_id, "failed")

        executor = self._get_executor()
        executor.submit(summarize_task)
        logger.debug(f"Scheduled background summarization for {url}")

    def _update_summary_status(self, cache_id: int, status: str) -> None:
        """Update summary status in database."""
        with self._db_lock:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute(
                "UPDATE research_cache SET summary_status = ?, updated_at = ? WHERE id = ?",
                (status, datetime.now().isoformat(), cache_id),
            )
            conn.commit()
            conn.close()

    def _save_summary(self, cache_id: int, summary: str) -> None:
        """Save generated summary to cache."""
        with self._db_lock:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute(
                "UPDATE research_cache SET summary = ?, summary_status = 'completed', updated_at = ? WHERE id = ?",
                (summary, datetime.now().isoformat(), cache_id),
            )
            conn.commit()
            conn.close()

    def get_links_only(self, url: str) -> Optional[List[Dict[str, str]]]:
        """Get only links from cached content."""
        cached = self.get_cached(url)
        return cached["links"] if cached else None

    def get_summary(self, url: str) -> Optional[Dict[str, Any]]:
        """Get summary info from cache."""
        cached = self.get_cached(url)
        if cached:
            return {
                "title": cached.get("title", ""),
                "summary": cached.get("summary"),
                "summary_status": cached.get("summary_status", "unknown"),
            }
        return None

    def get_content(self, url: str) -> Optional[str]:
        """Get full content from cache."""
        cached = self.get_cached(url)
        return cached["content"] if cached else None

    def cleanup_expired(self) -> int:
        """Remove expired cache entries and their related data."""
        with self._db_lock:
            conn = self._get_conn()
            c = conn.cursor()

            now = datetime.now().isoformat()

            # Get IDs of expired entries first
            c.execute("SELECT id FROM research_cache WHERE expires_at < ?", (now,))
            expired_ids = [row[0] for row in c.fetchall()]

            if expired_ids:
                self._clear_chroma_vectors_bulk(expired_ids)
                placeholders = ",".join("?" * len(expired_ids))

                # Delete related chunks
                c.execute(
                    f"DELETE FROM content_chunks WHERE cache_id IN ({placeholders})",
                    expired_ids,
                )

                # Delete related link embeddings
                c.execute(
                    f"DELETE FROM link_embeddings WHERE cache_id IN ({placeholders})",
                    expired_ids,
                )

                # Delete cache entries
                c.execute(
                    f"DELETE FROM research_cache WHERE id IN ({placeholders})",
                    expired_ids,
                )

            deleted = len(expired_ids)
            conn.commit()
            conn.close()

        if deleted:
            logger.info(f"Cleaned up {deleted} expired cache entries")
        return deleted

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        conn = self._get_conn()
        c = conn.cursor()

        now = datetime.now().isoformat()

        c.execute("SELECT COUNT(*) FROM research_cache")
        total = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM research_cache WHERE expires_at > ?", (now,))
        valid = c.fetchone()[0]

        c.execute(
            "SELECT COUNT(*) FROM research_cache WHERE summary_status = 'completed'"
        )
        summarized = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM content_chunks")
        chunks = c.fetchone()[0]

        conn.close()

        return {
            "total_entries": total,
            "valid_entries": valid,
            "expired_entries": total - valid,
            "summarized_entries": summarized,
            "total_chunks": chunks,
        }

    def save_finding(
        self,
        finding_text: str,
        source_url: Optional[str] = None,
        source_title: Optional[str] = None,
        tags: Optional[List[str]] = None,
        session_id: Optional[str] = None,
    ) -> int:
        """Save a research finding to persistent memory.

        Args:
            finding_text: The fact or insight discovered.
            source_url: URL where this was found.
            source_title: Title of the source page.
            tags: List of tags for categorization.
            session_id: Optional session identifier for grouping.

        Returns:
            The ID of the saved finding.
        """
        now = datetime.now().isoformat()
        tags_json = json.dumps(tags) if tags else None

        with self._db_lock:
            conn = self._get_conn()
            c = conn.cursor()

            c.execute(
                """
                INSERT INTO research_findings
                (finding_text, source_url, source_title, tags, created_at, session_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (finding_text, source_url, source_title, tags_json, now, session_id),
            )

            finding_id = c.lastrowid
            conn.commit()
            conn.close()

        logger.debug(f"Saved finding id={finding_id}")
        return finding_id

    def get_finding(self, finding_id: int) -> Optional[Dict[str, Any]]:
        """Get a specific finding by ID."""
        conn = self._get_conn()
        c = conn.cursor()

        c.execute(
            """
            SELECT id, finding_text, source_url, source_title, tags,
                   embedding, embedding_model, created_at, session_id
            FROM research_findings WHERE id = ?
        """,
            (finding_id,),
        )

        row = c.fetchone()
        conn.close()

        if row:
            return {
                "id": row[0],
                "finding_text": row[1],
                "source_url": row[2],
                "source_title": row[3],
                "tags": json.loads(row[4]) if row[4] else [],
                "has_embedding": row[5] is not None,
                "embedding_model": row[6],
                "created_at": row[7],
                "session_id": row[8],
            }
        return None

    def get_all_findings(
        self,
        limit: int = 100,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get all findings, optionally filtered by session.

        Args:
            limit: Maximum number of findings to return.
            session_id: Optional filter by session.

        Returns:
            List of finding dictionaries, most recent first.
        """
        conn = self._get_conn()
        c = conn.cursor()

        if session_id:
            c.execute(
                """
                SELECT id, finding_text, source_url, source_title, tags,
                       embedding IS NOT NULL as has_embedding, created_at, session_id
                FROM research_findings
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """,
                (session_id, limit),
            )
        else:
            c.execute(
                """
                SELECT id, finding_text, source_url, source_title, tags,
                       embedding IS NOT NULL as has_embedding, created_at, session_id
                FROM research_findings
                ORDER BY created_at DESC
                LIMIT ?
            """,
                (limit,),
            )

        rows = c.fetchall()
        conn.close()

        return [
            {
                "id": row[0],
                "finding_text": row[1],
                "source_url": row[2],
                "source_title": row[3],
                "tags": json.loads(row[4]) if row[4] else [],
                "has_embedding": bool(row[5]),
                "created_at": row[6],
                "session_id": row[7],
            }
            for row in rows
        ]

    def update_finding_embedding(
        self,
        finding_id: int,
        embedding: bytes,
        model: str,
    ) -> bool:
        """Update the embedding for a finding.

        Args:
            finding_id: The finding ID.
            embedding: Serialized embedding bytes.
            model: The embedding model used.

        Returns:
            True if updated, False if finding not found.
        """
        with self._db_lock:
            conn = self._get_conn()
            c = conn.cursor()

            c.execute(
                """
                UPDATE research_findings
                SET embedding = ?, embedding_model = ?
                WHERE id = ?
            """,
                (embedding, model, finding_id),
            )

            updated = c.rowcount > 0
            conn.commit()
            conn.close()

        return updated

    def delete_finding(self, finding_id: int) -> bool:
        """Delete a finding by ID.

        Args:
            finding_id: The finding ID to delete.

        Returns:
            True if deleted, False if not found.
        """
        with self._db_lock:
            conn = self._get_conn()
            c = conn.cursor()

            c.execute("DELETE FROM research_findings WHERE id = ?", (finding_id,))

            deleted = c.rowcount > 0
            conn.commit()
            conn.close()

        if deleted:
            logger.debug(f"Deleted finding id={finding_id}")
        return deleted

    def get_findings_count(self) -> int:
        """Get total number of findings in memory."""
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM research_findings")
        count = c.fetchone()[0]
        conn.close()
        return count

    def shutdown(self) -> None:
        """Shutdown the background executor gracefully."""
        if self._executor:
            logger.debug("Shutting down research cache executor...")
            self._executor.shutdown(wait=True)
            self._executor = None
            logger.debug("Research cache executor shutdown complete")
