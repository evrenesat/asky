"""Finding-memory operations for VectorStore."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from asky.research.embeddings import EmbeddingClient
from asky.research.vector_store_common import (
    cosine_similarity,
    distance_to_similarity,
    first_query_result,
)

if TYPE_CHECKING:
    from asky.research.vector_store import VectorStore

logger = logging.getLogger(__name__)


def upsert_finding_to_chroma(
    store: "VectorStore",
    finding_id: int,
    finding_text: str,
    embedding: List[float],
) -> None:
    collection = store._get_chroma_collection(store.chroma_findings_collection)
    if collection is None:
        return

    try:
        collection.delete(ids=[store._finding_chroma_id(finding_id)])
        collection.add(
            ids=[store._finding_chroma_id(finding_id)],
            documents=[finding_text],
            embeddings=[embedding],
            metadatas=[
                {
                    "finding_id": finding_id,
                    "embedding_model": store.embedding_client.model,
                }
            ],
        )
    except Exception as exc:
        logger.error("Failed to upsert finding embedding into ChromaDB: %s", exc)


def store_finding_embedding(
    store: "VectorStore",
    finding_id: int,
    finding_text: str,
) -> bool:
    if not finding_text or not finding_text.strip():
        return False

    try:
        embedding = store.embedding_client.embed_single(finding_text)
        embedding_bytes = EmbeddingClient.serialize_embedding(embedding)

        conn = store._get_conn()
        c = conn.cursor()
        c.execute(
            """
            UPDATE research_findings
            SET embedding = ?, embedding_model = ?
            WHERE id = ?
        """,
            (embedding_bytes, store.embedding_client.model, finding_id),
        )
        success = c.rowcount > 0
        conn.commit()
        conn.close()

        if success:
            upsert_finding_to_chroma(
                store=store,
                finding_id=finding_id,
                finding_text=finding_text,
                embedding=embedding,
            )
            logger.debug("Stored embedding for finding id=%s", finding_id)
        return success
    except Exception as exc:
        logger.error("Failed to store finding embedding: %s", exc)
        return False


def search_findings_with_chroma(
    store: "VectorStore",
    query_embedding: List[float],
    top_k: int,
) -> List[Tuple[int, float]]:
    collection = store._get_chroma_collection(store.chroma_findings_collection)
    if collection is None:
        return []

    try:
        response = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where={"embedding_model": store.embedding_client.model},
            include=["metadatas", "distances"],
        )
    except Exception as exc:
        logger.warning("Chroma finding query failed; falling back to SQLite: %s", exc)
        return []

    metadatas = first_query_result(response.get("metadatas", []))
    distances = first_query_result(response.get("distances", []))

    ranked_ids: List[Tuple[int, float]] = []
    for metadata, distance in zip(metadatas, distances):
        if not metadata:
            continue
        raw_id = metadata.get("finding_id")
        try:
            row_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        ranked_ids.append((row_id, distance_to_similarity(distance)))

    ranked_ids.sort(key=lambda item: item[1], reverse=True)
    return ranked_ids[:top_k]


def fetch_findings_by_ids(
    store: "VectorStore",
    finding_ids: List[int],
    session_id: Optional[str] = None,
) -> Dict[int, Dict[str, Any]]:
    if not finding_ids:
        return {}

    conn = store._get_conn()
    c = conn.cursor()
    placeholders = ",".join("?" * len(finding_ids))
    query = f"""
        SELECT id, finding_text, source_url, source_title, tags, created_at, session_id
        FROM research_findings
        WHERE id IN ({placeholders})
        """
    query_args: List[Any] = list(finding_ids)
    if session_id is not None:
        query += " AND session_id = ?"
        query_args.append(session_id)

    c.execute(query, query_args)
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


def search_findings_with_sqlite(
    store: "VectorStore",
    query_embedding: List[float],
    top_k: int,
    session_id: Optional[str] = None,
) -> List[Tuple[Dict[str, Any], float]]:
    conn = store._get_conn()
    c = conn.cursor()
    query = """
        SELECT id, finding_text, source_url, source_title, tags,
               embedding, created_at, session_id
        FROM research_findings
        WHERE embedding IS NOT NULL
    """
    query_args: List[Any] = []
    if session_id is not None:
        query += " AND session_id = ?"
        query_args.append(session_id)

    c.execute(query, query_args)
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


def has_finding_embeddings_for_model(
    store: "VectorStore",
    model: str,
    session_id: Optional[str] = None,
) -> bool:
    conn = store._get_conn()
    c = conn.cursor()
    if model and session_id is not None:
        c.execute(
            """
            SELECT COUNT(*) FROM research_findings
            WHERE embedding IS NOT NULL AND embedding_model = ? AND session_id = ?
        """,
            (model, session_id),
        )
    elif model:
        c.execute(
            """
            SELECT COUNT(*) FROM research_findings
            WHERE embedding IS NOT NULL AND embedding_model = ?
        """,
            (model,),
        )
    elif session_id is not None:
        c.execute(
            """
            SELECT COUNT(*) FROM research_findings
            WHERE embedding IS NOT NULL AND session_id = ?
        """,
            (session_id,),
        )
    else:
        c.execute(
            """
            SELECT COUNT(*) FROM research_findings
            WHERE embedding IS NOT NULL
        """
        )
    count = c.fetchone()[0]
    conn.close()
    return count > 0


def search_findings(
    store: "VectorStore",
    query: str,
    top_k: int = 10,
    session_id: Optional[str] = None,
) -> List[Tuple[Dict[str, Any], float]]:
    if not query or not query.strip():
        return []

    try:
        if not store._has_finding_embeddings_for_model(
            store.embedding_client.model,
            session_id=session_id,
        ):
            return []
        query_embedding = store.embedding_client.embed_single(query)

        chroma_ranked_ids = store._search_findings_with_chroma(
            query_embedding=query_embedding,
            top_k=top_k,
        )
        if chroma_ranked_ids:
            finding_ids = [finding_id for finding_id, _ in chroma_ranked_ids]
            findings_by_id = store._fetch_findings_by_ids(
                finding_ids,
                session_id=session_id,
            )
            ranked_findings: List[Tuple[Dict[str, Any], float]] = []
            for finding_id, similarity in chroma_ranked_ids:
                finding = findings_by_id.get(finding_id)
                if finding is None:
                    continue
                ranked_findings.append((finding, similarity))
            if ranked_findings:
                return ranked_findings[:top_k]

        return store._search_findings_with_sqlite(
            query_embedding=query_embedding,
            top_k=top_k,
            session_id=session_id,
        )
    except Exception as exc:
        logger.error("Finding search failed: %s", exc)
        return []


def has_finding_embedding(store: "VectorStore", finding_id: int) -> bool:
    conn = store._get_conn()
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


def delete_findings_by_session(store: "VectorStore", session_id: str) -> int:
    """Delete findings and their embeddings for a session from both SQLite and ChromaDB.

    Returns the number of findings deleted.
    """
    conn = store._get_conn()
    c = conn.cursor()
    # Get all finding IDs for this session to delete from Chroma
    c.execute("SELECT id FROM research_findings WHERE session_id = ?", (session_id,))
    finding_ids = [row[0] for row in c.fetchall()]

    if not finding_ids:
        conn.close()
        return 0

    # 1. Delete from ChromaDB
    collection = store._get_chroma_collection(store.chroma_findings_collection)
    if collection is not None:
        try:
            chroma_ids = [store._finding_chroma_id(fid) for fid in finding_ids]
            collection.delete(ids=chroma_ids)
        except Exception as exc:
            logger.error(
                "Failed to delete matching finding embeddings from ChromaDB for session %s: %s",
                session_id,
                exc,
            )

    # 2. Delete from SQLite
    c.execute("DELETE FROM research_findings WHERE session_id = ?", (session_id,))
    deleted_count = c.rowcount
    conn.commit()
    conn.close()

    if deleted_count > 0:
        logger.debug(
            "Deleted %s findings and embeddings for session %s",
            deleted_count,
            session_id,
        )
    return deleted_count
