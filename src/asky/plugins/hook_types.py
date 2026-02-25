"""Plugin hook constants and payload contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set

if TYPE_CHECKING:
    from asky.daemon.tray_protocol import TrayPluginEntry

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
POST_TURN_RENDER = "POST_TURN_RENDER"
DAEMON_SERVER_REGISTER = "DAEMON_SERVER_REGISTER"
DAEMON_TRANSPORT_REGISTER = "DAEMON_TRANSPORT_REGISTER"
TRAY_MENU_REGISTER = "TRAY_MENU_REGISTER"

CONFIG_LOADED = "CONFIG_LOADED"
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
    POST_TURN_RENDER,
    DAEMON_SERVER_REGISTER,
    DAEMON_TRANSPORT_REGISTER,
    TRAY_MENU_REGISTER,
}

DEFERRED_HOOK_NAMES = {
    CONFIG_LOADED,
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
class PostTurnRenderContext:
    """Payload fired after the final answer has been rendered to the CLI.

    ``cli_args`` carries the argparse Namespace so plugins can read
    CLI-only flags (e.g. ``push_data_endpoint``, ``mail_recipients``)
    that are not part of ``AskyTurnRequest``.
    """

    final_answer: str
    request: Any
    result: Any
    cli_args: Any = None


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


@dataclass
class DaemonTransportSpec:
    """Transport contract for the primary daemon communication channel."""

    name: str
    run: Callable[[], None]
    stop: Callable[[], None]


@dataclass
class DaemonTransportRegisterContext:
    """Mutable payload for daemon transport registration.

    Exactly one transport must be appended. The daemon runner raises
    DaemonUserError when zero or more than one transport is registered.
    The double_verbose flag is forwarded from the CLI invocation so
    transport plugins can honour it without an out-of-band channel.
    """

    double_verbose: bool = False
    transports: List[DaemonTransportSpec] = field(default_factory=list)


@dataclass
class TrayMenuRegisterContext:
    """Mutable payload for tray menu registration.

    Plugins append ``TrayPluginEntry`` items to ``status_entries`` (read-only
    informational rows) or ``action_entries`` (clickable rows).  The service
    callbacks let plugins drive the daemon lifecycle without importing
    ``TrayController`` directly.
    """

    status_entries: "List[TrayPluginEntry]"
    action_entries: "List[TrayPluginEntry]"
    start_service: Callable[[], None]
    stop_service: Callable[[], None]
    is_service_running: Callable[[], bool]
    on_error: Callable[[str], None]
