"""Service for managing persona knowledge sources."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence

from asky.plugins.manual_persona_creator.ingestion import ingest_persona_sources
from asky.plugins.manual_persona_creator.knowledge_catalog import (
    read_catalog,
    write_catalog,
)
from asky.plugins.manual_persona_creator.knowledge_types import (
    PersonaEntryKind,
    PersonaKnowledgeEntry,
    PersonaSourceClass,
    PersonaSourceRecord,
    PersonaTrustClass,
)
from asky.plugins.manual_persona_creator.storage import (
    read_chunks,
    touch_updated_at,
    write_chunks,
)
from asky.plugins.persona_manager.knowledge import rebuild_embeddings


@dataclass(frozen=True)
class IngestionResult:
    processed_sources: int
    skipped_existing_sources: int
    added_chunks: int
    warning_count: int
    warnings: List[str]


def add_manual_sources(
    persona_root: Path,
    sources: Sequence[str],
) -> IngestionResult:
    """Ingest manual sources and update persona artifacts."""
    catalog = read_catalog(persona_root)
    if catalog is None:
        # Should not happen for schema v3, but we might be rebuilding
        from asky.plugins.manual_persona_creator.knowledge_catalog import (
            rebuild_catalog_from_legacy,
        )

        rebuild_catalog_from_legacy(persona_root)
        catalog = read_catalog(persona_root)
        if catalog is None:
            raise ValueError(f"Failed to read/rebuild catalog for {persona_root}")

    existing_sources = catalog["sources"]
    existing_entries = catalog["entries"]
    
    existing_fingerprints = {
        s.content_fingerprint for s in existing_sources if s.content_fingerprint
    }

    ingest_result = ingest_persona_sources(sources=sources)
    raw_chunks = ingest_result["chunks"]
    warnings = ingest_result["warnings"]
    
    # Group chunks by source label to compute fingerprints
    chunks_by_source: Dict[str, List[Dict[str, Any]]] = {}
    for chunk in raw_chunks:
        source_label = chunk["source"]
        chunks_by_source.setdefault(source_label, []).append(chunk)

    new_sources: List[PersonaSourceRecord] = []
    new_entries: List[PersonaKnowledgeEntry] = []
    skipped_count = 0

    for source_label, source_chunks in chunks_by_source.items():
        # Re-compute fingerprint from actual ingested content
        content_fingerprint = hashlib.sha256(
            "".join(c["text"] for c in source_chunks).encode("utf-8")
        ).hexdigest()

        if content_fingerprint in existing_fingerprints:
            skipped_count += 1
            continue

        source_id = f"manual:{content_fingerprint[:16]}"
        
        # Check if source_id already exists (unlikely but possible)
        if any(s.source_id == source_id for s in existing_sources):
             skipped_count += 1
             continue

        source_record = PersonaSourceRecord(
            source_id=source_id,
            source_class=PersonaSourceClass.MANUAL_SOURCE,
            trust_class=PersonaTrustClass.USER_SUPPLIED_UNREVIEWED,
            label=source_label,
            content_fingerprint=content_fingerprint,
        )
        new_sources.append(source_record)

        for chunk in source_chunks:
            # We want deterministic chunk IDs within this source
            chunk_text = chunk["text"]
            chunk_fingerprint = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
            entry_id = f"chunk:{chunk_fingerprint[:16]}"
            
            new_entries.append(
                PersonaKnowledgeEntry(
                    entry_id=entry_id,
                    entry_kind=PersonaEntryKind.RAW_CHUNK,
                    source_id=source_id,
                    text=chunk_text,
                    metadata={
                        "chunk_index": chunk["chunk_index"],
                        "title": chunk["title"],
                    },
                )
            )

    if not new_sources:
        return IngestionResult(
            processed_sources=0,
            skipped_existing_sources=skipped_count,
            added_chunks=0,
            warning_count=len(warnings),
            warnings=warnings,
        )

    # Update catalog
    all_sources = list(existing_sources) + new_sources
    all_entries = list(existing_entries) + new_entries
    write_catalog(persona_root, all_sources, all_entries)

    # Update legacy chunks.json for compatibility
    existing_chunks = read_chunks(persona_root / "chunks.json")
    
    # Convert new_entries to legacy chunk format
    compat_chunks = []
    for entry in new_entries:
        source_record = next(s for s in new_sources if s.source_id == entry.source_id)
        compat_chunks.append({
            "chunk_id": entry.entry_id.replace("chunk:", ""),
            "chunk_index": entry.metadata.get("chunk_index", 0),
            "text": entry.text,
            "source": source_record.label,
            "title": entry.metadata.get("title", ""),
        })
    
    all_compat_chunks = existing_chunks + compat_chunks
    write_chunks(persona_root / "chunks.json", all_compat_chunks)

    # Rebuild embeddings
    rebuild_embeddings(persona_dir=persona_root, chunks=all_compat_chunks)
    
    touch_updated_at(persona_root / "metadata.toml")

    return IngestionResult(
        processed_sources=len(new_sources),
        skipped_existing_sources=skipped_count,
        added_chunks=len(new_entries),
        warning_count=len(warnings),
        warnings=warnings,
    )
