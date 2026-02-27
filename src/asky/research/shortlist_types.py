"""Shared types for source shortlist internals."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

SearchExecutor = Callable[[Dict[str, Any]], Dict[str, Any]]
FetchExecutor = Callable[[str], Dict[str, Any]]
SeedLinkExtractor = Callable[[str], Dict[str, Any]]
StatusCallback = Callable[[str], None]
TraceCallback = Callable[[Dict[str, Any]], None]
ShortlistMetrics = Dict[str, Any]


@dataclass
class CandidateRecord:
    """Candidate source record used throughout the shortlist pipeline."""

    url: str
    source_type: str
    requested_url: str = ""
    normalized_url: str = ""
    hostname: str = ""
    title: str = ""
    text: str = ""
    snippet: str = ""
    fetched_content: str = ""
    fetch_warning: str = ""
    fetch_error: str = ""
    final_url: str = ""
    date: Optional[str] = None
    search_snippet: str = ""
    path_tokens: str = ""
    semantic_score: float = 0.0
    overlap_ratio: float = 0.0
    bonus_score: float = 0.0
    penalty_score: float = 0.0
    final_score: float = 0.0
    why_selected: List[str] = field(default_factory=list)


@dataclass
class CorpusContext:
    """Corpus metadata extracted from preloaded local documents."""

    titles: List[str]
    keyphrases: List[str]
    lead_texts: Dict[str, str]
    source_handles: List[str]
    cache_ids: List[int]
