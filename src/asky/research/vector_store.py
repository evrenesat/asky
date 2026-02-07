"""Vector similarity search for research mode."""

import json
import logging
import math
import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from asky.config import (
    DB_PATH,
    RESEARCH_MAX_CHUNKS_PER_RETRIEVAL,
    RESEARCH_CHROMA_PERSIST_DIRECTORY,
    RESEARCH_CHROMA_CHUNKS_COLLECTION,
    RESEARCH_CHROMA_LINKS_COLLECTION,
    RESEARCH_CHROMA_FINDINGS_COLLECTION,
)
from asky.research.embeddings import EmbeddingClient, get_embedding_client

logger = logging.getLogger(__name__)
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]{2,}")
DEFAULT_DENSE_WEIGHT = 0.75
CHUNK_FTS_TABLE_NAME = "content_chunks_fts"
HYBRID_LEXICAL_CANDIDATE_MULTIPLIER = 10
CHROMA_COLLECTION_SPACE = "cosine"
CHROMA_TO_SIMILARITY_BASE = 1.0


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
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


def _distance_to_similarity(distance: Any) -> float:
    """Convert Chroma distance to a bounded similarity score."""
    try:
        score = CHROMA_TO_SIMILARITY_BASE - float(distance)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, score))


def _first_query_result(items: Any) -> List[Any]:
    """Normalize Chroma query payload shape (nested list per query)."""
    if not isinstance(items, list):
        return []
    if items and isinstance(items[0], list):
        return items[0]
    return items


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
            logger.error("Failed to open Chroma collection '%s': %s", collection_name, exc)
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
        collection = self._get_chroma_collection(self.chroma_chunks_collection)
        if collection is None:
            return

        model_name = self.embedding_client.model
        ids = [self._chunk_chroma_id(cache_id, chunk_idx) for chunk_idx, _ in chunks]
        metadatas = [
            {
                "cache_id": cache_id,
                "chunk_index": chunk_idx,
                "embedding_model": model_name,
            }
            for chunk_idx, _ in chunks
        ]
        documents = [chunk_text for _, chunk_text in chunks]

        try:
            collection.delete(where={"cache_id": cache_id})
            collection.add(
                ids=ids,
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas,
            )
        except Exception as exc:
            logger.error("Failed to upsert chunk embeddings into ChromaDB: %s", exc)

    def _upsert_links_to_chroma(
        self,
        cache_id: int,
        links_with_text: List[Dict[str, str]],
        embedding_inputs: List[str],
        embeddings: List[List[float]],
    ) -> None:
        """Upsert link vectors into Chroma for semantic relevance filtering."""
        collection = self._get_chroma_collection(self.chroma_links_collection)
        if collection is None:
            return

        model_name = self.embedding_client.model
        ids = [
            self._link_chroma_id(cache_id, link.get("href", ""))
            for link in links_with_text
        ]
        metadatas = [
            {
                "cache_id": cache_id,
                "link_text": link.get("text", ""),
                "link_url": link.get("href", ""),
                "embedding_model": model_name,
            }
            for link in links_with_text
        ]

        try:
            collection.delete(where={"cache_id": cache_id})
            collection.add(
                ids=ids,
                documents=embedding_inputs,
                embeddings=embeddings,
                metadatas=metadatas,
            )
        except Exception as exc:
            logger.error("Failed to upsert link embeddings into ChromaDB: %s", exc)

    def _upsert_finding_to_chroma(
        self,
        finding_id: int,
        finding_text: str,
        embedding: List[float],
    ) -> None:
        """Upsert one finding vector into Chroma."""
        collection = self._get_chroma_collection(self.chroma_findings_collection)
        if collection is None:
            return

        try:
            collection.delete(ids=[self._finding_chroma_id(finding_id)])
            collection.add(
                ids=[self._finding_chroma_id(finding_id)],
                documents=[finding_text],
                embeddings=[embedding],
                metadatas=[
                    {
                        "finding_id": finding_id,
                        "embedding_model": self.embedding_client.model,
                    }
                ],
            )
        except Exception as exc:
            logger.error("Failed to upsert finding embedding into ChromaDB: %s", exc)

    def clear_cache_embeddings(
        self,
        cache_id: int,
        clear_chunks: bool = True,
        clear_links: bool = True,
    ) -> None:
        """Delete Chroma vectors related to one cache entry."""
        if cache_id <= 0:
            return

        if clear_chunks:
            chunk_collection = self._get_chroma_collection(self.chroma_chunks_collection)
            if chunk_collection is not None:
                try:
                    chunk_collection.delete(where={"cache_id": cache_id})
                except Exception as exc:
                    logger.warning("Failed to clear chunk vectors in ChromaDB: %s", exc)

        if clear_links:
            link_collection = self._get_chroma_collection(self.chroma_links_collection)
            if link_collection is not None:
                try:
                    link_collection.delete(where={"cache_id": cache_id})
                except Exception as exc:
                    logger.warning("Failed to clear link vectors in ChromaDB: %s", exc)

    def clear_cache_embeddings_bulk(
        self,
        cache_ids: List[int],
        clear_chunks: bool = True,
        clear_links: bool = True,
    ) -> None:
        """Delete Chroma vectors for multiple cache entries."""
        for cache_id in cache_ids:
            self.clear_cache_embeddings(
                cache_id=cache_id,
                clear_chunks=clear_chunks,
                clear_links=clear_links,
            )

    def store_chunk_embeddings(
        self,
        cache_id: int,
        chunks: List[Tuple[int, str]],
    ) -> int:
        """Generate and store embeddings for content chunks."""
        if not chunks:
            return 0

        try:
            texts = [chunk[1] for chunk in chunks]
            embeddings = self.embedding_client.embed(texts)

            if len(embeddings) != len(chunks):
                logger.warning(
                    "Embedding count mismatch: %s vs %s",
                    len(embeddings),
                    len(chunks),
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

            self._upsert_chunks_to_chroma(cache_id, chunks, embeddings)

            logger.debug("Stored %s chunk embeddings for cache_id=%s", len(chunks), cache_id)
            return len(chunks)
        except Exception as exc:
            logger.error("Failed to store chunk embeddings: %s", exc)
            return 0

    def store_link_embeddings(
        self,
        cache_id: int,
        links: List[Dict[str, str]],
    ) -> int:
        """Generate and store embeddings for links."""
        if not links:
            return 0

        try:
            links_with_text: List[Dict[str, str]] = []
            embedding_inputs: List[str] = []
            for link in links:
                link_text = link.get("text", "")
                link_url = link.get("href", "")
                if not link_url:
                    continue
                combined = f"{link_text} - {link_url}".strip()
                if combined == "-":
                    continue
                links_with_text.append(link)
                embedding_inputs.append(combined)

            if not embedding_inputs:
                return 0

            embeddings = self.embedding_client.embed(embedding_inputs)

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

            self._upsert_links_to_chroma(
                cache_id=cache_id,
                links_with_text=links_with_text,
                embedding_inputs=embedding_inputs,
                embeddings=embeddings,
            )

            logger.debug("Stored %s link embeddings for cache_id=%s", stored, cache_id)
            return stored
        except Exception as exc:
            logger.error("Failed to store link embeddings: %s", exc)
            return 0

    def _search_chunks_with_chroma(
        self,
        cache_id: int,
        query_embedding: List[float],
        top_k: int,
    ) -> List[Tuple[str, float]]:
        """Search chunk similarities in ChromaDB."""
        collection = self._get_chroma_collection(self.chroma_chunks_collection)
        if collection is None:
            return []

        try:
            response = collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where={
                    "cache_id": cache_id,
                    "embedding_model": self.embedding_client.model,
                },
                include=["documents", "distances"],
            )
        except Exception as exc:
            logger.warning("Chroma chunk query failed; falling back to SQLite: %s", exc)
            return []

        docs = _first_query_result(response.get("documents", []))
        distances = _first_query_result(response.get("distances", []))

        results: List[Tuple[str, float]] = []
        for doc, distance in zip(docs, distances):
            results.append((str(doc or ""), _distance_to_similarity(distance)))

        results.sort(key=lambda item: item[1], reverse=True)
        return results[:top_k]

    def _search_chunks_with_sqlite(
        self,
        cache_id: int,
        query_embedding: List[float],
        top_k: int,
    ) -> List[Tuple[str, float]]:
        """Search chunk similarities in SQLite by scanning stored vectors."""
        conn = self._get_conn()
        c = conn.cursor()
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

        results = []
        for chunk_text, embedding_bytes in rows:
            embedding = EmbeddingClient.deserialize_embedding(embedding_bytes)
            similarity = cosine_similarity(query_embedding, embedding)
            results.append((chunk_text, similarity))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def search_chunks(
        self,
        cache_id: int,
        query: str,
        top_k: int = None,
    ) -> List[Tuple[str, float]]:
        """Search for most relevant chunks given a query."""
        top_k = top_k or RESEARCH_MAX_CHUNKS_PER_RETRIEVAL
        if not query:
            return []

        try:
            query_embedding = self.embedding_client.embed_single(query)

            chroma_results = self._search_chunks_with_chroma(
                cache_id=cache_id,
                query_embedding=query_embedding,
                top_k=top_k,
            )
            if chroma_results:
                return chroma_results

            return self._search_chunks_with_sqlite(
                cache_id=cache_id,
                query_embedding=query_embedding,
                top_k=top_k,
            )
        except Exception as exc:
            logger.error("Chunk search failed: %s", exc)
            return []

    def _rank_links_with_chroma(
        self,
        cache_id: int,
        query_embedding: List[float],
        top_k: int,
    ) -> List[Tuple[Dict[str, str], float]]:
        """Rank links with Chroma vector search."""
        collection = self._get_chroma_collection(self.chroma_links_collection)
        if collection is None:
            return []

        try:
            response = collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where={
                    "cache_id": cache_id,
                    "embedding_model": self.embedding_client.model,
                },
                include=["metadatas", "distances"],
            )
        except Exception as exc:
            logger.warning("Chroma link query failed; falling back to SQLite: %s", exc)
            return []

        metadatas = _first_query_result(response.get("metadatas", []))
        distances = _first_query_result(response.get("distances", []))

        ranked: List[Tuple[Dict[str, str], float]] = []
        for metadata, distance in zip(metadatas, distances):
            metadata = metadata or {}
            ranked.append(
                (
                    {
                        "text": str(metadata.get("link_text", "")),
                        "href": str(metadata.get("link_url", "")),
                    },
                    _distance_to_similarity(distance),
                )
            )

        ranked.sort(key=lambda item: item[1], reverse=True)
        return ranked[:top_k]

    def _rank_links_with_sqlite(
        self,
        cache_id: int,
        query_embedding: List[float],
        top_k: int,
    ) -> List[Tuple[Dict[str, str], float]]:
        """Rank links by scanning SQLite link vectors."""
        conn = self._get_conn()
        c = conn.cursor()
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
            results.append(({"text": link_text, "href": link_url}, similarity))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def rank_links_by_relevance(
        self,
        cache_id: int,
        query: str,
        top_k: int = 20,
    ) -> List[Tuple[Dict[str, str], float]]:
        """Rank links by relevance to query."""
        if not query:
            return []

        try:
            query_embedding = self.embedding_client.embed_single(query)

            chroma_ranked = self._rank_links_with_chroma(
                cache_id=cache_id,
                query_embedding=query_embedding,
                top_k=top_k,
            )
            if chroma_ranked:
                return chroma_ranked

            return self._rank_links_with_sqlite(
                cache_id=cache_id,
                query_embedding=query_embedding,
                top_k=top_k,
            )
        except Exception as exc:
            logger.error("Link ranking failed: %s", exc)
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

    def _dense_scores_for_chunks_with_chroma(
        self,
        cache_id: int,
        query_embedding: List[float],
        top_k: int,
    ) -> Dict[int, float]:
        """Return dense scores by chunk index from Chroma candidates."""
        collection = self._get_chroma_collection(self.chroma_chunks_collection)
        if collection is None:
            return {}

        try:
            response = collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where={
                    "cache_id": cache_id,
                    "embedding_model": self.embedding_client.model,
                },
                include=["metadatas", "distances"],
            )
        except Exception as exc:
            logger.warning("Chroma hybrid query failed; using SQLite dense scores: %s", exc)
            return {}

        metadatas = _first_query_result(response.get("metadatas", []))
        distances = _first_query_result(response.get("distances", []))

        scores: Dict[int, float] = {}
        for metadata, distance in zip(metadatas, distances):
            if not metadata:
                continue
            chunk_index_raw = metadata.get("chunk_index")
            try:
                chunk_index = int(chunk_index_raw)
            except (TypeError, ValueError):
                continue
            scores[chunk_index] = _distance_to_similarity(distance)
        return scores

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

            dense_candidate_limit = max(
                top_k * HYBRID_LEXICAL_CANDIDATE_MULTIPLIER,
                top_k,
            )
            dense_scores_by_chunk = self._dense_scores_for_chunks_with_chroma(
                cache_id=cache_id,
                query_embedding=query_embedding,
                top_k=dense_candidate_limit,
            )
            use_chroma_dense_scores = len(dense_scores_by_chunk) > 0

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
                if use_chroma_dense_scores:
                    dense_score = dense_scores_by_chunk.get(chunk_index, 0.0)
                else:
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
        except Exception as exc:
            logger.error("Hybrid chunk search failed: %s", exc)
            return []

    # -------------------- Research Findings Methods --------------------

    def store_finding_embedding(self, finding_id: int, finding_text: str) -> bool:
        """Generate and store embedding for a research finding."""
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
                self._upsert_finding_to_chroma(
                    finding_id=finding_id,
                    finding_text=finding_text,
                    embedding=embedding,
                )
                logger.debug("Stored embedding for finding id=%s", finding_id)
            return success
        except Exception as exc:
            logger.error("Failed to store finding embedding: %s", exc)
            return False

    def _search_findings_with_chroma(
        self,
        query_embedding: List[float],
        top_k: int,
    ) -> List[Tuple[int, float]]:
        """Search finding IDs via Chroma query."""
        collection = self._get_chroma_collection(self.chroma_findings_collection)
        if collection is None:
            return []

        try:
            response = collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where={"embedding_model": self.embedding_client.model},
                include=["metadatas", "distances"],
            )
        except Exception as exc:
            logger.warning("Chroma finding query failed; falling back to SQLite: %s", exc)
            return []

        metadatas = _first_query_result(response.get("metadatas", []))
        distances = _first_query_result(response.get("distances", []))

        ranked_ids: List[Tuple[int, float]] = []
        for metadata, distance in zip(metadatas, distances):
            if not metadata:
                continue
            raw_id = metadata.get("finding_id")
            try:
                finding_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            ranked_ids.append((finding_id, _distance_to_similarity(distance)))

        ranked_ids.sort(key=lambda item: item[1], reverse=True)
        return ranked_ids[:top_k]

    def _fetch_findings_by_ids(
        self,
        finding_ids: List[int],
    ) -> Dict[int, Dict[str, Any]]:
        """Fetch finding rows from SQLite and map by finding ID."""
        if not finding_ids:
            return {}

        conn = self._get_conn()
        c = conn.cursor()
        placeholders = ",".join("?" * len(finding_ids))
        c.execute(
            f"""
            SELECT id, finding_text, source_url, source_title, tags, created_at, session_id
            FROM research_findings
            WHERE id IN ({placeholders})
            """,
            finding_ids,
        )
        rows = c.fetchall()
        conn.close()

        mapped: Dict[int, Dict[str, Any]] = {}
        for row in rows:
            (
                finding_id,
                finding_text,
                source_url,
                source_title,
                tags_json,
                created_at,
                session_id,
            ) = row
            mapped[finding_id] = {
                "id": finding_id,
                "finding_text": finding_text,
                "source_url": source_url,
                "source_title": source_title,
                "tags": json.loads(tags_json) if tags_json else [],
                "created_at": created_at,
                "session_id": session_id,
            }
        return mapped

    def _search_findings_with_sqlite(
        self,
        query_embedding: List[float],
        top_k: int,
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Search findings by scanning SQLite embeddings."""
        conn = self._get_conn()
        c = conn.cursor()

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

        results = []
        for row in rows:
            (
                finding_id,
                finding_text,
                source_url,
                source_title,
                tags_json,
                embedding_bytes,
                created_at,
                session_id,
            ) = row
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

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def search_findings(
        self,
        query: str,
        top_k: int = 10,
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Search for relevant findings given a query."""
        if not query or not query.strip():
            return []

        try:
            query_embedding = self.embedding_client.embed_single(query)

            chroma_ranked_ids = self._search_findings_with_chroma(
                query_embedding=query_embedding,
                top_k=top_k,
            )
            if chroma_ranked_ids:
                finding_ids = [finding_id for finding_id, _ in chroma_ranked_ids]
                findings_by_id = self._fetch_findings_by_ids(finding_ids)
                ranked_findings: List[Tuple[Dict[str, Any], float]] = []
                for finding_id, similarity in chroma_ranked_ids:
                    finding = findings_by_id.get(finding_id)
                    if finding is None:
                        continue
                    ranked_findings.append((finding, similarity))
                if ranked_findings:
                    return ranked_findings[:top_k]

            return self._search_findings_with_sqlite(
                query_embedding=query_embedding,
                top_k=top_k,
            )
        except Exception as exc:
            logger.error("Finding search failed: %s", exc)
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
