# Hook Reference

All hook constants are in `asky.plugins.hook_types`. Import them with:

```python
from asky.plugins.hook_types import (
    TOOL_REGISTRY_BUILD, ToolRegistryBuildContext,
    POST_TURN_RENDER, PostTurnRenderContext,
    # etc.
)
```

Hook callbacks mutate the payload in-place (unless noted). Exceptions inside a callback are
logged and isolated — remaining callbacks for the same hook still run.

**Ordering**: `(priority ascending, plugin_name alphabetical, registration_index)`. Default
priority is 100; lower numbers run first.

---

## TOOL_REGISTRY_BUILD

Fired before each LLM call. Register tools the LLM can invoke.

```python
@dataclass
class ToolRegistryBuildContext:
    mode: str            # "cli" or "daemon"
    registry: Any        # call registry.register(name, schema_dict, executor_fn)
    disabled_tools: Set[str]  # skip if tool name is here
```

Pattern:

```python
def _on_tool_registry_build(self, payload: ToolRegistryBuildContext) -> None:
    if "download_video" in payload.disabled_tools:
        return
    payload.registry.register("download_video", SCHEMA, self._execute)
```

---

## SYSTEM_PROMPT_EXTEND

Chain hook — return a string to append to the system prompt. Return `""` to add nothing.

```python
def _on_system_prompt_extend(self, current_prompt: str) -> str:
    return "You have access to a video downloader tool."
```

---

## POST_TURN_RENDER

Fired after the final answer is rendered to CLI. Use for output delivery actions.

```python
@dataclass
class PostTurnRenderContext:
    final_answer: str    # the completed answer text
    request: Any         # AskyTurnRequest
    result: Any          # turn result
    cli_args: Any        # argparse Namespace — read CLI flags here
    answer_title: str    # extracted markdown heading or query text fallback
```

Pattern:

```python
def _on_post_turn_render(self, ctx: PostTurnRenderContext) -> None:
    flag_value = getattr(ctx.cli_args, "my_flag", None)
    if not ctx.final_answer or not flag_value:
        return
    # do delivery
```

---

## FETCH_URL_OVERRIDE

Intercept URL fetches. Set `ctx.result` to handle the request; leave it `None` to pass through.

```python
@dataclass
class FetchURLContext:
    url: str
    output_format: str
    include_links: bool
    max_links: Optional[int]
    trace_callback: Optional[Any]
    trace_context: Optional[Dict[str, Any]]
    result: Optional[Dict[str, Any]] = None  # set this to intercept
```

Result dict shape (mirrors default pipeline output):

```python
ctx.result = {
    "error": None,          # or error string
    "requested_url": ctx.url,
    "final_url": final_url,
    "content": extracted_text,
    "title": page_title,
    "links": [],            # optional
}
```

---

## PRE_PRELOAD / POST_PRELOAD

Modify the retrieval pipeline before/after execution.

```python
@dataclass
class PrePreloadContext:
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
    request: Any
    preload: Any        # preload result object
    query_text: str
    research_mode: bool
    research_source_mode: Optional[str]
```

---

## SESSION_RESOLVED

Fired after session context is determined.

```python
@dataclass
class SessionResolvedContext:
    request: Any
    session_manager: Any
    session_resolution: Any
```

---

## PRE_LLM_CALL / POST_LLM_RESPONSE

Fired around each LLM API call (may fire multiple times per turn in tool-use loops).

```python
@dataclass
class PreLLMCallContext:
    turn: int
    messages: List[Dict[str, Any]]    # mutable
    use_tools: bool
    tool_schemas: List[Dict[str, Any]]

@dataclass
class PostLLMResponseContext:
    turn: int
    message: Dict[str, Any]
    calls: List[Dict[str, Any]]       # tool call requests
    messages: List[Dict[str, Any]]
```

---

## PRE_TOOL_EXECUTE / POST_TOOL_EXECUTE

Fired around each tool call execution.

```python
@dataclass
class PreToolExecuteContext:
    call: Dict[str, Any]
    tool_name: str
    arguments: Dict[str, Any]
    summarize: bool
    short_circuit_result: Optional[Dict[str, Any]] = None  # set to skip execution

@dataclass
class PostToolExecuteContext:
    call: Dict[str, Any]
    tool_name: str
    arguments: Dict[str, Any]
    summarize: bool
    result: Dict[str, Any]
    elapsed_ms: float
```

---

## TURN_COMPLETED

Fired once after the full turn (including all tool loops) finishes.

```python
@dataclass
class TurnCompletedContext:
    request: Any
    result: Any
```

---

## DAEMON_SERVER_REGISTER

Register background sidecar servers (e.g. HTTP server, websocket).

```python
@dataclass
class DaemonServerSpec:
    name: str
    start: Callable[[], None]
    stop: Optional[Callable[[], None]] = None
    health_check: Optional[Callable[[], Any]] = None

@dataclass
class DaemonServerRegisterContext:
    service: Any
    servers: List[DaemonServerSpec]
```

---

## DAEMON_TRANSPORT_REGISTER

Register the primary daemon transport. Exactly one transport must be registered.

```python
@dataclass
class DaemonTransportSpec:
    name: str
    run: Callable[[], None]   # blocking foreground loop
    stop: Callable[[], None]

@dataclass
class DaemonTransportRegisterContext:
    double_verbose: bool
    transports: List[DaemonTransportSpec]
```

---

## TRAY_MENU_REGISTER

Contribute macOS tray menu items. Append `TrayPluginEntry` items to the lists.

```python
@dataclass
class TrayMenuRegisterContext:
    status_entries: List[TrayPluginEntry]   # read-only label rows
    action_entries: List[TrayPluginEntry]   # clickable rows
    start_service: Callable[[], None]
    stop_service: Callable[[], None]
    is_service_running: Callable[[], bool]
    on_error: Callable[[str], None]
```

```python
from asky.daemon.tray_protocol import TrayPluginEntry

ctx.status_entries.append(TrayPluginEntry(
    get_label=lambda: f"MyPlugin: {'on' if self._running else 'off'}"
))
ctx.action_entries.append(TrayPluginEntry(
    get_label=lambda: "Stop" if self._running else "Start",
    on_action=lambda: self._toggle(),
))
```

---

## Deferred Hooks (not yet implemented)

`CONFIG_LOADED` and `SESSION_END` are reserved for a future release. Do not register callbacks for them.
