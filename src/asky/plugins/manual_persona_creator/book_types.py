"""Type definitions for authored-book ingestion."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class IngestionIdentityStatus(Enum):
    """Result of an identity guard check."""

    AVAILABLE = "available"
    DUPLICATE_COMPLETED = "duplicate_completed"
    DUPLICATE_IN_PROGRESS = "duplicate_in_progress"
    REPLACEMENT_ALLOWED = "replacement_allowed"
    REPLACEMENT_FORBIDDEN = "replacement_forbidden"


@dataclass(frozen=True)
class BookMetadata:
    """Confirmed book identity and publication metadata."""

    title: str
    authors: List[str]
    publication_year: Optional[int] = None
    isbn: Optional[str] = None
    publisher: Optional[str] = None
    language: str = "en"
    description: Optional[str] = None


@dataclass(frozen=True)
class MetadataCandidate:
    """A ranked metadata candidate from lookup services."""

    metadata: BookMetadata
    confidence: float  # 0.0 to 1.0
    is_ambiguous: bool = False


@dataclass(frozen=True)
class ExtractionTargets:
    """User-confirmed or system-proposed extraction goals."""

    topic_target: int
    viewpoint_target: int


@dataclass(frozen=True)
class IngestionJobManifest:
    """Persistent state for an in-progress or terminal ingestion job."""

    job_id: str
    persona_name: str
    source_path: str
    source_fingerprint: str
    status: str  # planned, running, failed, completed, cancelled
    mode: str  # ingest or reingest
    created_at: str
    updated_at: str
    metadata: BookMetadata
    targets: ExtractionTargets
    stages_completed: List[str] = field(default_factory=list)
    stage_timings: Dict[str, float] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass(frozen=True)
class ViewpointEvidence:
    """Supporting evidence for a viewpoint claim."""

    excerpt: str
    section_ref: str


@dataclass(frozen=True)
class ViewpointEntry:
    """A structured viewpoint extracted from an authored book."""

    entry_id: str
    topic: str
    claim: str
    stance_label: str  # supports, opposes, mixed, descriptive, unclear
    confidence: float
    book_key: str
    book_title: str
    publication_year: Optional[int]
    isbn: Optional[str]
    evidence: List[ViewpointEvidence]


@dataclass(frozen=True)
class AuthoredBookReport:
    """Summary of the ingestion process and results."""

    book_key: str
    metadata: BookMetadata
    targets: ExtractionTargets
    actual_topics: int
    actual_viewpoints: int
    started_at: str
    completed_at: str
    duration_seconds: float
    warnings: List[str] = field(default_factory=list)
    stage_timings: Dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class BookSummaryRow:
    """Summary of an authored book for list views."""

    book_key: str
    title: str
    authors: List[str]
    publication_year: Optional[int]
    isbn: Optional[str]
    viewpoint_count: int
    last_ingested_at: str


@dataclass(frozen=True)
class PreflightResult:
    """Result of the preflight metadata lookup and analysis."""

    source_path: str
    source_fingerprint: str
    candidates: List[MetadataCandidate]
    proposed_targets: ExtractionTargets
    stats: Dict[str, Any]
    is_duplicate: bool = False
    existing_book_key: Optional[str] = None
    resumable_job_id: Optional[str] = None
    resumable_manifest: Optional[IngestionJobManifest] = None
