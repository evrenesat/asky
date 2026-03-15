from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class WebCollectionMode(str, Enum):
    SEED_DOMAIN = "seed_domain"
    BROAD_EXPAND = "broad_expand"


class WebCollectionInputMode(str, Enum):
    SEED_URLS = "seed_urls"
    SEARCH_QUERY = "search_query"


class WebCollectionStatus(str, Enum):
    COLLECTING = "collecting"
    REVIEW_READY = "review_ready"
    COMPLETED = "completed"
    EXHAUSTED = "exhausted"
    FAILED = "failed"


class WebPageStatus(str, Enum):
    REVIEW_READY = "review_ready"
    APPROVED = "approved"
    REJECTED = "rejected"
    DUPLICATE_FILTERED = "duplicate_filtered"
    FETCH_FAILED = "fetch_failed"


class WebPageClassification(str, Enum):
    AUTHORED_BY_PERSONA = "authored_by_persona"
    ABOUT_PERSONA = "about_persona"
    UNCERTAIN = "uncertain"
    IRRELEVANT = "irrelevant"


@dataclass(frozen=True)
class WebPagePreview:
    """Preview metadata for a scraped page used during review."""
    short_summary: str
    candidate_viewpoints: List[Dict[str, Any]] = field(default_factory=list)
    candidate_facts: List[Dict[str, Any]] = field(default_factory=list)
    candidate_timeline_events: List[Dict[str, Any]] = field(default_factory=list)
    conflict_candidates: List[Dict[str, Any]] = field(default_factory=list)
    recommended_classification: WebPageClassification = WebPageClassification.UNCERTAIN
    recommended_trust: str = "uncertain"


@dataclass(frozen=True)
class RetrievalProvenance:
    """Provenance for a single page fetch attempt."""
    provider: str  # e.g. "default", "playwright"
    source: str    # e.g. "httpx", "chromium"
    page_type: str = "html"
    warning: Optional[str] = None
    error: Optional[str] = None
    fallback_reason: Optional[str] = None
    trace_events: List[Dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class DuplicateMetadata:
    """Metadata about why a page was filtered as a duplicate."""
    reason: str  # e.g. "exact_url", "normalized_url", "content_fingerprint", "embedding_similarity"
    matched_page_id: Optional[str] = None
    matched_url: Optional[str] = None
    similarity_score: Optional[float] = None


@dataclass(frozen=True)
class WebPageReport:
    """Detailed report for a scraped page, including provenance and outcome."""
    page_id: str
    status: WebPageStatus
    requested_url: str
    final_url: str
    normalized_final_url: str
    title: str
    promoted_source_id: Optional[str] = None
    retrieval: Optional[RetrievalProvenance] = None
    duplicate_info: Optional[DuplicateMetadata] = None
    failure_reason: Optional[str] = None
    discovery_provenance: Optional[str] = None  # e.g. "seed", "extracted_link", "search_result"
    content_fingerprint: str = ""
    created_at: str = ""


@dataclass(frozen=True)
class WebPageManifest:
    """Durable manifest for a single scraped page (page.toml)."""
    page_id: str
    status: WebPageStatus
    requested_url: str
    final_url: str
    normalized_final_url: str
    title: str
    discovered_from_url: Optional[str] = None
    query_mode_marker: Optional[str] = None
    content_fingerprint: str = ""
    classification: WebPageClassification = WebPageClassification.UNCERTAIN
    approved_as_trust: Optional[str] = None  # e.g. authored_primary, third_party_secondary
    similarity_metadata: Dict[str, Any] = field(default_factory=dict)
    promoted_source_id: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""


@dataclass
class WebFrontierState:
    """State of the web collection crawler (frontier.json)."""
    queue: List[str] = field(default_factory=list)
    seen_candidate_urls: List[str] = field(default_factory=list)
    fetched_candidate_urls: List[str] = field(default_factory=list)
    raw_unique_fetch_count: int = 0
    overcollect_cap: int = 0


@dataclass(frozen=True)
class WebCollectionManifest:
    """Durable manifest for a web collection (collection.toml)."""
    collection_id: str
    persona_name: str
    mode: WebCollectionMode
    input_mode: WebCollectionInputMode
    status: WebCollectionStatus
    target_results: int
    seed_inputs: List[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    error_message: Optional[str] = None
