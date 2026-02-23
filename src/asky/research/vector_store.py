"""Vector similarity search for research mode."""

import logging
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Tuple

from asky.config import (
    DB_PATH,
    RESEARCH_CHROMA_CHUNKS_COLLECTION,
    RESEARCH_CHROMA_FINDINGS_COLLECTION,
    RESEARCH_CHROMA_LINKS_COLLECTION,
    RESEARCH_CHROMA_PERSIST_DIRECTORY,
)
from asky.research.embeddings import EmbeddingClient, get_embedding_client
from asky.research.vector_store_common import (
    CHROMA_COLLECTION_SPACE,
    CHUNK_FTS_TABLE_NAME,
    DEFAULT_DENSE_WEIGHT,
    cosine_similarity,
    distance_to_similarity,
    first_query_result,
    lexical_overlap_score,
    tokenize_text,
)
from asky.research import vector_store_chunk_link_ops as chunk_link_ops
from asky.research import vector_store_finding_ops as finding_ops

logger = logging.getLogger(__name__)


def _tokenize_text(text: str) -> set[str]:
    """Backward-compatible alias for lexical tokenization helper."""
    return tokenize_text(text)


def _lexical_overlap_score(query_tokens: set[str], text: str) -> float:
    """Backward-compatible alias for lexical overlap helper."""
    return lexical_overlap_score(query_tokens, text)


def _distance_to_similarity(distance: Any) -> float:
    """Backward-compatible alias for Chroma distance normalization."""
    return distance_to_similarity(distance)


def _first_query_result(items: Any) -> List[Any]:
    """Backward-compatible alias for Chroma response normalization."""
    return first_query_result(items)


