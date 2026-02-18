"""Vector embedding operations for user memory storage and retrieval."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from asky.research.embeddings import EmbeddingClient
from asky.research.vector_store_common import cosine_similarity, distance_to_similarity

logger = logging.getLogger(__name__)

CHROMA_COLLECTION_SPACE = "cosine"


def _get_chroma_client(chroma_dir: Path) -> Optional[Any]:
    """Return a Chroma persistent client, or None if ChromaDB is unavailable."""
    try:
        import chromadb  # type: ignore

        return chromadb.PersistentClient(path=str(chroma_dir))
    except Exception as exc:
        logger.debug("ChromaDB unavailable for memory ops: %s", exc)
        return None


def _get_chroma_collection(
    chroma_dir: Path, collection_name: str
) -> Optional[Any]:
    """Get or create a named Chroma collection."""
    client = _get_chroma_client(chroma_dir)
    if client is None:
        return None
    try:
        return client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": CHROMA_COLLECTION_SPACE},
        )
    except Exception as exc:
        logger.debug("Failed to get/create Chroma memory collection: %s", exc)
        return None


def _memory_chroma_id(memory_id: int) -> str:
    return f"memory:{memory_id}"


def _parse_memory_id_from_chroma(chroma_id: str) -> Optional[int]:
    if chroma_id.startswith("memory:"):
        try:
            return int(chroma_id[len("memory:") :])
        except ValueError:
            pass
    return None


def store_memory_embedding(
    db_path: Path,
    chroma_dir: Path,
    memory_id: int,
    text: str,
    collection_name: str,
) -> bool:
    """Embed text and persist it to SQLite BLOB and Chroma collection."""
    if not text or not text.strip():
        return False

    try:
        client = EmbeddingClient()
        embedding = client.embed_single(text)
        embedding_bytes = EmbeddingClient.serialize_embedding(embedding)

        # Persist to SQLite
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute(
            "UPDATE user_memories SET embedding = ?, embedding_model = ? WHERE id = ?",
            (embedding_bytes, client.model, memory_id),
        )
        success = c.rowcount > 0
        conn.commit()
        conn.close()

        if not success:
            return False

        # Upsert to Chroma
        collection = _get_chroma_collection(chroma_dir, collection_name)
        if collection is not None:
            try:
                chroma_id = _memory_chroma_id(memory_id)
                collection.delete(ids=[chroma_id])
                collection.add(
                    ids=[chroma_id],
                    documents=[text],
                    embeddings=[embedding],
                    metadatas=[{"memory_id": memory_id, "embedding_model": client.model}],
                )
            except Exception as exc:
                logger.warning("Failed to upsert memory embedding to Chroma: %s", exc)

        return True
    except Exception as exc:
        logger.error("Failed to store memory embedding: %s", exc)
        return False


def _search_with_chroma(
    chroma_dir: Path,
    query_embedding: List[float],
    top_k: int,
    collection_name: str,
    embedding_model: str,
) -> List[Tuple[int, float]]:
    """Query Chroma and return (memory_id, similarity) pairs."""
    collection = _get_chroma_collection(chroma_dir, collection_name)
    if collection is None:
        return []

    try:
        response = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where={"embedding_model": embedding_model},
            include=["metadatas", "distances"],
        )
    except Exception as exc:
        logger.debug("Chroma memory query failed: %s", exc)
        return []

    metadatas = response.get("metadatas", [])
    distances = response.get("distances", [])
    if not metadatas or not distances:
        return []

    meta_list = metadatas[0] if isinstance(metadatas[0], list) else metadatas
    dist_list = distances[0] if isinstance(distances[0], list) else distances

    results: List[Tuple[int, float]] = []
    for meta, dist in zip(meta_list, dist_list):
        if not meta:
            continue
        raw_id = meta.get("memory_id")
        try:
            memory_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        similarity = distance_to_similarity(dist)
        results.append((memory_id, similarity))

    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_k]


def _search_with_sqlite(
    db_path: Path,
    query_embedding: List[float],
    top_k: int,
    min_similarity: float,
) -> List[Tuple[Dict[str, Any], float]]:
    """Full scan of SQLite embeddings with cosine similarity. Used as Chroma fallback."""
    import json

    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        "SELECT id, memory_text, tags, created_at, embedding FROM user_memories WHERE embedding IS NOT NULL"
    )
    rows = c.fetchall()
    conn.close()

    if not rows:
        return []

    results = []
    for row in rows:
        memory_id, memory_text, tags_json, created_at, embedding_bytes = row
        stored_embedding = EmbeddingClient.deserialize_embedding(embedding_bytes)
        similarity = cosine_similarity(query_embedding, stored_embedding)
        if similarity < min_similarity:
            continue
        memory_dict = {
            "id": memory_id,
            "memory_text": memory_text,
            "tags": json.loads(tags_json) if tags_json else [],
            "created_at": created_at,
        }
        results.append((memory_dict, similarity))

    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_k]


def search_memories(
    db_path: Path,
    chroma_dir: Path,
    query: str,
    top_k: int,
    min_similarity: float,
    collection_name: str,
) -> List[Tuple[Dict[str, Any], float]]:
    """Search memories by embedding similarity. Returns (memory_dict, similarity) pairs."""
    import json

    if not query or not query.strip():
        return []

    try:
        client = EmbeddingClient()
        query_embedding = client.embed_single(query)

        chroma_results = _search_with_chroma(
            chroma_dir=chroma_dir,
            query_embedding=query_embedding,
            top_k=top_k,
            collection_name=collection_name,
            embedding_model=client.model,
        )

        if chroma_results:
            memory_ids = [mid for mid, _ in chroma_results]
            sims_by_id = {mid: sim for mid, sim in chroma_results}

            # Fetch rows from SQLite for the found IDs
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            placeholders = ",".join("?" * len(memory_ids))
            c.execute(
                f"SELECT id, memory_text, tags, created_at FROM user_memories WHERE id IN ({placeholders})",
                memory_ids,
            )
            rows = c.fetchall()
            conn.close()

            by_id = {r["id"]: r for r in rows}
            ranked: List[Tuple[Dict[str, Any], float]] = []
            for mid, sim in chroma_results:
                if sim < min_similarity:
                    continue
                row = by_id.get(mid)
                if row is None:
                    continue
                ranked.append(
                    (
                        {
                            "id": row["id"],
                            "memory_text": row["memory_text"],
                            "tags": json.loads(row["tags"]) if row["tags"] else [],
                            "created_at": row["created_at"],
                        },
                        sim,
                    )
                )
            if ranked:
                return ranked

        return _search_with_sqlite(
            db_path=db_path,
            query_embedding=query_embedding,
            top_k=top_k,
            min_similarity=min_similarity,
        )
    except Exception as exc:
        logger.error("Memory search failed: %s", exc)
        return []


def find_near_duplicate(
    db_path: Path,
    chroma_dir: Path,
    text: str,
    threshold: float,
    collection_name: str,
) -> Optional[int]:
    """Return memory_id if a near-duplicate already exists above threshold, else None."""
    if not text or not text.strip():
        return None

    try:
        client = EmbeddingClient()
        embedding = client.embed_single(text)

        chroma_results = _search_with_chroma(
            chroma_dir=chroma_dir,
            query_embedding=embedding,
            top_k=1,
            collection_name=collection_name,
            embedding_model=client.model,
        )

        if chroma_results:
            memory_id, similarity = chroma_results[0]
            if similarity >= threshold:
                return memory_id

        # SQLite fallback
        fallback = _search_with_sqlite(
            db_path=db_path,
            query_embedding=embedding,
            top_k=1,
            min_similarity=threshold,
        )
        if fallback:
            return fallback[0][0]["id"]

        return None
    except Exception as exc:
        logger.error("Near-duplicate search failed: %s", exc)
        return None


def delete_memory_from_chroma(
    chroma_dir: Path, memory_id: int, collection_name: str
) -> None:
    """Remove a memory embedding from the Chroma collection."""
    collection = _get_chroma_collection(chroma_dir, collection_name)
    if collection is None:
        return
    try:
        collection.delete(ids=[_memory_chroma_id(memory_id)])
    except Exception as exc:
        logger.warning(
            "Failed to delete memory %s from Chroma: %s", memory_id, exc
        )


def clear_all_memory_embeddings(chroma_dir: Path, collection_name: str) -> None:
    """Delete the entire Chroma collection for user memories."""
    client = _get_chroma_client(chroma_dir)
    if client is None:
        return
    try:
        client.delete_collection(collection_name)
    except Exception as exc:
        logger.warning("Failed to clear memory Chroma collection: %s", exc)
