# Hook Points & Extraction Map

Companion to [plugin-system.md](plugin-system.md). This document defines every hook point with its exact signature, call site, and use cases. It also maps existing features to hooks for potential extraction.

---

## Hook Point Reference

### `TOOL_REGISTRY_BUILD`

**When**: After `create_tool_registry()` or `create_research_tool_registry()` builds the default tool set, before the registry is returned to callers.

**Call site**: `src/asky/core/tool_registry_factory.py` — end of `create_tool_registry()` and `create_research_tool_registry()`.

**Payload**:
```python
def callback(
    registry: ToolRegistry,
    mode: str,  # "standard" or "research"
    disabled_tools: Set[str],  # tools already disabled by user
) -> None:
```

**Plugin actions**: Call `registry.register(name, schema, executor)` to add tools. Check `disabled_tools` to respect user preferences. Check `mode` to only register in appropriate modes.

**Used by**:
- Manual Persona Creator: registers `create_persona`, `add_to_persona`, `list_personas`, `export_persona`
- Persona Manager: registers `load_persona`, `unload_persona`, `query_persona_knowledge`, `import_persona`
- Puppeteer Browser: registers `browser_fetch`, `browser_login`, `list_browser_profiles`
- GUI Server: optionally registers GUI-related tools

---

### `SYSTEM_PROMPT_EXTEND`

**When**: After the system prompt is fully constructed (including tool guidelines), before it's sent to the model.

**Call site**: `src/asky/api/client.py` — in `build_messages()`, after `_append_enabled_tool_guidelines()`.

**Payload (chain)**:
```python
def callback(
    data: str,  # current system prompt text
    config: AskyConfig,
    session_id: Optional[str],
) -> str:  # return modified prompt
```

**Plugin actions**: Append persona instructions, add plugin-specific guidance sections.

**Used by**:
- Persona Manager: prepends persona's system prompt and behavioral instructions when a persona is loaded.

---

### `PRE_LLM_CALL`

**When**: Before each LLM API call within the conversation engine's multi-turn loop.

**Call site**: `src/asky/core/engine.py` — in `ConversationEngine.run()`, before calling `get_llm_msg()`.

**Payload**:
```python
def callback(
    messages: List[Dict[str, Any]],  # mutable message list
    model: str,
    turn_number: int,
) -> None:
```

**Plugin actions**: Inspect or mutate messages (e.g., inject context, filter content). Use with care — mutations affect model behavior.

**Used by**: Advanced plugins that need to dynamically adjust context per turn.

---

### `POST_LLM_RESPONSE`

**When**: After the LLM returns a response, before tool calls are dispatched.

**Call site**: `src/asky/core/engine.py` — in `ConversationEngine.run()`, after receiving response.

**Payload**:
```python
def callback(
    response: Dict[str, Any],  # raw LLM response
    tool_calls: List[Dict[str, Any]],  # parsed tool calls (may be empty)
    turn_number: int,
) -> None:
```

**Plugin actions**: Log responses, collect analytics, detect patterns.

---

### `PRE_TOOL_EXECUTE`

**When**: Before a tool executor is called.

**Call site**: `src/asky/core/registry.py` — in `ToolRegistry.dispatch()`, before calling the executor.

**Payload**:
```python
@dataclass
class ToolExecutionContext:
    tool_name: str
    args: Dict[str, Any]  # mutable — plugins can modify
    skip: bool = False  # set True to skip execution, provide result instead
    result: Optional[Dict[str, Any]] = None  # pre-filled result when skip=True

def callback(ctx: ToolExecutionContext) -> None:
```

**Plugin actions**:
- Modify tool arguments before execution.
- Short-circuit tool execution by setting `skip=True` and providing a `result`.
- Route calls to alternative implementations (e.g., Puppeteer intercepts `get_url_content`).

**Used by**:
- Puppeteer Browser: intercepts `get_url_content` when a browser profile matches the target URL domain, or when basic fetch returns 403.

---

### `POST_TOOL_EXECUTE`

**When**: After a tool executor returns its result.

**Call site**: `src/asky/core/registry.py` — in `ToolRegistry.dispatch()`, after the executor returns.

**Payload**:
```python
@dataclass
class ToolResultContext:
    tool_name: str
    args: Dict[str, Any]  # original args
    result: Dict[str, Any]  # mutable — plugins can modify
    execution_time_ms: float

def callback(ctx: ToolResultContext) -> None:
```

