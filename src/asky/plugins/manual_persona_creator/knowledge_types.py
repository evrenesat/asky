"""Canonical knowledge catalog types for persona packages."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Dict, List, Optional


class PersonaSourceClass(StrEnum):
    MANUAL_SOURCE = "manual_source"
    AUTHORED_BOOK = "authored_book"
    DIRECT_INTERVIEW = "direct_interview"
    BIOGRAPHY_OR_AUTOBIOGRAPHY = "biography_or_autobiography"
    THIRD_PARTY_COMMENTARY = "third_party_commentary"
    SCRAPED_WEB = "scraped_web"
    AUDIO_VIDEO_TRANSCRIPT = "audio_video_transcript"


class PersonaTrustClass(StrEnum):
    AUTHORED_PRIMARY = "authored_primary"
    USER_SUPPLIED_UNREVIEWED = "user_supplied_unreviewed"
    MIXED_ATTRIBUTION = "mixed_attribution"
    THIRD_PARTY_SECONDARY = "third_party_secondary"
    UNREVIEWED_WEB = "unreviewed_web"
    TRANSCRIPT_UNREVIEWED = "transcript_unreviewed"


class PersonaEntryKind(StrEnum):
    RAW_CHUNK = "raw_chunk"
    VIEWPOINT = "viewpoint"
    PERSONA_FACT = "persona_fact"
    EVIDENCE_EXCERPT = "evidence_excerpt"


class PersonaGroundingClass(StrEnum):
    DIRECT_EVIDENCE = "direct_evidence"
    SUPPORTED_PATTERN = "supported_pattern"
    BOUNDED_INFERENCE = "bounded_inference"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True)
class PersonaSourceRecord:
    """Canonical record for a knowledge source."""

    source_id: str
    source_class: PersonaSourceClass
    trust_class: PersonaTrustClass
    label: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    content_fingerprint: Optional[str] = None


@dataclass(frozen=True)
class PersonaKnowledgeEntry:
    """Canonical entry in the knowledge catalog."""

    entry_id: str
    entry_kind: PersonaEntryKind
    source_id: str
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    parent_entry_id: Optional[str] = None
