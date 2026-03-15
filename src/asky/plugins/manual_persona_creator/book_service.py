"""Service layer for authored-book operations."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from asky.plugins.manual_persona_creator.book_lookup import run_preflight
from asky.plugins.manual_persona_creator.book_types import (
    AuthoredBookReport,
    BookMetadata,
    BookSummaryRow,
    ExtractionTargets,
    IngestionIdentityStatus,
    IngestionJobManifest,
    PreflightResult,
    ViewpointEntry,
    ViewpointEvidence,
)
from asky.plugins.manual_persona_creator.storage import (
    get_book_key,
    get_book_paths,
    get_job_paths,
    get_persona_paths,
    list_books,
    read_book_metadata,
    read_job_manifest,
    write_job_manifest,
)

logger = logging.getLogger(__name__)


def get_ingestion_identity_status(
    *,
    data_dir: Path,
    persona_name: str,
    metadata: BookMetadata,
    expected_book_key: Optional[str] = None,
    mode: str = "ingest",  # ingest or reingest
) -> IngestionIdentityStatus:
    """Check if the proposed book identity is available or already exists."""
    paths = get_persona_paths(data_dir, persona_name)
    book_key = get_book_key(
        title=metadata.title,
        publication_year=metadata.publication_year,
        isbn=metadata.isbn
    )
    
    book_paths = get_book_paths(paths.root_dir, book_key)
    exists = book_paths.metadata_path.exists()

    if mode == "ingest":
        if exists:
            return IngestionIdentityStatus.DUPLICATE_COMPLETED
        return IngestionIdentityStatus.AVAILABLE
    
    if mode == "reingest":
        if expected_book_key and book_key != expected_book_key:
            return IngestionIdentityStatus.REPLACEMENT_FORBIDDEN
        if exists:
            return IngestionIdentityStatus.REPLACEMENT_ALLOWED
        return IngestionIdentityStatus.AVAILABLE

    return IngestionIdentityStatus.AVAILABLE


def prepare_ingestion_preflight(
    *,
    data_dir: Path,
    persona_name: str,
    source_path: str,
) -> PreflightResult:
    """Orchestrate preflight metadata lookup and analysis."""
    return run_preflight(
        persona_name=persona_name,
        source_path=source_path,
        data_dir=data_dir
    )


def create_ingestion_job(
    *,
    data_dir: Path,
    persona_name: str,
    source_path: str,
    source_fingerprint: str,
    metadata: BookMetadata,
    targets: ExtractionTargets,
    mode: str = "ingest",
    expected_book_key: Optional[str] = None,
) -> str:
    """
    Create a new ingestion job after enforcing identity guards.
    Returns the job_id.
    """
    status = get_ingestion_identity_status(
        data_dir=data_dir,
        persona_name=persona_name,
        metadata=metadata,
        expected_book_key=expected_book_key,
        mode=mode
    )

    if mode == "ingest" and status == IngestionIdentityStatus.DUPLICATE_COMPLETED:
        raise ValueError(f"Book already exists: {metadata.title}. Use reingest-book to replace.")
    
    if mode == "reingest" and status == IngestionIdentityStatus.REPLACEMENT_FORBIDDEN:
        raise ValueError(f"Identity mismatch: {metadata.title} does not match {expected_book_key}.")

    job_id = str(uuid.uuid4())
    paths = get_persona_paths(data_dir, persona_name)
    job_paths = get_job_paths(paths.root_dir, job_id)
    job_paths.job_dir.mkdir(parents=True, exist_ok=True)

    manifest = IngestionJobManifest(
        job_id=job_id,
        persona_name=persona_name,
        source_path=source_path,
        source_fingerprint=source_fingerprint,
        status="planned",
        mode=mode,
        created_at=_utc_now_iso(),
        updated_at=_utc_now_iso(),
        metadata=metadata,
        targets=targets,
    )

    data = {
        "job_id": manifest.job_id,
        "persona_name": manifest.persona_name,
        "source_path": manifest.source_path,
        "source_fingerprint": manifest.source_fingerprint,
        "status": manifest.status,
        "mode": manifest.mode,
        "created_at": manifest.created_at,
        "updated_at": manifest.updated_at,
        "metadata": asdict(manifest.metadata),
        "targets": asdict(manifest.targets),
        "stages_completed": [],
        "stage_timings": {},
        "warnings": [],
    }
    write_job_manifest(job_paths.manifest_path, data)
    return job_id


def update_ingestion_job_inputs(
    *,
    data_dir: Path,
    persona_name: str,
    job_id: str,
    metadata: BookMetadata,
    targets: ExtractionTargets,
    mode: Optional[str] = None,
) -> None:
    """Persist edited metadata and targets back into an existing job manifest."""
    paths = get_persona_paths(data_dir, persona_name)
    job_paths = get_job_paths(paths.root_dir, job_id)
    manifest = read_job_manifest(job_paths.manifest_path)
    manifest["metadata"] = asdict(metadata)
    manifest["targets"] = asdict(targets)
    if mode is not None:
        manifest["mode"] = mode
    manifest["updated_at"] = _utc_now_iso()
    write_job_manifest(job_paths.manifest_path, manifest)


def list_authored_books(
    *,
    data_dir: Path,
    persona_name: str,
) -> List[BookSummaryRow]:
    """List all completed authored books for a persona."""
    paths = get_persona_paths(data_dir, persona_name)
    book_keys = list_books(paths.root_dir)
    
    rows = []
    for key in book_keys:
        book_paths = get_book_paths(paths.root_dir, key)
        try:
            metadata_dict = read_book_metadata(book_paths.metadata_path)
            metadata = BookMetadata(**metadata_dict)
            
            # Read report for counts and timestamp
            viewpoint_count = 0
            last_ingested_at = "unknown"
            if book_paths.report_path.exists():
                report_data = json.loads(book_paths.report_path.read_text(encoding="utf-8"))
                viewpoint_count = report_data.get("actual_viewpoints", 0)
                last_ingested_at = report_data.get("completed_at", "unknown")
            elif book_paths.viewpoints_path.exists():
                # Fallback to viewpoints file if report missing
                vps = json.loads(book_paths.viewpoints_path.read_text(encoding="utf-8"))
                viewpoint_count = len(vps)

            rows.append(BookSummaryRow(
                book_key=key,
                title=metadata.title,
                authors=metadata.authors,
                publication_year=metadata.publication_year,
                isbn=metadata.isbn,
                viewpoint_count=viewpoint_count,
                last_ingested_at=last_ingested_at,
            ))
        except Exception as e:
            logger.warning("Failed to load metadata for book %s: %s", key, e)
            continue
            
    return sorted(rows, key=lambda x: x.last_ingested_at, reverse=True)


def get_authored_book_report(
    *,
    data_dir: Path,
    persona_name: str,
    book_key: str,
) -> AuthoredBookReport:
    """Load the full report for an authored book."""
    paths = get_persona_paths(data_dir, persona_name)
    book_paths = get_book_paths(paths.root_dir, book_key)
    
    if not book_paths.report_path.exists():
        raise FileNotFoundError(f"Report not found for book: {book_key}")
        
    data = json.loads(book_paths.report_path.read_text(encoding="utf-8"))
    
    # Map back to dataclasses
    metadata = BookMetadata(**data["metadata"])
    targets = ExtractionTargets(**data["targets"])
    
    return AuthoredBookReport(
        book_key=data["book_key"],
        metadata=metadata,
        targets=targets,
        actual_topics=data["actual_topics"],
        actual_viewpoints=data["actual_viewpoints"],
        started_at=data["started_at"],
        completed_at=data["completed_at"],
        duration_seconds=data["duration_seconds"],
        warnings=data.get("warnings", []),
        stage_timings=data.get("stage_timings", {}),
    )


def query_authored_viewpoints(
    *,
    data_dir: Path,
    persona_name: str,
    book_key: Optional[str] = None,
    topic_query: Optional[str] = None,
    limit: int = 20,
) -> List[ViewpointEntry]:
    """Query structured viewpoints across one or all books."""
    paths = get_persona_paths(data_dir, persona_name)
    
    if book_key:
        keys = [book_key]
    else:
        keys = list_books(paths.root_dir)
        
    all_viewpoints = []
    for key in keys:
        book_paths = get_book_paths(paths.root_dir, key)
        if not book_paths.viewpoints_path.exists():
            continue
            
        data = json.loads(book_paths.viewpoints_path.read_text(encoding="utf-8"))
        for v_data in data:
            if topic_query and topic_query.lower() not in v_data.get("topic", "").lower():
                continue
            evidence = [ViewpointEvidence(**e) for e in v_data.get("evidence", [])]
            all_viewpoints.append(ViewpointEntry(
                entry_id=v_data["entry_id"],
                topic=v_data["topic"],
                claim=v_data["claim"],
                stance_label=v_data["stance_label"],
                confidence=v_data["confidence"],
                book_key=v_data["book_key"],
                book_title=v_data["book_title"],
                publication_year=v_data.get("publication_year"),
                isbn=v_data.get("isbn"),
                evidence=evidence,
            ))
            
    all_viewpoints.sort(key=lambda x: (x.topic, -x.confidence))
    return all_viewpoints[:limit]


def run_ingestion_job(
    *,
    data_dir: Path,
    persona_name: str,
    job_id: str,
) -> None:
    """Delegate to the BookIngestionJob runner."""
    from asky.plugins.manual_persona_creator.book_ingestion import BookIngestionJob
    job = BookIngestionJob(
        data_dir=data_dir,
        persona_name=persona_name,
        job_id=job_id,
    )
    job.run()


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
