"""Plugin hook constants and payload contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

TOOL_REGISTRY_BUILD = "TOOL_REGISTRY_BUILD"
SESSION_RESOLVED = "SESSION_RESOLVED"
PRE_PRELOAD = "PRE_PRELOAD"
POST_PRELOAD = "POST_PRELOAD"
SYSTEM_PROMPT_EXTEND = "SYSTEM_PROMPT_EXTEND"
PRE_LLM_CALL = "PRE_LLM_CALL"
POST_LLM_RESPONSE = "POST_LLM_RESPONSE"
PRE_TOOL_EXECUTE = "PRE_TOOL_EXECUTE"
POST_TOOL_EXECUTE = "POST_TOOL_EXECUTE"
TURN_COMPLETED = "TURN_COMPLETED"
DAEMON_SERVER_REGISTER = "DAEMON_SERVER_REGISTER"

CONFIG_LOADED = "CONFIG_LOADED"
POST_TURN_RENDER = "POST_TURN_RENDER"
SESSION_END = "SESSION_END"

SUPPORTED_HOOK_NAMES = {
    TOOL_REGISTRY_BUILD,
    SESSION_RESOLVED,
    PRE_PRELOAD,
    POST_PRELOAD,
    SYSTEM_PROMPT_EXTEND,
    PRE_LLM_CALL,
    POST_LLM_RESPONSE,
    PRE_TOOL_EXECUTE,
    POST_TOOL_EXECUTE,
    TURN_COMPLETED,
    DAEMON_SERVER_REGISTER,
}

DEFERRED_HOOK_NAMES = {
    CONFIG_LOADED,
    POST_TURN_RENDER,
    SESSION_END,
}


@dataclass
class ToolRegistryBuildContext:
    """Mutable payload for tool-registry build hooks."""

    mode: str
    registry: Any
    disabled_tools: Set[str]


@dataclass
class SessionResolvedContext:
    """Mutable payload for session-resolution hooks."""

    request: Any
    session_manager: Any
    session_resolution: Any


@dataclass
class PrePreloadContext:
    """Mutable payload before preload pipeline execution."""

    request: Any
    query_text: str
    research_mode: bool
    research_source_mode: Optional[str]
    local_corpus_paths: Optional[List[str]]
    preload_local_sources: bool
    preload_shortlist: bool
    shortlist_override: Optional[str]
    additional_source_context: Optional[str]


@dataclass
class PostPreloadContext:
    """Mutable payload after preload pipeline execution."""

    request: Any
    preload: Any
    query_text: str
    research_mode: bool
    research_source_mode: Optional[str]


@dataclass
class PreLLMCallContext:
    """Mutable payload before each LLM call."""

    turn: int
    messages: List[Dict[str, Any]]
    use_tools: bool
    tool_schemas: List[Dict[str, Any]]


@dataclass
class PostLLMResponseContext:
    """Mutable payload after an LLM response is received."""

    turn: int
    message: Dict[str, Any]
    calls: List[Dict[str, Any]]
    messages: List[Dict[str, Any]]


@dataclass
class PreToolExecuteContext:
    """Mutable payload before a tool executor is called."""

    call: Dict[str, Any]
    tool_name: str
    arguments: Dict[str, Any]
    summarize: bool
    short_circuit_result: Optional[Dict[str, Any]] = None


@dataclass
class PostToolExecuteContext:
    """Mutable payload after a tool executor returns."""

    call: Dict[str, Any]
    tool_name: str
    arguments: Dict[str, Any]
    summarize: bool
    result: Dict[str, Any]
    elapsed_ms: float


@dataclass
class TurnCompletedContext:
    """Mutable payload after turn completion."""

    request: Any
    result: Any


@dataclass
class DaemonServerSpec:
    """Server registration contract for daemon plugin servers."""

    name: str
    start: Callable[[], None]
    stop: Optional[Callable[[], None]] = None
    health_check: Optional[Callable[[], Any]] = None


@dataclass
class DaemonServerRegisterContext:
    """Mutable payload for daemon server registration hooks."""

    service: Any
    servers: List[DaemonServerSpec] = field(default_factory=list)