**Plugin actions**: Transform results, add metadata, cache results, trigger side effects.

---

### `DAEMON_SERVER_REGISTER`

**When**: During daemon startup, after XMPP client is initialized but before the event loop starts.

**Call site**: `src/asky/daemon/service.py` — in `run_foreground()`, before `asyncio.get_event_loop().run_forever()`.

**Payload**:
```python
def callback(
    daemon_service: XMPPDaemonService,
    servers: List[DaemonServerSpec],  # mutable list — append your server specs
    event_loop: asyncio.AbstractEventLoop,
) -> None:
```

**Plugin actions**: Append `DaemonServerSpec` objects. The daemon service will call `spec.start()` for each and `spec.stop()` on shutdown.

**Used by**:
- GUI Server: starts NiceGUI web server on configured port.

---

### `CONFIG_LOADED`

**When**: After all TOML config files are loaded and merged, before constants are exported.

**Call site**: `src/asky/config/loader.py` — at the end of `load_config()`.

**Payload**:
```python
def callback(config: Dict[str, Any]) -> None:  # mutable config dict
```

**Plugin actions**: Register default values for plugin-specific config keys. Validate required config.

**Note**: This hook fires very early (before plugins are activated). It's invoked by the `PluginManager` during a special pre-activation config pass where only the `CONFIG_LOADED` hooks from plugins' `__init__` module-level registrations are called. Alternatively, plugins can simply define their defaults in their own TOML files.

**Recommendation**: Most plugins should use their own `plugins/<name>.toml` file for config rather than mutating global config. This hook is for plugins that need to influence global Asky behavior.

---

### `SESSION_START`

**When**: When a session is created or resumed.

**Call site**: `src/asky/api/session.py` — in `resolve_session_for_turn()`, after session is resolved.

**Payload**:
```python
def callback(
    session_id: str,
    session_name: Optional[str],
    is_new: bool,
    research_mode: bool,
) -> None:
```

**Plugin actions**: Load session-scoped data (e.g., persona bindings). Initialize session state.

**Used by**:
- Persona Manager: loads persona bound to session.

---

### `SESSION_END`

**When**: When a session is explicitly ended or when the process exits cleanly.

**Call site**: `src/asky/api/client.py` — after `run_turn()` completes (for CLI mode), or on daemon shutdown.

**Payload**:
```python
def callback(session_id: str) -> None:
```

**Plugin actions**: Persist session-scoped data, clean up resources.

---

### `PRE_PRELOAD`

**When**: Before the preload pipeline runs (local ingestion + shortlist).

**Call site**: `src/asky/api/client.py` — in `run_turn()`, before calling `run_preload_pipeline()`.

**Payload**:
```python
@dataclass
class PreloadContext:
    config: AskyConfig
    session_id: Optional[str]
    research_mode: bool
    extra_sources: List[str]  # mutable — plugins can add sources to preload

def callback(ctx: PreloadContext) -> None:
```

**Plugin actions**: Inject additional sources into the preload pipeline (e.g., persona corpus URLs).

**Used by**:
- Persona Manager: adds persona's vector data references to preload sources.

---

### `POST_PRELOAD`

**When**: After the preload pipeline completes, before messages are assembled.

**Call site**: `src/asky/api/client.py` — in `run_turn()`, after preload pipeline returns.

**Payload**:
```python
@dataclass
class PostPreloadContext:
    preload_result: PreloadResolution  # the resolved preload data
    extra_context: List[str]  # mutable — plugins can append context blocks

def callback(ctx: PostPreloadContext) -> None:
```

**Plugin actions**: Inject additional context blocks into the message assembly (e.g., persona knowledge chunks).

**Used by**:
- Persona Manager: injects persona-relevant chunks into the context.

---

## Extraction Candidates

These are existing Asky features that could be moved to plugins. Each entry shows the current location, the hooks it would use, and the extraction complexity.

### 1. Push Data (Low Risk, Low Effort)

**Current location**: `src/asky/push_data.py` + `push_data.toml` config
**Current integration**: `tool_registry_factory.py` registers `push_data_*` tools dynamically
**Hooks needed**: `TOOL_REGISTRY_BUILD`, `CONFIG_LOADED`
**Extraction plan**:
- Move `push_data.py` to `src/asky/plugins/push_data/`
- Plugin reads `push_data.toml` in its own config, registers tools via `TOOL_REGISTRY_BUILD`
- Remove push_data tool registration from `tool_registry_factory.py`
- Fallback: if plugin not loaded but `push_data.toml` exists, factory still registers (backward compat)

