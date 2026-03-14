"""Knowledge catalog management for persona packages."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from asky.plugins.manual_persona_creator.knowledge_types import (
    PersonaEntryKind,
    PersonaKnowledgeEntry,
    PersonaSourceClass,
    PersonaSourceRecord,
    PersonaTrustClass,
)
from asky.plugins.manual_persona_creator.storage import (
    AUTHORED_BOOKS_DIR_NAME,
    BOOK_METADATA_FILENAME,
    VIEWPOINTS_FILENAME,
    read_book_metadata,
    read_chunks,
)

KNOWLEDGE_DIR_NAME = "persona_knowledge"
SOURCES_FILENAME = "sources.json"
ENTRIES_FILENAME = "entries.json"


def get_knowledge_paths(persona_root: Path) -> Dict[str, Path]:
    """Resolve canonical files for persona knowledge."""
    knowledge_dir = persona_root / KNOWLEDGE_DIR_NAME
    return {
        "dir": knowledge_dir,
        "sources": knowledge_dir / SOURCES_FILENAME,
        "entries": knowledge_dir / ENTRIES_FILENAME,
    }


def write_catalog(
    persona_root: Path,
    sources: List[PersonaSourceRecord],
    entries: List[PersonaKnowledgeEntry],
) -> None:
    """Persist knowledge catalog atomically."""
    paths = get_knowledge_paths(persona_root)
    paths["dir"].mkdir(parents=True, exist_ok=True)

    sources_data = [asdict(s) for s in sources]
    entries_data = [asdict(e) for e in entries]

    _write_json_atomic(paths["sources"], sources_data)
    _write_json_atomic(paths["entries"], entries_data)


def read_catalog(persona_root: Path) -> Optional[Dict[str, Any]]:
    """Read knowledge catalog if it exists."""
    paths = get_knowledge_paths(persona_root)
    if not paths["sources"].exists() or not paths["entries"].exists():
        return None

    sources_data = json.loads(paths["sources"].read_text(encoding="utf-8"))
    entries_data = json.loads(paths["entries"].read_text(encoding="utf-8"))

    return {
        "sources": [PersonaSourceRecord(**s) for s in sources_data],
        "entries": [PersonaKnowledgeEntry(**e) for e in entries_data],
    }


def rebuild_catalog_from_legacy(persona_root: Path) -> None:
    """Rebuild catalog from v1/v2 artifacts (chunks.json and authored_books/)."""
    sources: List[PersonaSourceRecord] = []
    entries: List[PersonaKnowledgeEntry] = []

    # 1. Project authored books
    books_root = persona_root / AUTHORED_BOOKS_DIR_NAME
    if books_root.exists():
        for book_dir in sorted(books_root.iterdir()):
            if not book_dir.is_dir():
                continue
            
            book_key = book_dir.name
            metadata_path = book_dir / BOOK_METADATA_FILENAME
            viewpoints_path = book_dir / VIEWPOINTS_FILENAME
            
            if not metadata_path.exists():
                continue
                
            book_metadata = read_book_metadata(metadata_path)
            
            # Milestone 1 vs Legacy compatibility
            book_info = book_metadata.get("book", book_metadata)
            title = book_info.get("title", book_key)
            
            source_id = f"book:{book_key}"
            sources.append(
                PersonaSourceRecord(
                    source_id=source_id,
                    source_class=PersonaSourceClass.AUTHORED_BOOK,
                    trust_class=PersonaTrustClass.AUTHORED_PRIMARY,
                    label=title,
                    metadata=book_info,
                )
            )
            
            if viewpoints_path.exists():
                viewpoints = json.loads(viewpoints_path.read_text(encoding="utf-8"))
                for vp in viewpoints:
                    # Support both ViewpointEntry and legacy shapes
                    vp_id = vp.get("entry_id") or vp.get("viewpoint_id", "")
                    if not vp_id:
                        continue
                    
                    entry_id = f"viewpoint:{vp_id}"
                    text = vp.get("claim") or vp.get("viewpoint_text", "")
                    
                    # Metadata for canonical entry
                    vp_metadata = {
                        "topic": vp.get("topic", ""),
                        "confidence": vp.get("confidence", 0),
                    }
                    # Include milestone-1 extra metadata if present
                    for key in ["stance_label", "book_key", "book_title", "publication_year", "isbn"]:
                        if key in vp:
                            vp_metadata[key] = vp[key]

                    entries.append(
                        PersonaKnowledgeEntry(
                            entry_id=entry_id,
                            entry_kind=PersonaEntryKind.VIEWPOINT,
                            source_id=source_id,
                            text=text,
                            metadata=vp_metadata,
                        )
                    )
                    
                    # Project evidence
                    evidence_list = vp.get("evidence", [])
                    for i, evidence in enumerate(evidence_list):
                        evidence_text = evidence.get("excerpt") or evidence.get("text", "")
                        section_ref = evidence.get("section_ref") or evidence.get("page_ref", "")
                        
                        entries.append(
                            PersonaKnowledgeEntry(
                                entry_id=f"evidence:{vp_id}:{i}",
                                entry_kind=PersonaEntryKind.EVIDENCE_EXCERPT,
                                source_id=source_id,
                                text=evidence_text,
                                metadata={
                                    "section_ref": section_ref,
                                    "context": evidence.get("context", ""),
                                },
                                parent_entry_id=entry_id,
                            )
                        )

    # 2. Project raw chunks
    chunks_path = persona_root / "chunks.json"
    if chunks_path.exists():
        chunks = read_chunks(chunks_path)
        # Group chunks by source to create SourceRecords
        chunks_by_source: Dict[str, List[Dict[str, Any]]] = {}
        for chunk in chunks:
            source_label = chunk.get("source", "manual_upload")
            # Skip authored-book compatibility chunks (e.g., authored-book://<book_key>)
            if source_label.startswith("authored-book://"):
                continue
            chunks_by_source.setdefault(source_label, []).append(chunk)
            
        for source_label, source_chunks in chunks_by_source.items():
            # Create a fingerprint for the manual source based on its chunks
            content_fingerprint = hashlib.sha256(
                "".join(c.get("text", "") for c in source_chunks).encode("utf-8")
            ).hexdigest()
            
            source_id = f"manual:{content_fingerprint[:16]}"
            
            # Check if we already have this manual source (unlikely with fingerprint, but good for safety)
            if not any(s.source_id == source_id for s in sources):
                sources.append(
                    PersonaSourceRecord(
                        source_id=source_id,
                        source_class=PersonaSourceClass.MANUAL_SOURCE,
                        trust_class=PersonaTrustClass.USER_SUPPLIED_UNREVIEWED,
                        label=source_label,
                        content_fingerprint=content_fingerprint,
                    )
                )
            
            for chunk in source_chunks:
                chunk_id = chunk.get("chunk_id", "")
                if not chunk_id:
                    continue
                
                entries.append(
                    PersonaKnowledgeEntry(
                        entry_id=f"chunk:{chunk_id}",
                        entry_kind=PersonaEntryKind.RAW_CHUNK,
                        source_id=source_id,
                        text=chunk.get("text", ""),
                        metadata={
                            "chunk_index": chunk.get("chunk_index", 0),
                            "title": chunk.get("title", ""),
                        },
                    )
                )

    write_catalog(persona_root, sources, entries)


def _write_json_atomic(path: Path, data: Any) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(data, indent=2, ensure_ascii=True), encoding="utf-8")
    temp_path.replace(path)
