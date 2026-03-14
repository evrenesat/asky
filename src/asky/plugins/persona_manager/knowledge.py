"""Persona embedding build and retrieval helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from asky.research.embeddings import get_embedding_client
from asky.research.vector_store_common import cosine_similarity
from asky.plugins.manual_persona_creator.knowledge_catalog import read_catalog
from asky.plugins.manual_persona_creator.knowledge_types import (
    PersonaSourceClass,
    PersonaTrustClass,
)
from asky.plugins.persona_manager.runtime_grounding import PersonaEvidencePacket

EMBEDDINGS_FILENAME = "embeddings.json"
DEFAULT_TOP_K = 3
EMBEDDING_BATCH_SIZE = 64
MAX_EMBEDDING_CHUNKS = 5000


def embeddings_path(persona_dir: Path) -> Path:
    """Return canonical embedding artifact path."""
    return persona_dir / EMBEDDINGS_FILENAME


def rebuild_embeddings(
    *,
    persona_dir: Path,
    chunks: List[Dict[str, Any]],
    max_chunks: int = MAX_EMBEDDING_CHUNKS,
) -> Dict[str, Any]:
    """Rebuild embeddings from normalized chunk payloads."""
    usable_chunks = [chunk for chunk in chunks if str(chunk.get("text", "")).strip()]
    usable_chunks = usable_chunks[: int(max_chunks)]
    client = get_embedding_client()

    records: List[Dict[str, Any]] = []
    for index in range(0, len(usable_chunks), EMBEDDING_BATCH_SIZE):
        batch = usable_chunks[index : index + EMBEDDING_BATCH_SIZE]
        vectors = client.embed([str(item.get("text", "")) for item in batch])
        for chunk, vector in zip(batch, vectors):
            records.append(
                {
                    "chunk_id": str(chunk.get("chunk_id", "") or ""),
                    "vector": [float(value) for value in vector],
                    "text": str(chunk.get("text", "") or ""),
                    "source": str(chunk.get("source", "") or ""),
                    "title": str(chunk.get("title", "") or ""),
                }
            )

    output_path = embeddings_path(persona_dir)
    output_path.write_text(json.dumps(records, ensure_ascii=True), encoding="utf-8")
    return {
        "embedded_chunks": len(records),
        "skipped_chunks": max(0, len(chunks) - len(usable_chunks)),
        "truncated": len(chunks) > len(usable_chunks),
    }


def retrieve_relevant_chunks(
    *,
    persona_dir: Path,
    query_text: str,
    top_k: int = DEFAULT_TOP_K,
) -> List[Dict[str, Any]]:
    """Retrieve top persona chunks by cosine similarity."""
    embedding_file = embeddings_path(persona_dir)
    if not embedding_file.exists():
        return []

    try:
        payload = json.loads(embedding_file.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, list):
        return []

    query = str(query_text or "").strip()
    if not query:
        return []

    try:
        query_vector = get_embedding_client().embed_single(query)
    except Exception:
        return []

    ranked: List[tuple[float, Dict[str, Any]]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        vector = item.get("vector")
        if not isinstance(vector, list):
            continue
        score = cosine_similarity(
            [float(value) for value in query_vector],
            [float(value) for value in vector],
        )
        ranked.append((score, item))

    ranked.sort(key=lambda row: row[0], reverse=True)
    return [
        {
            "score": score,
            "text": str(item.get("text", "") or ""),
            "source": str(item.get("source", "") or ""),
            "title": str(item.get("title", "") or ""),
            "chunk_id": str(item.get("chunk_id", "") or ""),
        }
        for score, item in ranked[: max(1, int(top_k))]
        if str(item.get("text", "") or "").strip()
    ]


def retrieve_evidence_packets(
    *,
    persona_dir: Path,
    query_text: str,
    top_k: int = DEFAULT_TOP_K,
) -> List[PersonaEvidencePacket]:
    """Retrieve top persona evidence packets with full metadata."""
    chunks = retrieve_relevant_chunks(
        persona_dir=persona_dir,
        query_text=query_text,
        top_k=top_k,
    )
    if not chunks:
        return []

    catalog = read_catalog(persona_dir)
    if catalog is None:
        # Fallback for v1/v2 if catalog missing
        return [
            PersonaEvidencePacket(
                packet_id=f"P{i+1}",
                source_label=c["source"],
                source_class=PersonaSourceClass.MANUAL_SOURCE,
                trust_class=PersonaTrustClass.USER_SUPPLIED_UNREVIEWED,
                text=c["text"],
                entry_id=f"chunk:{c['chunk_id']}",
                source_id="manual:unknown",
            )
            for i, c in enumerate(chunks)
        ]

    sources_map = {s.source_id: s for s in catalog["sources"]}
    entries_map = {e.entry_id: e for e in catalog["entries"]}

    packets: List[PersonaEvidencePacket] = []
    for i, chunk in enumerate(chunks):
        chunk_id = chunk["chunk_id"]
        entry_id = f"chunk:{chunk_id}"
        entry = entries_map.get(entry_id)
        
        if entry:
            source = sources_map.get(entry.source_id)
            if source:
                packets.append(
                    PersonaEvidencePacket(
                        packet_id=f"P{i+1}",
                        source_label=source.label,
                        source_class=source.source_class,
                        trust_class=source.trust_class,
                        text=entry.text,
                        entry_id=entry_id,
                        source_id=source.source_id,
                    )
                )
                continue

        # Fallback if entry/source not found in catalog
        packets.append(
            PersonaEvidencePacket(
                packet_id=f"P{i+1}",
                source_label=chunk["source"],
                source_class=PersonaSourceClass.MANUAL_SOURCE,
                trust_class=PersonaTrustClass.USER_SUPPLIED_UNREVIEWED,
                text=chunk["text"],
                entry_id=entry_id,
                source_id="manual:unknown",
            )
        )

    return packets