class VectorStore:
    """Vector store using ChromaDB for dense retrieval with SQLite fallbacks."""

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
        chroma_persist_directory: str = None,
    ):
        if self._initialized:
            return

        self.db_path = db_path or str(DB_PATH)
        self._embedding_client = embedding_client
        self._fts_available: Optional[bool] = None

        self.chroma_persist_directory = str(
            chroma_persist_directory or RESEARCH_CHROMA_PERSIST_DIRECTORY
        )
        self.chroma_chunks_collection = RESEARCH_CHROMA_CHUNKS_COLLECTION
        self.chroma_links_collection = RESEARCH_CHROMA_LINKS_COLLECTION
        self.chroma_findings_collection = RESEARCH_CHROMA_FINDINGS_COLLECTION

        self._chroma_client: Any = None
        self._chroma_ready = False
        self._chroma_disabled = False
        self._db_lock = threading.Lock()
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

    def _get_chroma_client(self) -> Any:
        """Return a Chroma client when available, else None."""
        if self._chroma_ready:
            return self._chroma_client
        if self._chroma_disabled:
            return None

        try:
            import chromadb

            self._chroma_client = chromadb.PersistentClient(
                path=self.chroma_persist_directory
            )
            self._chroma_ready = True
            return self._chroma_client
        except Exception as exc:
            self._chroma_disabled = True
            logger.warning(
                "ChromaDB is unavailable; falling back to SQLite-only vector search: %s",
                exc,
            )
            return None

    def _get_chroma_collection(self, collection_name: str) -> Any:
        """Get or create a Chroma collection when client is available."""
        client = self._get_chroma_client()
        if client is None:
            return None

        try:
            return client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": CHROMA_COLLECTION_SPACE},
            )
        except Exception as exc:
            logger.error(
                "Failed to open Chroma collection '%s': %s", collection_name, exc
            )
            return None

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
            with self._db_lock:
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
            logger.warning("BM25 lexical scoring unavailable, falling back: %s", exc)
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

    def _chunk_chroma_id(self, cache_id: int, chunk_index: int) -> str:
        """Build deterministic Chroma ID for a content chunk."""
        return f"chunk:{cache_id}:{chunk_index}"

    def _link_chroma_id(self, cache_id: int, link_url: str) -> str:
        """Build deterministic Chroma ID for a cached link."""
        return f"link:{cache_id}:{link_url}"

    def _finding_chroma_id(self, finding_id: int) -> str:
        """Build deterministic Chroma ID for a research finding."""
        return f"finding:{finding_id}"

    def _upsert_chunks_to_chroma(
        self,
        cache_id: int,
        chunks: List[Tuple[int, str]],
        embeddings: List[List[float]],
    ) -> None:
        """Upsert chunk vectors into Chroma for semantic retrieval."""
        chunk_link_ops.upsert_chunks_to_chroma(self, cache_id, chunks, embeddings)

    def _upsert_links_to_chroma(
        self,
        cache_id: int,
        links_with_text: List[Dict[str, str]],
        embedding_inputs: List[str],
        embeddings: List[List[float]],
    ) -> None:
        """Upsert link vectors into Chroma for semantic relevance filtering."""
        chunk_link_ops.upsert_links_to_chroma(
            self,
            cache_id,
            links_with_text,
            embedding_inputs,
            embeddings,
        )

    def _upsert_finding_to_chroma(
        self,
        finding_id: int,
        finding_text: str,
        embedding: List[float],
    ) -> None:
        """Upsert one finding vector into Chroma."""
        finding_ops.upsert_finding_to_chroma(self, finding_id, finding_text, embedding)

    def clear_cache_embeddings(
        self,
        cache_id: int,
        clear_chunks: bool = True,
        clear_links: bool = True,
    ) -> None:
        """Delete Chroma vectors related to one cache entry."""
        chunk_link_ops.clear_cache_embeddings(
            self,
            cache_id,
            clear_chunks=clear_chunks,
            clear_links=clear_links,
        )

    def clear_cache_embeddings_bulk(
        self,
        cache_ids: List[int],
        clear_chunks: bool = True,
        clear_links: bool = True,
    ) -> None:
        """Delete Chroma vectors for multiple cache entries."""
        chunk_link_ops.clear_cache_embeddings_bulk(
            self,
            cache_ids,
            clear_chunks=clear_chunks,
            clear_links=clear_links,
        )

    def store_chunk_embeddings(
        self,
        cache_id: int,
        chunks: List[Tuple[int, str]],
    ) -> int:
        """Generate and store embeddings for content chunks."""
        return chunk_link_ops.store_chunk_embeddings(self, cache_id, chunks)

    def store_link_embeddings(
        self,
        cache_id: int,
        links: List[Dict[str, str]],
    ) -> int:
        """Generate and store embeddings for links."""
        return chunk_link_ops.store_link_embeddings(self, cache_id, links)

    def _search_chunks_with_chroma(
        self,
        cache_id: int,
        query_embedding: List[float],
        top_k: int,
    ) -> List[Tuple[str, float]]:
        """Search chunk similarities in ChromaDB."""
        return chunk_link_ops.search_chunks_with_chroma(
            self, cache_id, query_embedding, top_k
        )

    def _search_chunks_with_sqlite(
        self,
        cache_id: int,
        query_embedding: List[float],
        top_k: int,
    ) -> List[Tuple[str, float]]:
        """Search chunk similarities in SQLite by scanning stored vectors."""
        return chunk_link_ops.search_chunks_with_sqlite(
            self, cache_id, query_embedding, top_k
        )

    def search_chunks(
        self,
        cache_id: int,
        query: str,
        top_k: int = None,
    ) -> List[Tuple[str, float]]:
        """Search for most relevant chunks given a query."""
        return chunk_link_ops.search_chunks(self, cache_id, query, top_k)

    def _rank_links_with_chroma(
        self,
        cache_id: int,
        query_embedding: List[float],
        top_k: int,
    ) -> List[Tuple[Dict[str, str], float]]:
        """Rank links with Chroma vector search."""
        return chunk_link_ops.rank_links_with_chroma(
            self, cache_id, query_embedding, top_k
        )

    def _rank_links_with_sqlite(
        self,
        cache_id: int,
        query_embedding: List[float],
        top_k: int,
    ) -> List[Tuple[Dict[str, str], float]]:
        """Rank links by scanning SQLite link vectors."""
        return chunk_link_ops.rank_links_with_sqlite(
            self, cache_id, query_embedding, top_k
        )

    def rank_links_by_relevance(
        self,
        cache_id: int,
        query: str,
        top_k: int = 20,
    ) -> List[Tuple[Dict[str, str], float]]:
        """Rank links by relevance to query."""
        return chunk_link_ops.rank_links_by_relevance(self, cache_id, query, top_k)

    def has_chunk_embeddings(self, cache_id: int) -> bool:
        """Check if chunk embeddings exist for a cache entry."""
        return chunk_link_ops.has_chunk_embeddings(self, cache_id)

    def has_chunk_embeddings_for_model(self, cache_id: int, model: str) -> bool:
        """Check if chunk embeddings exist for a specific embedding model."""
        return chunk_link_ops.has_chunk_embeddings_for_model(self, cache_id, model)

    def has_link_embeddings(self, cache_id: int) -> bool:
        """Check if link embeddings exist for a cache entry."""
        return chunk_link_ops.has_link_embeddings(self, cache_id)

    def has_link_embeddings_for_model(self, cache_id: int, model: str) -> bool:
        """Check if link embeddings exist for a specific embedding model."""
        return chunk_link_ops.has_link_embeddings_for_model(self, cache_id, model)

    def _dense_scores_for_chunks_with_chroma(
        self,
        cache_id: int,
        query_embedding: List[float],
        top_k: int,
    ) -> Dict[int, float]:
        """Return dense scores by chunk index from Chroma candidates."""
        return chunk_link_ops.dense_scores_for_chunks_with_chroma(
            self,
            cache_id,
            query_embedding,
            top_k,
        )

    def search_chunks_hybrid(
        self,
        cache_id: int,
        query: str,
        top_k: int = None,
        dense_weight: float = DEFAULT_DENSE_WEIGHT,
        min_score: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """Search chunks by combining dense semantic and lexical relevance."""
        return chunk_link_ops.search_chunks_hybrid(
            self,
            cache_id,
            query,
            top_k=top_k,
            dense_weight=dense_weight,
            min_score=min_score,
        )

    def store_finding_embedding(self, finding_id: int, finding_text: str) -> bool:
        """Generate and store embedding for a research finding."""
        return finding_ops.store_finding_embedding(self, finding_id, finding_text)

    def _search_findings_with_chroma(
        self,
        query_embedding: List[float],
        top_k: int,
    ) -> List[Tuple[int, float]]:
        """Search finding IDs via Chroma query."""
        return finding_ops.search_findings_with_chroma(self, query_embedding, top_k)

    def _fetch_findings_by_ids(
        self,
        finding_ids: List[int],
        session_id: Optional[str] = None,
    ) -> Dict[int, Dict[str, Any]]:
        """Fetch finding rows from SQLite and map by finding ID."""
        return finding_ops.fetch_findings_by_ids(
            self,
            finding_ids,
            session_id=session_id,
        )

    def _search_findings_with_sqlite(
        self,
        query_embedding: List[float],
        top_k: int,
        session_id: Optional[str] = None,
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Search findings by scanning SQLite embeddings."""
        return finding_ops.search_findings_with_sqlite(
            self,
            query_embedding,
            top_k,
            session_id=session_id,
        )

    def _has_finding_embeddings_for_model(
        self,
        model: str,
        session_id: Optional[str] = None,
    ) -> bool:
        """Check whether SQLite has any stored finding embeddings for the model."""
        return finding_ops.has_finding_embeddings_for_model(
            self,
            model,
            session_id=session_id,
        )

    def search_findings(
        self,
        query: str,
        top_k: int = 10,
        session_id: Optional[str] = None,
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Search for relevant findings given a query."""
        return finding_ops.search_findings(
            self,
            query,
            top_k,
            session_id=session_id,
        )

    def has_finding_embedding(self, finding_id: int) -> bool:
        """Check if a finding has an embedding."""
        return finding_ops.has_finding_embedding(self, finding_id)

    def delete_findings_by_session(self, session_id: str) -> int:
        """Delete findings and their embeddings for a session."""
        return finding_ops.delete_findings_by_session(self, session_id)


def get_vector_store() -> VectorStore:
    """Get the singleton vector store instance."""
    return VectorStore()
