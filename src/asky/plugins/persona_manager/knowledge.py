"""Persona embedding build and retrieval helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from asky.research.embeddings import get_embedding_client

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
