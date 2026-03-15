"""Service adapters for Manual Persona Creator GUI."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from asky.plugins.manual_persona_creator.book_lookup import PreflightResult
from asky.plugins.manual_persona_creator.book_service import (
    create_ingestion_job,
    get_authored_book_report,
    list_authored_books,
    update_ingestion_job_inputs,
)
from asky.plugins.manual_persona_creator.book_types import (
    BookMetadata,
    ExtractionTargets,
)
from asky.plugins.manual_persona_creator.source_service import (
    list_source_bundles_for_persona,
)
from asky.plugins.manual_persona_creator.storage import (
    get_persona_paths,
    list_persona_names,
    read_metadata,
)
from asky.plugins.manual_persona_creator.web_service import (
    get_collection_review_pages,
)
from asky.plugins.manual_persona_creator.storage import list_web_collections


@dataclass(frozen=True)
class PersonaSummary:
    name: str
    description: str
    schema_version: int
    book_count: int
    source_count: int
    web_collection_count: int


def list_personas_summary(data_dir: Path) -> List[PersonaSummary]:
    """List all personas with basic counts."""
    names = list_persona_names(data_dir)
    summaries = []
    for name in names:
        try:
            paths = get_persona_paths(data_dir, name)
            metadata = read_metadata(paths.metadata_path)

            books = list_authored_books(data_dir=data_dir, persona_name=name)
            sources = list_source_bundles_for_persona(
                data_dir=data_dir, persona_name=name
            )
            collections = list_web_collections(paths.root_dir)

            summaries.append(
                PersonaSummary(
                    name=name,
                    description=metadata.get("persona", {}).get("description", ""),
                    schema_version=metadata.get("schema_version", 0),
                    book_count=len(books),
                    source_count=len(sources),
                    web_collection_count=len(collections),
                )
            )
        except Exception:
            continue
    return summaries


def get_persona_detail(data_dir: Path, persona_name: str) -> Dict[str, Any]:
    """Return full detail for one persona."""
    paths = get_persona_paths(data_dir, persona_name)
    if not paths.metadata_path.exists():
        raise ValueError(f"Persona '{persona_name}' not found")

    metadata = read_metadata(paths.metadata_path)
    books = list_authored_books(data_dir=data_dir, persona_name=persona_name)
    sources = list_source_bundles_for_persona(
        data_dir=data_dir, persona_name=persona_name
    )

    approved_sources = [s for s in sources if s.get("review_status") == "approved"]
    pending_sources = [s for s in sources if s.get("review_status") == "pending"]

    collections = []
    for cid in list_web_collections(paths.root_dir):
        collections.append({"collection_id": cid})

    return {
        "name": persona_name,
        "metadata": metadata,
        "books": [asdict(b) for b in books],
        "approved_sources": approved_sources,
        "pending_sources": pending_sources,
        "web_collections": collections,
    }


@dataclass(frozen=True)
class AuthoredBookPreflightDTO:
    """Unified DTO for authored-book preflight results (fresh or resumable)."""

    source_path: str
    source_fingerprint: str
    title: str
    authors: List[str]
    topic_target: int
    viewpoint_target: int
    publication_year: Optional[int] = None
    isbn: Optional[str] = None
    is_duplicate: bool = False
    existing_book_key: Optional[str] = None
    resumable_job_id: Optional[str] = None


def from_preflight_result(result: PreflightResult) -> AuthoredBookPreflightDTO:
    """
    Convert preflight result to a stable GUI-facing DTO.

    For fresh jobs, uses proposed targets and candidates.
    For resumable jobs, uses manifest metadata/targets.
    For no-candidate cases, returns empty values requiring explicit input.
    """
    if result.resumable_manifest:
        manifest = result.resumable_manifest
        return AuthoredBookPreflightDTO(
            source_path=manifest.source_path,
            source_fingerprint=manifest.source_fingerprint,
            title=manifest.metadata.title,
            authors=manifest.metadata.authors,
            publication_year=manifest.metadata.publication_year,
            isbn=manifest.metadata.isbn,
            topic_target=manifest.targets.topic_target,
            viewpoint_target=manifest.targets.viewpoint_target,
            is_duplicate=result.is_duplicate,
            existing_book_key=result.existing_book_key,
            resumable_job_id=result.resumable_job_id,
        )

    if result.candidates:
        cand = result.candidates[0]
        return AuthoredBookPreflightDTO(
            source_path=result.source_path,
            source_fingerprint=result.source_fingerprint,
            title=cand.metadata.title,
            authors=cand.metadata.authors,
            publication_year=cand.metadata.publication_year,
            isbn=cand.metadata.isbn,
            topic_target=result.proposed_targets.topic_target,
            viewpoint_target=result.proposed_targets.viewpoint_target,
            is_duplicate=result.is_duplicate,
            existing_book_key=result.existing_book_key,
            resumable_job_id=result.resumable_job_id,
        )

    return AuthoredBookPreflightDTO(
        source_path=result.source_path,
        source_fingerprint=result.source_fingerprint,
        title="",
        authors=[],
        topic_target=result.proposed_targets.topic_target,
        viewpoint_target=result.proposed_targets.viewpoint_target,
        is_duplicate=result.is_duplicate,
        existing_book_key=result.existing_book_key,
        resumable_job_id=result.resumable_job_id,
    )


def validate_authored_book_input(metadata: BookMetadata, targets: ExtractionTargets) -> List[str]:
    """Validate user input for authored books."""
    errors = []
    if not metadata.title or not metadata.title.strip():
        errors.append("Title cannot be blank.")
    
    valid_authors = [a.strip() for a in metadata.authors if a.strip()]
    if not valid_authors:
        errors.append("At least one author must be provided.")
        
    if targets.topic_target < 1:
        errors.append("Topic target must be at least 1.")
        
    if targets.viewpoint_target < 1:
        errors.append("Viewpoint target must be at least 1.")
        
    return errors


def submit_authored_book(
    data_dir: Path,
    persona_name: str,
    dto: AuthoredBookPreflightDTO,
    metadata: BookMetadata,
    targets: ExtractionTargets,
    mode: str = "ingest",
    expected_book_key: Optional[str] = None,
) -> str:
    """
    Submit authored-book job, handling fresh vs resumable logic.

    For resumable jobs, updates the existing job instead of creating a new one.
    For duplicates, raises an appropriate error.

    Returns the final job_id (resumable or newly created).
    """
    if dto.resumable_job_id:
        update_ingestion_job_inputs(
            data_dir=data_dir,
            persona_name=persona_name,
            job_id=dto.resumable_job_id,
            metadata=metadata,
            targets=targets,
            mode=mode,
        )
        return dto.resumable_job_id

    return create_ingestion_job(
        data_dir=data_dir,
        persona_name=persona_name,
        source_path=dto.source_path,
        source_fingerprint=dto.source_fingerprint,
        metadata=metadata,
        targets=targets,
        mode=mode,
        expected_book_key=expected_book_key,
    )
