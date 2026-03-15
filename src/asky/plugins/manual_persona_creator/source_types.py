"""Typed milestone-3 source models for persona packages."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Dict, List, Optional


class PersonaSourceKind(StrEnum):
    """Exact public kinds for milestone-3 source ingestion."""

    BIOGRAPHY = "biography"
    AUTOBIOGRAPHY = "autobiography"
    INTERVIEW = "interview"
    ARTICLE = "article"
    ESSAY = "essay"
    SPEECH = "speech"
    NOTES = "notes"
    POSTS = "posts"
    WEB_PAGE = "web_page"


class PersonaReviewStatus(StrEnum):
    """Exact states for milestone-3 review flow."""

    APPROVED = "approved"
    PENDING = "pending"
    REJECTED = "rejected"


@dataclass(frozen=True)
class PersonaSourceBundleMetadata:
    """Per-source bundle metadata record."""

    source_id: str
    kind: PersonaSourceKind
    label: str
    review_status: PersonaReviewStatus
    created_at: str
    updated_at: str
    source_class: str
    trust_class: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    bundle_members: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class PersonaFactRecord:
    """Fact record extracted from a milestone-3 source."""

    fact_id: str
    text: str
    topic: Optional[str] = None
    attribution: Optional[str] = None
    evidence_excerpt: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PersonaTimelineEventRecord:
    """Timeline-event record extracted from a milestone-3 source."""

    event_id: str
    text: str
    year: Optional[int] = None
    date_label: Optional[str] = None
    topic: Optional[str] = None
    attribution: Optional[str] = None
    evidence_excerpt: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PersonaConflictGroupRecord:
    """Conflict-group record for preserving contradictions."""

    conflict_id: str
    topic: str
    description: str
    opposing_claims: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PersonaSourceReportRecord:
    """Per-source ingestion report record."""

    source_id: str
    kind: PersonaSourceKind
    status: str
    warnings: List[str] = field(default_factory=list)
    stage_timings: Dict[str, float] = field(default_factory=dict)
    extracted_counts: Dict[str, int] = field(default_factory=dict)
    conflict_summary: List[str] = field(default_factory=list)
    review_timestamp: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PersonaSourceIngestionJobManifest:
    """Source-ingestion job manifest for resumable jobs."""

    job_id: str
    persona_name: str
    kind: PersonaSourceKind
    source_path: str
    status: str
    created_at: str
    updated_at: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    stages: List[Dict[str, Any]] = field(default_factory=list)
