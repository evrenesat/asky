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


@dataclass
class AskyChatResult:
    """Result payload returned by `AskyClient.chat()`."""

    final_answer: str
    query_summary: str
    answer_summary: str
    messages: List[Dict[str, Any]]
    model_alias: str
    session_id: Optional[str] = None
