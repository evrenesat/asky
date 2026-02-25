# Hook Points & Extraction Map (Revised)

Companion to [plugin-system.md](plugin-system.md) and [plugin-system-api.md](plugin-system-api.md).

This document defines v1 hook points, exact call sites, payload contracts, and extraction mapping.

---

## v1 Hook Lifecycle Order

For a normal turn, expected order is:

1. `TOOL_REGISTRY_BUILD`
2. `SESSION_RESOLVED`
3. `PRE_PRELOAD`
4. `POST_PRELOAD`
5. `SYSTEM_PROMPT_EXTEND`
6. `PRE_LLM_CALL`
7. `POST_LLM_RESPONSE`
8. `PRE_TOOL_EXECUTE`
9. `POST_TOOL_EXECUTE`
10. `TURN_COMPLETED`

For daemon startup, `DAEMON_SERVER_REGISTER` runs during service boot.

---

## Hook Reference

## `TOOL_REGISTRY_BUILD`

**When**: after built-in/custom tools are registered, before factory returns.

**Call sites**:

- `src/asky/core/tool_registry_factory.py:create_tool_registry`
- `src/asky/core/tool_registry_factory.py:create_research_tool_registry`

**Payload**:

```python
@dataclass
class ToolRegistryBuildContext:
    registry: ToolRegistry
    mode: Literal["standard", "research"]
    disabled_tools: set[str]
    session_id: str | None = None
    research_source_mode: str | None = None
```

**Mutability**:

- `registry` is mutable (register additional tools).
- `disabled_tools` is read-only input.

**Primary use**:

- plugin tool registration.

---

## `SESSION_RESOLVED`

**When**: session resolution is complete for `run_turn()` and effective profile is known.

**Call site**:

- `src/asky/api/client.py:run_turn`

**Payload**:

```python
@dataclass
class SessionResolvedContext:
    request: AskyTurnRequest
    session_resolution: SessionResolution
    session_id: str | None
    research_mode: bool
    research_source_mode: str | None
```

**Mutability**:

- observation-oriented in v1; no mutation guarantees.

**Primary use**:

- session-bound plugin state load/check.

---

## `PRE_PRELOAD`

**When**: immediately before `run_preload_pipeline(...)`.

**Call site**:

- `src/asky/api/client.py:run_turn`

**Payload**:

```python
@dataclass
class PrePreloadContext:
    query_text: str
    research_mode: bool
    local_corpus_paths: list[str] | None
    additional_source_context: str | None
```

**Mutability**:

- mutable fields; plugin may update values in-place.

**Primary use**:

- add extra preload source hints.

---

## `POST_PRELOAD`

**When**: after preload resolution, before message assembly.

**Call site**:

- `src/asky/api/client.py:run_turn`

**Payload**:

```python
@dataclass
class PostPreloadContext:
    preload: PreloadResolution
    query_text: str
    session_id: str | None
    research_mode: bool
```

**Mutability**:

- `preload` is mutable (`combined_context`, extra source handles, etc).

**Primary use**:

- inject plugin-generated context blocks.

---

## `SYSTEM_PROMPT_EXTEND` (Chain)

**When**: after base prompt + tool guidelines are assembled, before model call.

**Call site**:

- `src/asky/api/client.py:run_messages`

**Signature**:

```python
def callback(
    data: str,
    *,
    session_id: str | None,
    research_mode: bool,
    model_alias: str,
) -> str:
    ...
```

**Mutability**:

- chain return value becomes next prompt value.

**Primary use**:

- persona/system instruction augmentation.

---

## `PRE_LLM_CALL`

**When**: before each `get_llm_msg(...)` call in engine loop.

**Call site**:

- `src/asky/core/engine.py:ConversationEngine.run`

**Payload**:

```python
@dataclass
class PreLLMCallContext:
    turn_number: int
    model_id: str
    messages: list[dict[str, Any]]
    use_tools: bool
```

**Mutability**:

- `messages` mutable (advanced use only).

**Primary use**:

- turn-level instrumentation or guarded message shaping.

---

## `POST_LLM_RESPONSE`

**When**: after model response is received and parsed, before tool dispatch.

**Call site**:

- `src/asky/core/engine.py:ConversationEngine.run`

**Payload**:

```python
@dataclass
class PostLLMResponseContext:
    turn_number: int
    response_message: dict[str, Any]
    parsed_tool_calls: list[dict[str, Any]]
```

**Mutability**:

- `parsed_tool_calls` may be edited (use cautiously).

**Primary use**:

- response analytics or guarded tool-call filtering.

---

## `PRE_TOOL_EXECUTE`