### 2. Email Sender (Low Risk, Low Effort)

**Current location**: `src/asky/email_sender.py`
**Current integration**: registered as tool in `tool_registry_factory.py` via custom tools config
**Hooks needed**: `TOOL_REGISTRY_BUILD`
**Extraction plan**:
- Move `email_sender.py` to `src/asky/plugins/email_sender/`
- Plugin registers `send_email` tool via `TOOL_REGISTRY_BUILD`
- Remove email tool registration from factory

### 3. Browser Rendering (Low Risk, Medium Effort)

**Current location**: `src/asky/rendering.py`
**Current integration**: called from `chat.py` when `--render` flag is set
**Hooks needed**: New `POST_TURN` hook or `POST_TOOL_EXECUTE` on final answer
**Extraction plan**:
- Move `rendering.py` to `src/asky/plugins/renderer/`
- Plugin subscribes to a `POST_TURN` hook (new hook needed)
- Plugin reads config for whether to auto-render

### 4. XMPP Daemon (High Risk, High Effort — Future)

**Current location**: `src/asky/daemon/` (entire package)
**Current integration**: deeply integrated into `main.py` and daemon flow
**Hooks needed**: `DAEMON_SERVER_REGISTER` (would become the primary server, not an addition)
**Extraction plan**:
- This is a long-term goal, not for initial phases
- Would require the daemon service to become a plugin that registers itself as the XMPP server
- The `DAEMON_SERVER_REGISTER` hook was designed with this in mind

### 5. Research Tools (Medium Risk, Medium Effort — Future)

**Current location**: `src/asky/research/tools.py`, `tool_registry_factory.py`
**Current integration**: `create_research_tool_registry()` in factory
**Hooks needed**: `TOOL_REGISTRY_BUILD` (mode="research")
**Extraction plan**:
- Move research tool definitions to a plugin
- Keep research infrastructure (vector store, cache) in core since many features depend on it
- Plugin only handles tool schema registration and executor wiring

### 6. Memory System (Medium Risk, Medium Effort — Future)

**Current location**: `src/asky/memory/`
**Current integration**: recall injected in `client.py`, tools in factory, auto-extract in `chat.py`
**Hooks needed**: `SYSTEM_PROMPT_EXTEND` (for recall injection), `TOOL_REGISTRY_BUILD` (for save_memory tool), `SESSION_END` (for auto-extract)
**Extraction plan**:
- Memory recall → `SYSTEM_PROMPT_EXTEND` hook
- Memory tools → `TOOL_REGISTRY_BUILD` hook
- Auto-extract → `SESSION_END` hook
- Keep `memory/store.py` and `memory/vector_ops.py` as core infrastructure

---

## Hook Invocation Patterns

### Guard Pattern (zero overhead without plugins)

Every hook call site must follow this pattern:

```python
# In engine.py, client.py, etc.
if self._hook_registry:
    self._hook_registry.invoke(HOOK_NAME, arg1=val1, arg2=val2)
```

Or for chain hooks:

```python
if self._hook_registry:
    system_prompt = self._hook_registry.invoke_chain(
        SYSTEM_PROMPT_EXTEND, data=system_prompt, config=config
    )
```

### Passing HookRegistry Through the Stack

The `HookRegistry` flows from `PluginManager` → `AskyClient` → `ConversationEngine` → `ToolRegistry`:

```
main.py
  └── PluginManager (owns HookRegistry)
        └── passes to AskyClient(hook_registry=...)
              └── passes to create_tool_registry(hook_registry=...)
              └── passes to ConversationEngine(hook_registry=...)
                    └── ToolRegistry already has it from factory
```

All parameters are `Optional[HookRegistry]` with default `None` for backward compatibility.

---

## Priority Guidelines

| Priority Range | Intended Use |
|---------------|--------------|
| 0–49 | Core/infrastructure hooks (config validation, logging) |
| 50–99 | Pre-processing hooks (input transformation) |
| 100 | Default (most plugins) |
| 101–149 | Post-processing hooks (output transformation) |
| 150–199 | Monitoring/analytics hooks (read-only observation) |

Plugins should document their chosen priorities to avoid conflicts.
