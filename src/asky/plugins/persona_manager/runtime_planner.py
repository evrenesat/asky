"""Structured persona retrieval and packet planning."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from asky.plugins.manual_persona_creator.knowledge_types import (
    PersonaEntryKind,
    PersonaSourceClass,
    PersonaTrustClass,
)
from asky.plugins.manual_persona_creator.runtime_index import read_runtime_index
from asky.plugins.persona_manager.runtime_types import PersonaEvidencePacket
from asky.research.embeddings import get_embedding_client
from asky.research.vector_store_common import cosine_similarity

# Relevance floor for primary worldview support (viewpoints and raw chunks).
# Below this, we consider the topic "unseen" and return zero packets.
MIN_PRIMARY_RELEVANCE = 0.40

# Entry kinds that can serve as primary packets.
# EVIDENCE_EXCERPT is attached support only.
PRIMARY_KINDS = {
    PersonaEntryKind.VIEWPOINT,
    PersonaEntryKind.RAW_CHUNK,
}

# Exact priority for entry kinds (lower is better)
KIND_PRIORITY = {
    PersonaEntryKind.VIEWPOINT: 0,
    PersonaEntryKind.RAW_CHUNK: 1,
}

# Trust priority (lower is better)
TRUST_PRIORITY = {
    PersonaTrustClass.AUTHORED_PRIMARY: 0,
    PersonaTrustClass.USER_SUPPLIED_UNREVIEWED: 1,
    PersonaTrustClass.MIXED_ATTRIBUTION: 2,
    PersonaTrustClass.THIRD_PARTY_SECONDARY: 3,
    PersonaTrustClass.UNREVIEWED_WEB: 4,
    PersonaTrustClass.TRANSCRIPT_UNREVIEWED: 5,
}


def plan_persona_packets(
    *,
    persona_dir: Path,
    query_text: str,
    top_k: int,
) -> List[PersonaEvidencePacket]:
    """Retrieve and rank persona knowledge into structured evidence packets."""
    index = read_runtime_index(persona_dir)
    if not index:
        return []

    query = str(query_text or "").strip()
    if not query:
        return []

    try:
        query_vector = get_embedding_client().embed_single(query)
    except Exception:
        return []

    # 1. Rank by similarity and priority
    primary_candidates: List[Tuple[float, Dict[str, Any]]] = []
    for item in index:
        vector = item.get("vector")
        if not vector:
            continue

        kind = item.get("entry_kind")
        if kind not in PRIMARY_KINDS:
            continue

        score = cosine_similarity(query_vector, vector)
        if score < MIN_PRIMARY_RELEVANCE:
            continue

        primary_candidates.append((score, item))

    if not primary_candidates:
        return []

    # Multi-level sort: score (desc), kind priority (asc), trust priority (asc), authored-book preference, deterministic entry_id
    def sort_key(row):
        score, item = row
        kind = item.get("entry_kind")
        trust = item.get("trust_class")
        source_class = item.get("source_class")

        return (
            -score,
            KIND_PRIORITY.get(kind, 99),
            TRUST_PRIORITY.get(trust, 99),
            0 if source_class == PersonaSourceClass.AUTHORED_BOOK else 1,
            item.get("entry_id", ""),
        )

    primary_candidates.sort(key=sort_key)
    top_matches = primary_candidates[:top_k]

    # 2. Hydrate packets
    packets: List[PersonaEvidencePacket] = []
    for i, (score, item) in enumerate(top_matches):
        entry_id = item["entry_id"]
        kind = item["entry_kind"]
        metadata = item.get("metadata", {})

        supporting_excerpts = []
        # Step 3: Hydrate viewpoint packets with linked supporting excerpts
        if kind == PersonaEntryKind.VIEWPOINT:
            # Find excerpts that have this viewpoint as parent
            for other in index:
                if (
                    other.get("entry_kind") == PersonaEntryKind.EVIDENCE_EXCERPT
                    and other.get("metadata", {}).get("parent_entry_id") == entry_id
                ):
                    supporting_excerpts.append(other["text"])

        packets.append(
            PersonaEvidencePacket(
                packet_id=f"P{i+1}",
                entry_id=entry_id,
                entry_kind=kind,
                source_id=item["source_id"],
                source_label=item["source_label"],
                source_class=item["source_class"],
                trust_class=item["trust_class"],
                text=item["text"],
                metadata=metadata,
                supporting_excerpts=supporting_excerpts,
            )
        )

    return packets
