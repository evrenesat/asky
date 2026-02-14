"""Typed request/response primitives for programmatic asky usage."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass(frozen=True)
class AskyConfig:
    """Runtime settings for an `AskyClient` instance."""

    model_alias: str
    summarize: bool = False
    verbose: bool = False
    open_browser: bool = False
    research_mode: bool = False
    disabled_tools: Set[str] = field(default_factory=set)
    model_parameters_override: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AskyChatResult:
    """Result payload returned by `AskyClient.chat()`."""

    final_answer: str
    query_summary: str
    answer_summary: str
    messages: List[Dict[str, Any]]
    model_alias: str
    session_id: Optional[str] = None


@dataclass(frozen=True)
class AskyTurnRequest:
    """High-level request for a full orchestrated chat turn."""

    query_text: str
    continue_ids: Optional[str] = None
    summarize_context: bool = False
    sticky_session_name: Optional[str] = None
    resume_session_term: Optional[str] = None
    shell_session_id: Optional[int] = None
    lean: bool = False
    preload_local_sources: bool = True
    preload_shortlist: bool = True
    additional_source_context: Optional[str] = None
    local_corpus_paths: Optional[List[str]] = None
    save_history: bool = True


@dataclass
class ContextResolution:
    """Resolved context payload from history selector processing."""

    context_str: str = ""
    resolved_ids: List[int] = field(default_factory=list)


@dataclass
class SessionResolution:
    """Resolved session state for a request."""

    session_id: Optional[int] = None
    event: Optional[str] = None
    notices: List[str] = field(default_factory=list)
    halt_reason: Optional[str] = None
    matched_sessions: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class PreloadResolution:
    """Resolved local-ingestion/shortlist preloaded corpus metadata."""

    local_context: Optional[str] = None
    local_payload: Dict[str, Any] = field(default_factory=dict)
    local_elapsed_ms: float = 0.0
    shortlist_context: Optional[str] = None
    shortlist_payload: Dict[str, Any] = field(default_factory=dict)
    shortlist_stats: Dict[str, Any] = field(default_factory=dict)
    shortlist_elapsed_ms: float = 0.0
    shortlist_enabled: bool = False
    shortlist_reason: str = ""
    combined_context: Optional[str] = None


@dataclass
class AskyTurnResult(AskyChatResult):
    """Extended result for fully orchestrated turn execution."""

    halted: bool = False
    halt_reason: Optional[str] = None
    notices: List[str] = field(default_factory=list)
    context: ContextResolution = field(default_factory=ContextResolution)
    session: SessionResolution = field(default_factory=SessionResolution)
    preload: PreloadResolution = field(default_factory=PreloadResolution)
