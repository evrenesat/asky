"""Vector similarity search using cosine similarity."""

import json
import logging
import math
import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from asky.config import DB_PATH, RESEARCH_MAX_CHUNKS_PER_RETRIEVAL
from asky.research.embeddings import EmbeddingClient, get_embedding_client

logger = logging.getLogger(__name__)
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]{2,}")
DEFAULT_DENSE_WEIGHT = 0.75
CHUNK_FTS_TABLE_NAME = "content_chunks_fts"
HYBRID_LEXICAL_CANDIDATE_MULTIPLIER = 10


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors.

    Args:
        a: First vector.
        b: Second vector.

    Returns:
        Cosine similarity score between -1 and 1.
    """
    if not a or not b or len(a) != len(b):
        return 0.0

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)


def _tokenize_text(text: str) -> set[str]:
    """Tokenize text into normalized lexical terms."""
    if not text:
        return set()
    return {token.lower() for token in TOKEN_PATTERN.findall(text)}


def _lexical_overlap_score(query_tokens: set[str], text: str) -> float:
    """Compute simple lexical overlap ratio against query terms."""
    if not query_tokens:
        return 0.0
    chunk_tokens = _tokenize_text(text)
    if not chunk_tokens:
        return 0.0
    return len(query_tokens & chunk_tokens) / len(query_tokens)


class VectorStore:
    """Simple vector store using SQLite + in-memory similarity search."""

    _instance: Optional["VectorStore"] = None

    def __new__(cls, *args, **kwargs):
        """Singleton pattern for efficient reuse."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(
        self,
        db_path: str = None,
        embedding_client: EmbeddingClient = None,
    ):
        if self._initialized:
            return

        self.db_path = db_path or str(DB_PATH)
        self._embedding_client = embedding_client
        self._fts_available: Optional[bool] = None
        self._initialized = True

    @property
    def embedding_client(self) -> EmbeddingClient:
        """Lazy initialization of embedding client."""
        if self._embedding_client is None:
            self._embedding_client = get_embedding_client()
        return self._embedding_client

    def _get_conn(self) -> sqlite3.Connection:
        """Get a database connection."""
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _table_has_column(self, table_name: str, column_name: str) -> bool:
        """Check if a table has a given column name."""
        conn = self._get_conn()
        c = conn.cursor()
        c.execute(f"PRAGMA table_info({table_name})")
        columns = {row[1] for row in c.fetchall()}
        conn.close()
        return column_name in columns

    def _table_exists(self, table_name: str) -> bool:
        """Check if a table exists in the current SQLite database."""
        conn = self._get_conn()
        c = conn.cursor()
        c.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type IN ('table', 'view') AND name = ?
            LIMIT 1
            """,
            (table_name,),
        )
        exists = c.fetchone() is not None
        conn.close()
        return exists

    def _is_chunk_fts_available(self) -> bool:
        """Return whether chunk FTS table is available."""
        if self._fts_available is None:
            self._fts_available = self._table_exists(CHUNK_FTS_TABLE_NAME)
        return self._fts_available

    def _build_match_query(self, query: str) -> Optional[str]:
        """Build a safe FTS MATCH query from normalized query tokens."""
        tokens = sorted(_tokenize_text(query))
        if not tokens:
            return None
        quoted = [f'"{token}"' for token in tokens]
        return " AND ".join(quoted)

    def _get_bm25_scores(
        self, cache_id: int, query: str, limit: int
    ) -> Dict[int, float]:
        """Get normalized BM25 lexical scores keyed by chunk_index."""
        if not self._is_chunk_fts_available():
            return {}
        match_query = self._build_match_query(query)
        if not match_query:
            return {}

        try:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute(
                f"""
                SELECT cc.chunk_index, bm25({CHUNK_FTS_TABLE_NAME}) AS bm25_score
                FROM {CHUNK_FTS_TABLE_NAME}
                JOIN content_chunks cc ON cc.id = {CHUNK_FTS_TABLE_NAME}.rowid
                WHERE cc.cache_id = ? AND {CHUNK_FTS_TABLE_NAME} MATCH ?
                ORDER BY bm25_score ASC
                LIMIT ?
                """,
                (cache_id, match_query, limit),
            )
            rows = c.fetchall()
            conn.close()
        except sqlite3.OperationalError as exc:
            logger.warning(f"BM25 lexical scoring unavailable, falling back: {exc}")
            return {}

        if not rows:
            return {}

        raw_scores = [score for _, score in rows]
        min_score = min(raw_scores)
        max_score = max(raw_scores)
        if max_score == min_score:
            return {chunk_index: 1.0 for chunk_index, _ in rows}

        normalized_scores: Dict[int, float] = {}
        for chunk_index, bm25_score in rows:
            normalized = (max_score - bm25_score) / (max_score - min_score)
            normalized_scores[chunk_index] = max(0.0, min(1.0, normalized))
        return normalized_scores

    def store_chunk_embeddings(
        self,
        cache_id: int,
        chunks: List[Tuple[int, str]],
    ) -> int:
        """Generate and store embeddings for content chunks.

        Args:
            cache_id: The research_cache entry ID.
            chunks: List of (chunk_index, chunk_text) tuples.

        Returns:
            Number of chunks embedded and stored.
        """
        if not chunks:
            return 0

        try:
            # Generate embeddings in batch
            texts = [chunk[1] for chunk in chunks]
            embeddings = self.embedding_client.embed(texts)

            if len(embeddings) != len(chunks):
                logger.warning(
                    f"Embedding count mismatch: {len(embeddings)} vs {len(chunks)}"
                )
                return 0

            conn = self._get_conn()
            c = conn.cursor()
            now = datetime.now().isoformat()
            c.execute("DELETE FROM content_chunks WHERE cache_id = ?", (cache_id,))

            for (chunk_idx, chunk_text), embedding in zip(chunks, embeddings):
                embedding_bytes = EmbeddingClient.serialize_embedding(embedding)
                c.execute(
                    """
                    INSERT OR REPLACE INTO content_chunks
                    (cache_id, chunk_index, chunk_text, embedding, embedding_model, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (
                        cache_id,
                        chunk_idx,
                        chunk_text,
                        embedding_bytes,
                        self.embedding_client.model,
                        now,
                    ),
                )

            conn.commit()
            conn.close()

            logger.debug(f"Stored {len(chunks)} chunk embeddings for cache_id={cache_id}")
            return len(chunks)

        except Exception as e:
            logger.error(f"Failed to store chunk embeddings: {e}")
            return 0

    def store_link_embeddings(
        self,
        cache_id: int,
        links: List[Dict[str, str]],
    ) -> int:
        """Generate and store embeddings for links.

        Args:
            cache_id: The research_cache entry ID.
            links: List of link dicts with 'text' and 'href' keys.

        Returns:
            Number of links embedded and stored.
        """
        if not links:
            return 0

        try:
            # Combine link text and URL for embedding
            # This gives semantic meaning to both the label and the URL structure
            links_with_text = []
            texts = []
            for link in links:
                link_text = link.get("text", "")
                link_url = link.get("href", "")
                if not link_url:
                    continue
                combined = f"{link_text} - {link_url}".strip()
                if combined == "-":
                    continue
                links_with_text.append(link)
                texts.append(combined)

            if not texts:
                return 0

            embeddings = self.embedding_client.embed(texts)

            conn = self._get_conn()
            c = conn.cursor()
            now = datetime.now().isoformat()
            c.execute("DELETE FROM link_embeddings WHERE cache_id = ?", (cache_id,))
            has_embedding_model_column = self._table_has_column(
                "link_embeddings", "embedding_model"
            )

            stored = 0
            for link, embedding in zip(links_with_text, embeddings):
                embedding_bytes = EmbeddingClient.serialize_embedding(embedding)
                if has_embedding_model_column:
                    c.execute(
                        """
                        INSERT OR REPLACE INTO link_embeddings
                        (cache_id, link_text, link_url, embedding, embedding_model, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """,
                        (
                            cache_id,
                            link.get("text", ""),
                            link.get("href", ""),
                            embedding_bytes,
                            self.embedding_client.model,
                            now,
                        ),
                    )
                else:
                    c.execute(
                        """
                        INSERT OR REPLACE INTO link_embeddings
                        (cache_id, link_text, link_url, embedding, created_at)
                        VALUES (?, ?, ?, ?, ?)
                    """,
                        (
                            cache_id,
                            link.get("text", ""),
                            link.get("href", ""),
                            embedding_bytes,
                            now,
                        ),
                    )
                stored += 1

            conn.commit()
            conn.close()

            logger.debug(f"Stored {stored} link embeddings for cache_id={cache_id}")
            return stored

        except Exception as e:
            logger.error(f"Failed to store link embeddings: {e}")
            return 0

    def search_chunks(
        self,
        cache_id: int,
        query: str,
        top_k: int = None,
    ) -> List[Tuple[str, float]]:
        """Search for most relevant chunks given a query.

        Args:
            cache_id: The research_cache entry ID.
            query: The search query.
            top_k: Number of results to return.

        Returns:
            List of (chunk_text, similarity_score) tuples, sorted by relevance.
        """
        top_k = top_k or RESEARCH_MAX_CHUNKS_PER_RETRIEVAL

        if not query:
            return []

        try:
            # Get query embedding
            query_embedding = self.embedding_client.embed_single(query)

            conn = self._get_conn()
            c = conn.cursor()

            # Fetch all chunks for this cache entry
            c.execute(
                """
                SELECT chunk_text, embedding FROM content_chunks
                WHERE cache_id = ? AND embedding IS NOT NULL
            """,
                (cache_id,),
            )

            rows = c.fetchall()
            conn.close()

            if not rows:
                return []

            # Compute similarities
            results = []
            for chunk_text, embedding_bytes in rows:
                embedding = EmbeddingClient.deserialize_embedding(embedding_bytes)
                similarity = cosine_similarity(query_embedding, embedding)
                results.append((chunk_text, similarity))

            # Sort by similarity descending
            results.sort(key=lambda x: x[1], reverse=True)

            return results[:top_k]

        except Exception as e:
            logger.error(f"Chunk search failed: {e}")
            return []

    def rank_links_by_relevance(
        self,
        cache_id: int,
        query: str,
        top_k: int = 20,
    ) -> List[Tuple[Dict[str, str], float]]:
        """Rank links by relevance to query.

        Args:
            cache_id: The research_cache entry ID.
            query: The search query.
            top_k: Number of results to return.

        Returns:
            List of (link_dict, similarity_score) tuples, sorted by relevance.
        """
        if not query:
            return []

        try:
            # Get query embedding
            query_embedding = self.embedding_client.embed_single(query)

            conn = self._get_conn()
            c = conn.cursor()

            # Fetch all link embeddings
            c.execute(
                """
                SELECT link_text, link_url, embedding FROM link_embeddings
                WHERE cache_id = ? AND embedding IS NOT NULL
            """,
                (cache_id,),
            )

            rows = c.fetchall()
            conn.close()

            if not rows:
                return []

            results = []
            for link_text, link_url, embedding_bytes in rows:
                embedding = EmbeddingClient.deserialize_embedding(embedding_bytes)
                similarity = cosine_similarity(query_embedding, embedding)
                results.append(
                    ({"text": link_text, "href": link_url}, similarity)
                )

            results.sort(key=lambda x: x[1], reverse=True)

            return results[:top_k]

        except Exception as e:
            logger.error(f"Link ranking failed: {e}")
            return []

    def has_chunk_embeddings(self, cache_id: int) -> bool:
        """Check if chunk embeddings exist for a cache entry."""
        conn = self._get_conn()
        c = conn.cursor()
        c.execute(
            """
            SELECT COUNT(*) FROM content_chunks
            WHERE cache_id = ? AND embedding IS NOT NULL
        """,
            (cache_id,),
        )
        count = c.fetchone()[0]
        conn.close()
        return count > 0

    def has_chunk_embeddings_for_model(self, cache_id: int, model: str) -> bool:
        """Check if chunk embeddings exist for a specific embedding model."""
        if not model:
            return self.has_chunk_embeddings(cache_id)
        conn = self._get_conn()
        c = conn.cursor()
        c.execute(
            """
            SELECT COUNT(*) FROM content_chunks
            WHERE cache_id = ? AND embedding IS NOT NULL AND embedding_model = ?
        """,
            (cache_id, model),
        )
        count = c.fetchone()[0]
        conn.close()
        return count > 0

    def has_link_embeddings(self, cache_id: int) -> bool:
        """Check if link embeddings exist for a cache entry."""
        conn = self._get_conn()
        c = conn.cursor()
        c.execute(
            """
            SELECT COUNT(*) FROM link_embeddings
            WHERE cache_id = ? AND embedding IS NOT NULL
        """,
            (cache_id,),
        )
        count = c.fetchone()[0]
        conn.close()
        return count > 0

    def has_link_embeddings_for_model(self, cache_id: int, model: str) -> bool:
        """Check if link embeddings exist for a specific embedding model."""
        if not model:
            return self.has_link_embeddings(cache_id)

        has_embedding_model_column = self._table_has_column(
            "link_embeddings", "embedding_model"
        )
        if not has_embedding_model_column:
            return self.has_link_embeddings(cache_id)

        conn = self._get_conn()
        c = conn.cursor()
        c.execute(
            """
            SELECT COUNT(*) FROM link_embeddings
            WHERE cache_id = ? AND embedding IS NOT NULL AND embedding_model = ?
        """,
            (cache_id, model),
        )
        count = c.fetchone()[0]
        conn.close()
        return count > 0

    def search_chunks_hybrid(
        self,
        cache_id: int,
        query: str,
        top_k: int = None,
        dense_weight: float = DEFAULT_DENSE_WEIGHT,
        min_score: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """Search chunks by combining dense semantic and lexical relevance."""
        top_k = top_k or RESEARCH_MAX_CHUNKS_PER_RETRIEVAL
        if not query or not query.strip():
            return []

        try:
            query_embedding = self.embedding_client.embed_single(query)
            query_tokens = _tokenize_text(query)

            conn = self._get_conn()
            c = conn.cursor()
            c.execute(
                """
                SELECT chunk_index, chunk_text, embedding
                FROM content_chunks
                WHERE cache_id = ? AND embedding IS NOT NULL
            """,
                (cache_id,),
            )
            rows = c.fetchall()
            conn.close()

            if not rows:
                return []

            dense_weight = max(0.0, min(1.0, dense_weight))
            lexical_weight = 1.0 - dense_weight
            bm25_limit = max(
                top_k * HYBRID_LEXICAL_CANDIDATE_MULTIPLIER,
                top_k,
            )
            bm25_scores_by_chunk = self._get_bm25_scores(
                cache_id=cache_id,
                query=query,
                limit=bm25_limit,
            )
            use_bm25_scores = len(bm25_scores_by_chunk) > 0

            ranked: List[Dict[str, Any]] = []
            for chunk_index, chunk_text, embedding_bytes in rows:
                embedding = EmbeddingClient.deserialize_embedding(embedding_bytes)
                dense_score = max(0.0, cosine_similarity(query_embedding, embedding))
                if use_bm25_scores:
                    lexical_score = bm25_scores_by_chunk.get(chunk_index, 0.0)
                else:
                    lexical_score = _lexical_overlap_score(query_tokens, chunk_text)
                score = (dense_weight * dense_score) + (lexical_weight * lexical_score)
                if score < min_score:
                    continue
                ranked.append(
                    {
                        "chunk_index": chunk_index,
                        "text": chunk_text,
                        "score": score,
                        "dense_score": dense_score,
                        "lexical_score": lexical_score,
                    }
                )

            ranked.sort(key=lambda item: item["score"], reverse=True)
            return ranked[:top_k]
        except Exception as e:
            logger.error(f"Hybrid chunk search failed: {e}")
            return []

    # -------------------- Research Findings Methods --------------------

    def store_finding_embedding(self, finding_id: int, finding_text: str) -> bool:
        """Generate and store embedding for a research finding.

        Args:
            finding_id: The finding ID in research_findings table.
            finding_text: The text of the finding to embed.

        Returns:
            True if embedding was stored successfully.
        """
        if not finding_text or not finding_text.strip():
            return False

        try:
            embedding = self.embedding_client.embed_single(finding_text)
            embedding_bytes = EmbeddingClient.serialize_embedding(embedding)

            conn = self._get_conn()
            c = conn.cursor()

            c.execute(
                """
                UPDATE research_findings
                SET embedding = ?, embedding_model = ?
                WHERE id = ?
            """,
                (embedding_bytes, self.embedding_client.model, finding_id),
            )

            success = c.rowcount > 0
            conn.commit()
            conn.close()

            if success:
                logger.debug(f"Stored embedding for finding id={finding_id}")
            return success

        except Exception as e:
            logger.error(f"Failed to store finding embedding: {e}")
            return False

    def search_findings(
        self,
        query: str,
        top_k: int = 10,
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Search for relevant findings given a query.

        Args:
            query: The search query.
            top_k: Number of results to return.

        Returns:
            List of (finding_dict, similarity_score) tuples, sorted by relevance.
        """
        if not query or not query.strip():
            return []

        try:
            # Get query embedding
            query_embedding = self.embedding_client.embed_single(query)

            conn = self._get_conn()
            c = conn.cursor()

            # Fetch all findings with embeddings
            c.execute(
                """
                SELECT id, finding_text, source_url, source_title, tags,
                       embedding, created_at, session_id
                FROM research_findings
                WHERE embedding IS NOT NULL
            """
            )

            rows = c.fetchall()
            conn.close()

            if not rows:
                return []

            # Compute similarities
            results = []
            for row in rows:
                finding_id, finding_text, source_url, source_title, tags_json, embedding_bytes, created_at, session_id = row
                embedding = EmbeddingClient.deserialize_embedding(embedding_bytes)
                similarity = cosine_similarity(query_embedding, embedding)

                finding_dict = {
                    "id": finding_id,
                    "finding_text": finding_text,
                    "source_url": source_url,
                    "source_title": source_title,
                    "tags": json.loads(tags_json) if tags_json else [],
                    "created_at": created_at,
                    "session_id": session_id,
                }
                results.append((finding_dict, similarity))

            # Sort by similarity descending
            results.sort(key=lambda x: x[1], reverse=True)

            return results[:top_k]

        except Exception as e:
            logger.error(f"Finding search failed: {e}")
            return []

    def has_finding_embedding(self, finding_id: int) -> bool:
        """Check if a finding has an embedding."""
        conn = self._get_conn()
        c = conn.cursor()
        c.execute(
            """
            SELECT COUNT(*) FROM research_findings
            WHERE id = ? AND embedding IS NOT NULL
        """,
            (finding_id,),
        )
        count = c.fetchone()[0]
        conn.close()
        return count > 0


def get_vector_store() -> VectorStore:
    """Get the singleton vector store instance."""
    return VectorStore()