**When**: before executor invocation in tool dispatch.

**Call site**:

- `src/asky/core/registry.py:ToolRegistry.dispatch`

**Payload**:

```python
@dataclass
class ToolExecutionContext:
    tool_name: str
    args: dict[str, Any]
    skip: bool = False
    result: dict[str, Any] | None = None
```

**Mutability**:

- `args` mutable.
- may short-circuit execution via `skip=True` and `result`.

**Primary use**:

- alternative execution routing (browser fetch plugin).

---

## `POST_TOOL_EXECUTE`

**When**: after executor returns.

**Call site**:

- `src/asky/core/registry.py:ToolRegistry.dispatch`

**Payload**:

```python
@dataclass
class ToolResultContext:
    tool_name: str
    args: dict[str, Any]
    result: dict[str, Any]
    execution_time_ms: float
```

**Mutability**:

- `result` mutable.

**Primary use**:

- result transformation, caching metadata, side-channel observability.

---

## `TURN_COMPLETED`

**When**: after final answer is produced and turn result assembled.

**Call site**:

- `src/asky/api/client.py:run_turn`

**Payload**:

```python
@dataclass
class TurnCompletedContext:
    request: AskyTurnRequest
    result: AskyTurnResult
    session_id: str | None
```

**Mutability**:

- read-only intent in v1.

**Primary use**:

- plugin post-turn side effects (logging/indexing/non-blocking tasks).

---

## `DAEMON_SERVER_REGISTER`

**When**: during daemon startup before entering foreground loop.

**Call site**:

- `src/asky/daemon/service.py:XMPPDaemonService.run_foreground`

**Payload**:

```python
@dataclass
class DaemonServerSpec:
    name: str
    start: Callable[[], None]
    stop: Callable[[], None]
    is_running: Callable[[], bool]


def callback(
    daemon_service: XMPPDaemonService,
    servers: list[DaemonServerSpec],
) -> None:
    ...
```

**Mutability**:

- append server specs to `servers` list.

**Primary use**:

- GUI server registration.

---

## Deferred Hooks (Not in v1)

These are intentionally deferred until core runtime is stable:

1. `CONFIG_LOADED` (global config bootstrap ordering risk)
2. `SESSION_END` (ambiguous semantics across CLI/API/daemon)
3. `POST_TURN_RENDER` (render pipeline extraction can use `TURN_COMPLETED` first)

---

## Extraction Candidates

## 1. Push Data (Low Risk)

- Current: `src/asky/push_data.py` + registry factory wiring
- Hooks: `TOOL_REGISTRY_BUILD`
- Migration: plugin registers push endpoints; retain fallback for compatibility window

## 2. Email Sender (Low Risk)

- Current: `src/asky/email_sender.py`
- Hooks: `TOOL_REGISTRY_BUILD`
- Migration: plugin-owned tool registration

## 3. Rendering (Low/Medium Risk)

- Current: `src/asky/rendering.py` called from chat flow
- Hooks: `TURN_COMPLETED`
- Migration: plugin-driven render action on final answer

## 4. Research Tool Registration (Medium Risk)

- Current: research tool registration in `tool_registry_factory.py`
- Hooks: `TOOL_REGISTRY_BUILD` (research mode)
- Migration: keep research infra core, move registration surface

## 5. Memory Behavior Split (Medium Risk)

- Current: memory recall/extraction mixed in core turn flow
- Hooks: `SYSTEM_PROMPT_EXTEND`, `TOOL_REGISTRY_BUILD`, `TURN_COMPLETED`
- Migration: staged extraction, keep storage/vector infra core

## 6. XMPP Daemon (High Risk, Long-Term)

- Current: deeply integrated daemon package
- Hooks: `DAEMON_SERVER_REGISTER` as precursor
- Migration: only after plugin runtime is proven in production

---

## Invocation Guard Pattern

Every call site must guard for absent runtime:

```python
if hook_registry is not None:
    hook_registry.invoke(HOOK_NAME, context=context)
```

Chain hooks:

```python
if hook_registry is not None:
    prompt = hook_registry.invoke_chain(
        SYSTEM_PROMPT_EXTEND,
        data=prompt,
        session_id=session_id,
        research_mode=research_mode,
        model_alias=model_alias,
    )
```

---

## Priority Guidelines

| Range | Intent |
| --- | --- |
| 0-49 | infrastructure/validation |
| 50-99 | preprocess/overrides |
| 100 | default |
| 101-149 | postprocess |
| 150-199 | analytics/observers |

Tie-breakers are deterministic (`plugin_name`, then registration order).
