"""Runtime index management for persona knowledge."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from asky.plugins.manual_persona_creator.knowledge_catalog import read_catalog
from asky.plugins.manual_persona_creator.knowledge_types import (
    PersonaEntryKind,
    PersonaSourceClass,
    PersonaTrustClass,
)
from asky.research.embeddings import get_embedding_client

RUNTIME_INDEX_FILENAME = "runtime_index.json"
EMBEDDING_BATCH_SIZE = 64


@dataclass(frozen=True)
class PersonaRuntimeIndexRecord:
    """A single record in the derived persona runtime index."""

    entry_id: str
    entry_kind: PersonaEntryKind
    source_id: str
    source_label: str
    source_class: PersonaSourceClass
    trust_class: PersonaTrustClass
    text: str  # normalized searchable text
    metadata: Dict[str, Any] = field(default_factory=dict)
    vector: List[float] = field(default_factory=list)


def runtime_index_path(persona_dir: Path) -> Path:
    """Return canonical runtime index artifact path."""
    return persona_dir / "persona_knowledge" / RUNTIME_INDEX_FILENAME


def rebuild_runtime_index(persona_dir: Path) -> Dict[str, Any]:
    """Rebuild the runtime index from the canonical knowledge catalog."""
    catalog = read_catalog(persona_dir)
    if not catalog:
        return {"rebuilt": False, "reason": "catalog_missing"}

    sources_map = {s.source_id: s for s in catalog["sources"]}
    records: List[PersonaRuntimeIndexRecord] = []

    for entry in catalog["entries"]:
        source = sources_map.get(entry.source_id)
        if not source:
            continue

        # Extract only necessary runtime metadata
        runtime_metadata = {}
        for key in [
            "topic",
            "stance_label",
            "book_key",
            "book_title",
            "publication_year",
            "section_ref",
        ]:
            if key in entry.metadata:
                runtime_metadata[key] = entry.metadata[key]

        if entry.parent_entry_id:
            runtime_metadata["parent_entry_id"] = entry.parent_entry_id

        records.append(
            PersonaRuntimeIndexRecord(
                entry_id=entry.entry_id,
                entry_kind=entry.entry_kind,
                source_id=entry.source_id,
                source_label=source.label,
                source_class=source.source_class,
                trust_class=source.trust_class,
                text=entry.text,
                metadata=runtime_metadata,
            )
        )

    if not records:
        return {"rebuilt": True, "indexed_entries": 0}

    # Generate embeddings
    client = get_embedding_client()
    indexed_records: List[Dict[str, Any]] = []

    for i in range(0, len(records), EMBEDDING_BATCH_SIZE):
        batch = records[i : i + EMBEDDING_BATCH_SIZE]
        texts = [r.text for r in batch]
        vectors = client.embed(texts)

        for record, vector in zip(batch, vectors):
            data = asdict(record)
            data["vector"] = [float(v) for v in vector]
            indexed_records.append(data)

    output_path = runtime_index_path(persona_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    temp_path = output_path.with_suffix(".tmp")
    temp_path.write_text(
        json.dumps(indexed_records, ensure_ascii=True, indent=2), encoding="utf-8"
    )
    temp_path.replace(output_path)

    return {"rebuilt": True, "indexed_entries": len(indexed_records)}


def read_runtime_index(persona_dir: Path) -> List[Dict[str, Any]]:
    """Read the runtime index if it exists."""
    path = runtime_index_path(persona_dir)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
