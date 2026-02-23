"""Chunk/link storage and retrieval operations for VectorStore."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Tuple

from asky.config import RESEARCH_MAX_CHUNKS_PER_RETRIEVAL
from asky.research.embeddings import EmbeddingClient
from asky.research.vector_store_common import (
    DEFAULT_DENSE_WEIGHT,
    HYBRID_LEXICAL_CANDIDATE_MULTIPLIER,
    cosine_similarity,
    distance_to_similarity,
    first_query_result,
    lexical_overlap_score,
    tokenize_text,
)

if TYPE_CHECKING:
    from asky.research.vector_store import VectorStore

logger = logging.getLogger(__name__)


def _build_chroma_cache_model_filter(cache_id: int, embedding_model: str) -> Dict[str, Any]:
    """Build Chroma metadata filter compatible with strict single-operator parsers."""
    if embedding_model:
        return {
            "$and": [
                {"cache_id": cache_id},
                {"embedding_model": embedding_model},
            ]
        }
    return {"cache_id": cache_id}


def upsert_chunks_to_chroma(
    store: "VectorStore",
    cache_id: int,
    chunks: List[Tuple[int, str]],
    embeddings: List[List[float]],
) -> None:
    collection = store._get_chroma_collection(store.chroma_chunks_collection)
    if collection is None:
        return

    model_name = store.embedding_client.model
    ids = [store._chunk_chroma_id(cache_id, chunk_idx) for chunk_idx, _ in chunks]
    metadatas = [
        {"cache_id": cache_id, "chunk_index": chunk_idx, "embedding_model": model_name}
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


def upsert_links_to_chroma(
    store: "VectorStore",
    cache_id: int,
    links_with_text: List[Dict[str, str]],
    embedding_inputs: List[str],
    embeddings: List[List[float]],
) -> None:
    collection = store._get_chroma_collection(store.chroma_links_collection)
    if collection is None:
        return

    model_name = store.embedding_client.model
    ids = [
        store._link_chroma_id(cache_id, link.get("href", ""))
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


def clear_cache_embeddings(
    store: "VectorStore",
    cache_id: int,
    clear_chunks: bool = True,
    clear_links: bool = True,
) -> None:
    if cache_id <= 0:
        return

    if clear_chunks:
        chunk_collection = store._get_chroma_collection(store.chroma_chunks_collection)
        if chunk_collection is not None:
            try:
                chunk_collection.delete(where={"cache_id": cache_id})
            except Exception as exc:
                logger.warning("Failed to clear chunk vectors in ChromaDB: %s", exc)

    if clear_links:
        link_collection = store._get_chroma_collection(store.chroma_links_collection)
        if link_collection is not None:
            try:
                link_collection.delete(where={"cache_id": cache_id})
            except Exception as exc:
                logger.warning("Failed to clear link vectors in ChromaDB: %s", exc)


def clear_cache_embeddings_bulk(
    store: "VectorStore",
    cache_ids: List[int],
    clear_chunks: bool = True,
    clear_links: bool = True,
) -> None:
    for cache_id in cache_ids:
        clear_cache_embeddings(
            store,
            cache_id=cache_id,
            clear_chunks=clear_chunks,
            clear_links=clear_links,
        )


def store_chunk_embeddings(
    store: "VectorStore",
    cache_id: int,
    chunks: List[Tuple[int, str]],
) -> int:
    if not chunks:
        return 0

    try:
        texts = [chunk[1] for chunk in chunks]
        embeddings = store.embedding_client.embed(texts)
        if len(embeddings) != len(chunks):
            logger.warning(
                "Embedding count mismatch: %s vs %s",
                len(embeddings),
                len(chunks),
            )
            return 0

        conn = store._get_conn()
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
                    store.embedding_client.model,
                    now,
                ),
            )

        conn.commit()
        conn.close()

        upsert_chunks_to_chroma(store, cache_id, chunks, embeddings)
        logger.debug("Stored %s chunk embeddings for cache_id=%s", len(chunks), cache_id)
        return len(chunks)
    except Exception as exc:
        logger.error("Failed to store chunk embeddings: %s", exc)
        return 0


def store_link_embeddings(
    store: "VectorStore",
    cache_id: int,
    links: List[Dict[str, str]],
) -> int:
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

        embeddings = store.embedding_client.embed(embedding_inputs)

        conn = store._get_conn()
        c = conn.cursor()
        now = datetime.now().isoformat()
        c.execute("DELETE FROM link_embeddings WHERE cache_id = ?", (cache_id,))
        has_embedding_model_column = store._table_has_column(
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
                        store.embedding_client.model,
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

        upsert_links_to_chroma(
            store=store,
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


def search_chunks_with_chroma(
    store: "VectorStore",
    cache_id: int,
    query_embedding: List[float],
    top_k: int,
) -> List[Tuple[str, float]]:
    collection = store._get_chroma_collection(store.chroma_chunks_collection)
    if collection is None:
        return []

    try:
        response = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=_build_chroma_cache_model_filter(
                cache_id=cache_id,
                embedding_model=store.embedding_client.model,
            ),
            include=["documents", "distances", "ids"],
        )
    except Exception as exc:
        logger.warning("Chroma chunk query failed; falling back to SQLite: %s", exc)
        return []

    ids = first_query_result(response.get("ids", []))
    docs = first_query_result(response.get("documents", []))
    distances = first_query_result(response.get("distances", []))

    if not ids:
        try:
            all_count = collection.count()
            if all_count > 0:
                logger.warning(
                    "No embeddings found for model '%s'. "
                    "Data may have been indexed with a different model. "
                    "Re-index or change RESEARCH_EMBEDDING_MODEL.",
                    store.embedding_client.model,
                )
        except Exception:
            pass
        return []

    results: List[Tuple[str, float]] = []
    for doc, distance in zip(docs, distances):
        results.append((str(doc or ""), distance_to_similarity(distance)))
    results.sort(key=lambda item: item[1], reverse=True)
    return results[:top_k]


def search_chunks_with_sqlite(
    store: "VectorStore",
    cache_id: int,
    query_embedding: List[float],
    top_k: int,
) -> List[Tuple[str, float]]:
    conn = store._get_conn()
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
    store: "VectorStore",
    cache_id: int,
    query: str,
    top_k: int | None = None,
) -> List[Tuple[str, float]]:
    top_k = top_k or RESEARCH_MAX_CHUNKS_PER_RETRIEVAL
    if not query:
        return []

    try:
        query_embedding = store.embedding_client.embed_single(query)
        chroma_results = store._search_chunks_with_chroma(
            cache_id=cache_id,
            query_embedding=query_embedding,
            top_k=top_k,
        )
        if chroma_results:
            return chroma_results
        return store._search_chunks_with_sqlite(
            cache_id=cache_id,
            query_embedding=query_embedding,
            top_k=top_k,
        )
    except Exception as exc:
        logger.error("Chunk search failed: %s", exc)
        return []


def rank_links_with_chroma(
    store: "VectorStore",
    cache_id: int,
    query_embedding: List[float],
    top_k: int,
) -> List[Tuple[Dict[str, str], float]]:
    collection = store._get_chroma_collection(store.chroma_links_collection)
    if collection is None:
        return []

    try:
        response = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=_build_chroma_cache_model_filter(
                cache_id=cache_id,
                embedding_model=store.embedding_client.model,
            ),
            include=["metadatas", "distances"],
        )
    except Exception as exc:
        logger.warning("Chroma link query failed; falling back to SQLite: %s", exc)
        return []

    metadatas = first_query_result(response.get("metadatas", []))
    distances = first_query_result(response.get("distances", []))

    ranked: List[Tuple[Dict[str, str], float]] = []
    for metadata, distance in zip(metadatas, distances):
        metadata = metadata or {}
        ranked.append(
            (
                {
                    "text": str(metadata.get("link_text", "")),
                    "href": str(metadata.get("link_url", "")),
                },
                distance_to_similarity(distance),
            )
        )

    ranked.sort(key=lambda item: item[1], reverse=True)
    return ranked[:top_k]


def rank_links_with_sqlite(
    store: "VectorStore",
    cache_id: int,
    query_embedding: List[float],
    top_k: int,
) -> List[Tuple[Dict[str, str], float]]:
    conn = store._get_conn()
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
    store: "VectorStore",
    cache_id: int,
    query: str,
    top_k: int = 20,
) -> List[Tuple[Dict[str, str], float]]:
    if not query:
        return []

    try:
        query_embedding = store.embedding_client.embed_single(query)
        chroma_ranked = store._rank_links_with_chroma(
            cache_id=cache_id,
            query_embedding=query_embedding,
            top_k=top_k,
        )
        if chroma_ranked:
            return chroma_ranked
        return store._rank_links_with_sqlite(
            cache_id=cache_id,
            query_embedding=query_embedding,
            top_k=top_k,
        )
    except Exception as exc:
        logger.error("Link ranking failed: %s", exc)
        return []


def has_chunk_embeddings(store: "VectorStore", cache_id: int) -> bool:
    conn = store._get_conn()
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


def has_chunk_embeddings_for_model(store: "VectorStore", cache_id: int, model: str) -> bool:
    if not model:
        return has_chunk_embeddings(store, cache_id)
    conn = store._get_conn()
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


def has_link_embeddings(store: "VectorStore", cache_id: int) -> bool:
    conn = store._get_conn()
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


def has_link_embeddings_for_model(store: "VectorStore", cache_id: int, model: str) -> bool:
    if not model:
        return has_link_embeddings(store, cache_id)
    has_embedding_model_column = store._table_has_column("link_embeddings", "embedding_model")
    if not has_embedding_model_column:
        return has_link_embeddings(store, cache_id)
    conn = store._get_conn()
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


def dense_scores_for_chunks_with_chroma(
    store: "VectorStore",
    cache_id: int,
    query_embedding: List[float],
    top_k: int,
) -> Dict[int, float]:
    collection = store._get_chroma_collection(store.chroma_chunks_collection)
    if collection is None:
        return {}

    try:
        response = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=_build_chroma_cache_model_filter(
                cache_id=cache_id,
                embedding_model=store.embedding_client.model,
            ),
            include=["metadatas", "distances"],
        )
    except Exception as exc:
        logger.warning("Chroma hybrid query failed; using SQLite dense scores: %s", exc)
        return {}

    metadatas = first_query_result(response.get("metadatas", []))
    distances = first_query_result(response.get("distances", []))
    scores: Dict[int, float] = {}
    for metadata, distance in zip(metadatas, distances):
        if not metadata:
            continue
        chunk_index_raw = metadata.get("chunk_index")
        try:
            chunk_index = int(chunk_index_raw)
        except (TypeError, ValueError):
            continue
        scores[chunk_index] = distance_to_similarity(distance)
    return scores


def search_chunks_hybrid(
    store: "VectorStore",
    cache_id: int,
    query: str,
    top_k: int | None = None,
    dense_weight: float = DEFAULT_DENSE_WEIGHT,
    min_score: float = 0.0,
) -> List[Dict[str, Any]]:
    top_k = top_k or RESEARCH_MAX_CHUNKS_PER_RETRIEVAL
    if not query or not query.strip():
        return []

    try:
        query_embedding = store.embedding_client.embed_single(query)
        query_tokens = tokenize_text(query)

        conn = store._get_conn()
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
        dense_candidate_limit = max(top_k * HYBRID_LEXICAL_CANDIDATE_MULTIPLIER, top_k)
        dense_scores_by_chunk = store._dense_scores_for_chunks_with_chroma(
            cache_id=cache_id,
            query_embedding=query_embedding,
            top_k=dense_candidate_limit,
        )
        use_chroma_dense_scores = len(dense_scores_by_chunk) > 0

        bm25_limit = max(top_k * HYBRID_LEXICAL_CANDIDATE_MULTIPLIER, top_k)
        bm25_scores_by_chunk = store._get_bm25_scores(
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
                lexical_score = lexical_overlap_score(query_tokens, chunk_text)

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
