"""Service for managing persona knowledge sources and milestone-3 structured extraction."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from asky.plugins.manual_persona_creator.ingestion import ingest_persona_sources
from asky.plugins.manual_persona_creator.knowledge_catalog import (
    CONFLICTS_FILENAME,
    ENTRIES_FILENAME,
    KNOWLEDGE_DIR_NAME,
    SOURCES_FILENAME,
    get_knowledge_paths,
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
from asky.plugins.manual_persona_creator.source_types import (
    PersonaReviewStatus,
    PersonaSourceIngestionJobManifest,
    PersonaSourceKind,
    PersonaSourceReportRecord,
)
from asky.plugins.manual_persona_creator.storage import (
    get_persona_paths,
    get_source_bundle_paths,
    get_source_id,
    get_source_job_paths,
    ensure_canonical_source_bundle,
    list_source_bundles,
    read_chunks,
    touch_updated_at,
    write_chunks,
    write_job_manifest,
)
from asky.plugins.manual_persona_creator.runtime_index import rebuild_runtime_index
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
    
    chunks_by_source: Dict[str, List[Dict[str, Any]]] = {}
    for chunk in raw_chunks:
        source_label = chunk["source"]
        chunks_by_source.setdefault(source_label, []).append(chunk)

    new_sources: List[PersonaSourceRecord] = []
    new_entries: List[PersonaKnowledgeEntry] = []
    skipped_count = 0

    for source_label, source_chunks in chunks_by_source.items():
        content_fingerprint = hashlib.sha256(
            "".join(c["text"] for c in source_chunks).encode("utf-8")
        ).hexdigest()

        if content_fingerprint in existing_fingerprints:
            skipped_count += 1
            continue

        source_id = f"manual:{content_fingerprint[:16]}"
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
        return IngestionResult(0, skipped_count, 0, len(warnings), warnings)

    all_sources = list(existing_sources) + new_sources
    all_entries = list(existing_entries) + new_entries
    write_catalog(persona_root, all_sources, all_entries)

    existing_chunks = read_chunks(persona_root / "chunks.json")
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

    rebuild_embeddings(persona_dir=persona_root, chunks=all_compat_chunks)
    rebuild_runtime_index(persona_dir=persona_root)
    touch_updated_at(persona_root / "metadata.toml")

    return IngestionResult(len(new_sources), skipped_count, len(new_entries), len(warnings), warnings)


# Milestone-3 Service Entrypoints

def validate_manual_source(kind: str, source_path: Path) -> None:
    """Validate manual source kind and path before staging.

    Raises ValueError if kind is unsupported or path does not exist.
    """
    supported_kinds = {
        "biography",
        "autobiography",
        "interview",
        "article",
        "essay",
        "speech",
        "notes",
        "posts",
    }

    if kind not in supported_kinds:
        raise ValueError(f"Unsupported source kind: {kind}")

    expanded_path = Path(source_path).expanduser()
    if not expanded_path.exists():
        raise ValueError(f"Source path does not exist: {source_path}")


def prepare_source_preflight(
    data_dir: Path,
    persona_name: str,
    kind: PersonaSourceKind,
    source_path: Path,
) -> Dict[str, Any]:
    """Prepare preflight info for source ingestion."""
    # Mappings from plan
    mappings = {
        PersonaSourceKind.BIOGRAPHY: (PersonaSourceClass.BIOGRAPHY_OR_AUTOBIOGRAPHY, PersonaTrustClass.THIRD_PARTY_SECONDARY, PersonaReviewStatus.PENDING),
        PersonaSourceKind.AUTOBIOGRAPHY: (PersonaSourceClass.BIOGRAPHY_OR_AUTOBIOGRAPHY, PersonaTrustClass.AUTHORED_PRIMARY, PersonaReviewStatus.APPROVED),
        PersonaSourceKind.INTERVIEW: (PersonaSourceClass.DIRECT_INTERVIEW, PersonaTrustClass.MIXED_ATTRIBUTION, PersonaReviewStatus.PENDING),
        PersonaSourceKind.ARTICLE: (PersonaSourceClass.MANUAL_SOURCE, PersonaTrustClass.AUTHORED_PRIMARY, PersonaReviewStatus.APPROVED),
        PersonaSourceKind.ESSAY: (PersonaSourceClass.MANUAL_SOURCE, PersonaTrustClass.AUTHORED_PRIMARY, PersonaReviewStatus.APPROVED),
        PersonaSourceKind.SPEECH: (PersonaSourceClass.MANUAL_SOURCE, PersonaTrustClass.AUTHORED_PRIMARY, PersonaReviewStatus.APPROVED),
        PersonaSourceKind.NOTES: (PersonaSourceClass.MANUAL_SOURCE, PersonaTrustClass.AUTHORED_PRIMARY, PersonaReviewStatus.APPROVED),
        PersonaSourceKind.POSTS: (PersonaSourceClass.MANUAL_SOURCE, PersonaTrustClass.AUTHORED_PRIMARY, PersonaReviewStatus.APPROVED),
    }
    source_class, trust_class, initial_status = mappings[kind]
    
    return {
        "kind": kind,
        "source_path": str(source_path),
        "source_class": source_class,
        "trust_class": trust_class,
        "initial_status": initial_status,
        "is_directory": source_path.is_dir(),
    }


def create_source_ingestion_job(
    data_dir: Path,
    persona_name: str,
    kind: PersonaSourceKind,
    source_path: Path,
) -> str:
    """Create a new source ingestion job."""
    paths = get_persona_paths(data_dir, persona_name)
    job_id = f"job_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    job_paths = get_source_job_paths(paths.root_dir, job_id)
    job_paths.job_dir.mkdir(parents=True, exist_ok=True)
    
    preflight = prepare_source_preflight(data_dir, persona_name, kind, source_path)
    
    manifest = PersonaSourceIngestionJobManifest(
        job_id=job_id,
        persona_name=persona_name,
        kind=kind,
        source_path=str(source_path),
        status="created",
        created_at=_utc_now_iso(),
        updated_at=_utc_now_iso(),
        metadata={
            "source_class": preflight["source_class"],
            "trust_class": preflight["trust_class"],
        },
    )
    write_job_manifest(job_paths.manifest_path, asdict(manifest))
    return job_id


def run_source_job(data_dir: Path, persona_name: str, job_id: str) -> PersonaSourceReportRecord:
    """Run a source ingestion job."""
    from asky.plugins.manual_persona_creator.source_job import SourceIngestionJob
    job = SourceIngestionJob(data_dir=data_dir, persona_name=persona_name, job_id=job_id)
    return job.run()


def list_source_bundles_for_persona(data_dir: Path, persona_name: str) -> List[Dict[str, Any]]:
    """List source bundles for a persona."""
    paths = get_persona_paths(data_dir, persona_name)
    bundles = []
    for source_id in list_source_bundles(paths.root_dir):
        bundle_paths = get_source_bundle_paths(paths.root_dir, source_id)
        if bundle_paths.metadata_path.exists():
            try:
                from asky.plugins.manual_persona_creator.storage import read_source_metadata
                metadata = read_source_metadata(bundle_paths.metadata_path)
                bundles.append(metadata)
            except:
                pass
    return bundles


def approve_source_bundle(data_dir: Path, persona_name: str, source_id: str):
    """Promote approved knowledge into canonical persona artifacts."""
    paths = get_persona_paths(data_dir, persona_name)
    bundle_paths = ensure_canonical_source_bundle(paths.root_dir, source_id)
    
    if not bundle_paths.metadata_path.exists():
        raise ValueError(f"Source bundle {source_id} not found")
        
    from asky.plugins.manual_persona_creator.storage import (
        read_source_metadata,
        write_source_metadata,
    )
    metadata = read_source_metadata(bundle_paths.metadata_path)
    metadata["review_status"] = PersonaReviewStatus.APPROVED
    metadata["updated_at"] = _utc_now_iso()
    write_source_metadata(bundle_paths.metadata_path, metadata)
    
    project_source_knowledge(
        persona_root=paths.root_dir,
        source_id=source_id,
        source_class=metadata["source_class"],
        trust_class=metadata["trust_class"],
        label=metadata["label"],
        source_kind=metadata.get("kind"),
        viewpoints_path=bundle_paths.viewpoints_path if bundle_paths.viewpoints_path.exists() else None,
        facts_path=bundle_paths.facts_path if bundle_paths.facts_path.exists() else None,
        timeline_path=bundle_paths.timeline_path if bundle_paths.timeline_path.exists() else None,
        conflicts_path=bundle_paths.conflicts_path if bundle_paths.conflicts_path.exists() else None,
        metadata=metadata.get("metadata", {}),
    )


def project_source_knowledge(
    *,
    persona_root: Path,
    source_id: str,
    source_class: PersonaSourceClass,
    trust_class: PersonaTrustClass,
    label: str,
    source_kind: Optional[str] = None,
    viewpoints_path: Optional[Path] = None,
    facts_path: Optional[Path] = None,
    timeline_path: Optional[Path] = None,
    conflicts_path: Optional[Path] = None,
    content_path: Optional[Path] = None,
    metadata: Optional[Dict[str, Any]] = None,
):
    """Shared projection logic for any milestone-3 knowledge source (book, source bundle, web page)."""
    catalog = read_catalog(persona_root)
    if catalog is None:
        from asky.plugins.manual_persona_creator.knowledge_catalog import (
            rebuild_catalog_from_legacy,
        )
        rebuild_catalog_from_legacy(persona_root)
        catalog = read_catalog(persona_root)
        
    if catalog is None:
        raise ValueError("Catalog not found and could not be rebuilt")
        
    # Idempotence: Remove existing records for this source before re-projecting
    sources = [s for s in catalog["sources"] if s.source_id != source_id]
    entries = [e for e in catalog["entries"] if e.source_id != source_id]
    
    # 1. Add Source Record
    source_record = PersonaSourceRecord(
        source_id=source_id,
        source_class=source_class,
        trust_class=trust_class,
        label=label,
        metadata=metadata or {},
    )
    sources.append(source_record)
        
    # 2. Project Viewpoints
    if viewpoints_path and viewpoints_path.exists():
        viewpoints = json.loads(viewpoints_path.read_text(encoding="utf-8"))
        for vp in viewpoints:
            entry_id = f"viewpoint:{source_id}:{uuid.uuid4().hex[:8]}"
            entries.append(PersonaKnowledgeEntry(
                entry_id=entry_id,
                entry_kind=PersonaEntryKind.VIEWPOINT,
                source_id=source_id,
                text=vp.get("claim") or vp.get("viewpoint", ""),
                metadata={
                    "topic": vp.get("topic"),
                    "confidence": vp.get("confidence"),
                    "source_kind": source_kind,
                },
            ))
            
    # 3. Project Facts
    if facts_path and facts_path.exists():
        facts = json.loads(facts_path.read_text(encoding="utf-8"))
        for fact in facts:
            entry_id = f"fact:{source_id}:{uuid.uuid4().hex[:8]}"
            entries.append(PersonaKnowledgeEntry(
                entry_id=entry_id,
                entry_kind=PersonaEntryKind.PERSONA_FACT,
                source_id=source_id,
                text=fact["text"] if "text" in fact else fact.get("fact", ""),
                metadata={
                    "topic": fact.get("topic"),
                    "attribution": fact.get("attribution"),
                    "source_kind": source_kind,
                },
            ))

    # 4. Project Timeline
    if timeline_path and timeline_path.exists():
        events = json.loads(timeline_path.read_text(encoding="utf-8"))
        for event in events:
            entry_id = f"event:{source_id}:{uuid.uuid4().hex[:8]}"
            entries.append(PersonaKnowledgeEntry(
                entry_id=entry_id,
                entry_kind=PersonaEntryKind.TIMELINE_EVENT,
                source_id=source_id,
                text=event["text"],
                metadata={
                    "year": event.get("year"),
                    "topic": event.get("topic"),
                    "source_kind": source_kind,
                },
            ))

    # 5. Project Content/RAW_CHUNK
    if content_path and content_path.exists():
        text = content_path.read_text(encoding="utf-8")
        entry_id = f"raw:{source_id}:{uuid.uuid4().hex[:8]}"
        entries.append(PersonaKnowledgeEntry(
            entry_id=entry_id,
            entry_kind=PersonaEntryKind.RAW_CHUNK,
            source_id=source_id,
            text=text,
            metadata={
                "source_kind": source_kind,
            },
        ))

    # 6. Project Conflicts
    k_paths = get_knowledge_paths(persona_root)
    existing_conflicts = []
    if k_paths["conflicts"].exists():
        existing_conflicts = json.loads(k_paths["conflicts"].read_text(encoding="utf-8"))
    
    # Idempotence: Remove existing conflicts for this source
    existing_conflicts = [c for c in existing_conflicts if c.get("source_id") != source_id]

    if conflicts_path and conflicts_path.exists():
        conflicts = json.loads(conflicts_path.read_text(encoding="utf-8"))
        for conflict in conflicts:
            conflict["conflict_id"] = f"conflict:{uuid.uuid4().hex[:8]}"
            conflict["source_id"] = source_id
            existing_conflicts.append(conflict)
            
    k_paths["conflicts"].write_text(json.dumps(existing_conflicts, indent=2), encoding="utf-8")

    # Write Catalog
    write_catalog(persona_root, sources, entries)
    
    # Rebuild Chunks
    _rebuild_chunks_from_catalog(persona_root, sources, entries)
    
    # Rebuild runtime artifacts
    rebuild_runtime_index(persona_dir=persona_root)
    from asky.plugins.manual_persona_creator.storage import get_persona_paths, touch_updated_at
    touch_updated_at(persona_root / "metadata.toml")


def unproject_source_knowledge(
    *,
    persona_root: Path,
    source_id: str,
):
    """Remove a source and all its entries from persona knowledge."""
    catalog = read_catalog(persona_root)
    if not catalog:
        return

    # 1. Remove Source Record
    sources = [s for s in catalog["sources"] if s.source_id != source_id]
    
    # 2. Remove Entries
    entries = [e for e in catalog["entries"] if e.source_id != source_id]
    
    # 3. Remove Conflicts
    k_paths = get_knowledge_paths(persona_root)
    if k_paths["conflicts"].exists():
        conflicts = json.loads(k_paths["conflicts"].read_text(encoding="utf-8"))
        conflicts = [c for c in conflicts if c.get("source_id") != source_id]
        k_paths["conflicts"].write_text(json.dumps(conflicts, indent=2), encoding="utf-8")

    # Write Catalog
    write_catalog(persona_root, sources, entries)
    
    # Rebuild Chunks and embeddings
    _rebuild_chunks_from_catalog(persona_root, sources, entries)
    
    # Rebuild runtime index
    rebuild_runtime_index(persona_dir=persona_root)
    
    from asky.plugins.manual_persona_creator.storage import touch_updated_at
    touch_updated_at(persona_root / "metadata.toml")


def retract_source_bundle(data_dir: Path, persona_name: str, source_id: str):
    """Retract an approved source bundle back to pending status."""
    paths = get_persona_paths(data_dir, persona_name)
    bundle_paths = ensure_canonical_source_bundle(paths.root_dir, source_id)
    
    if not bundle_paths.metadata_path.exists():
        raise ValueError(f"Source bundle {source_id} not found")
        
    from asky.plugins.manual_persona_creator.storage import (
        read_source_metadata,
        write_source_metadata,
    )
    metadata = read_source_metadata(bundle_paths.metadata_path)
    metadata["review_status"] = PersonaReviewStatus.PENDING
    metadata["updated_at"] = _utc_now_iso()
    write_source_metadata(bundle_paths.metadata_path, metadata)
    
    unproject_source_knowledge(persona_root=paths.root_dir, source_id=source_id)


def reject_source_bundle(data_dir: Path, persona_name: str, source_id: str):
    """Mark a source bundle as rejected."""
    paths = get_persona_paths(data_dir, persona_name)
    bundle_paths = ensure_canonical_source_bundle(paths.root_dir, source_id)
    
    if not bundle_paths.metadata_path.exists():
        raise ValueError(f"Source bundle {source_id} not found")
        
    from asky.plugins.manual_persona_creator.storage import (
        read_source_metadata,
        write_source_metadata,
    )
    metadata = read_source_metadata(bundle_paths.metadata_path)
    metadata["review_status"] = PersonaReviewStatus.REJECTED
    metadata["updated_at"] = _utc_now_iso()
    write_source_metadata(bundle_paths.metadata_path, metadata)
    
    unproject_source_knowledge(persona_root=paths.root_dir, source_id=source_id)



def get_source_report(data_dir: Path, persona_name: str, source_id: str) -> Optional[Dict[str, Any]]:
    """Get ingestion report for a source bundle."""
    paths = get_persona_paths(data_dir, persona_name)
    bundle_paths = get_source_bundle_paths(paths.root_dir, source_id)
    if not bundle_paths.report_path.exists():
        return None
    return json.loads(bundle_paths.report_path.read_text(encoding="utf-8"))


def query_approved_viewpoints(data_dir: Path, persona_name: str, source_id: Optional[str] = None, topic: Optional[str] = None) -> List[PersonaKnowledgeEntry]:
    """Query approved viewpoint entries."""
    paths = get_persona_paths(data_dir, persona_name)
    catalog = read_catalog(paths.root_dir)
    if not catalog:
        return []
    entries = [e for e in catalog["entries"] if e.entry_kind == PersonaEntryKind.VIEWPOINT]
    if source_id:
        entries = [e for e in entries if e.source_id == source_id]
    if topic:
        t_lower = topic.lower()
        entries = [e for e in entries if t_lower in (e.metadata.get("topic") or "").lower()]
    return entries


def query_approved_facts(data_dir: Path, persona_name: str, source_id: Optional[str] = None, topic: Optional[str] = None) -> List[PersonaKnowledgeEntry]:
    """Query approved fact entries."""
    paths = get_persona_paths(data_dir, persona_name)
    catalog = read_catalog(paths.root_dir)
    if not catalog:
        return []
    entries = [e for e in catalog["entries"] if e.entry_kind == PersonaEntryKind.PERSONA_FACT]
    if source_id:
        entries = [e for e in entries if e.source_id == source_id]
    if topic:
        t_lower = topic.lower()
        entries = [e for e in entries if t_lower in (e.metadata.get("topic") or "").lower()]
    return entries


def query_approved_timeline(data_dir: Path, persona_name: str, source_id: Optional[str] = None, topic: Optional[str] = None) -> List[PersonaKnowledgeEntry]:
    """Query approved timeline entries."""
    paths = get_persona_paths(data_dir, persona_name)
    catalog = read_catalog(paths.root_dir)
    if not catalog:
        return []
    entries = [e for e in catalog["entries"] if e.entry_kind == PersonaEntryKind.TIMELINE_EVENT]
    if source_id:
        entries = [e for e in entries if e.source_id == source_id]
    if topic:
        t_lower = topic.lower()
        entries = [e for e in entries if t_lower in (e.metadata.get("topic") or "").lower()]
    return sorted(entries, key=lambda e: e.metadata.get("year") or 0)


def query_approved_conflicts(data_dir: Path, persona_name: str, source_id: Optional[str] = None, topic: Optional[str] = None) -> List[Dict[str, Any]]:
    """Query approved conflict groups."""
    paths = get_persona_paths(data_dir, persona_name)
    k_paths = get_knowledge_paths(paths.root_dir)
    if not k_paths["conflicts"].exists():
        return []
    conflicts = json.loads(k_paths["conflicts"].read_text(encoding="utf-8"))
    if source_id:
        conflicts = [c for c in conflicts if c.get("source_id") == source_id]
    if topic:
        t_lower = topic.lower()
        conflicts = [c for c in conflicts if t_lower in (c.get("topic") or "").lower()]
    return conflicts


def _rebuild_chunks_from_catalog(persona_root: Path, sources: List[PersonaSourceRecord], entries: List[PersonaKnowledgeEntry]):
    """Rebuild chunks.json from catalog for embedding support."""
    chunks = []
    # 1. Existing chunks from catalog
    for i, entry in enumerate(entries):
        if entry.entry_kind in {PersonaEntryKind.RAW_CHUNK, PersonaEntryKind.VIEWPOINT, PersonaEntryKind.PERSONA_FACT, PersonaEntryKind.TIMELINE_EVENT}:
            source = next((s for s in sources if s.source_id == entry.source_id), None)
            source_label = source.label if source else "unknown"
            
            chunks.append({
                "chunk_id": entry.entry_id,
                "chunk_index": i,
                "text": entry.text,
                "source": source_label,
                "title": source_label,
            })
            
    write_chunks(persona_root / "chunks.json", chunks)
    rebuild_embeddings(persona_dir=persona_root, chunks=chunks)


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
