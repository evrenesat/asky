# Persona Manager Plugin (`plugins/persona_manager/`)

Hardened runtime orchestration for grounded persona behavior.

## Module Overview

| Module | Purpose |
| --- | --- |
| `plugin.py` | Plugin entrypoint and hook handlers |
| `runtime_types.py` | Typed runtime models for packets and plan state |
| `runtime_planner.py` | Structured retrieval and multi-level ranking |
| `runtime_grounding.py` | Answer validation and grounded contract |
| `importer.py` | Persona ZIP import and derived artifact rebuild |
| `knowledge.py` | Legacy embedding build helpers |
| `gui_service.py` | Browser-facing helpers for session/persona binding |
| `session_binding.py` | Persistent session-to-persona mappings |

## Runtime Boundary

Only approved persona knowledge participates in runtime answering.

- approved sources feed the runtime index
- primary packets remain `viewpoint` and `raw_chunk`
- `persona_fact` and `timeline_event` stay queryable via CLI but are not primary voice packets
- metadata preserves source kind for formatting and debugging

## Grounding Contract

Persona answers must use:

- `Answer:`
- `Grounding:`
- `Evidence:` with `[P#]`
- `Current Context:` with `[W#]` when live context is used

Replies that blur persona evidence and live context or omit required citations are collapsed to the safe fallback.

## Retrieval Strategy

Structured retrieval order:

1. viewpoints
2. linked evidence excerpts
3. raw chunks

This ranking is intentional. Do not bypass it from GUI code.

## Hook Usage

- `SESSION_RESOLVED` resolves active session binding
- `SYSTEM_PROMPT_EXTEND` injects persona behavior prompt and grounding rules
- `PRE_PRELOAD` injects retrieved persona packets
- `POST_TOOL_EXECUTE` tracks live web sources
- `POST_LLM_RESPONSE` validates grounded format and attribution
- `TURN_COMPLETED` clears turn-scoped state
- `GUI_EXTENSION_REGISTER` registers the session binding page

## GUI Scope

Current browser scope for this plugin is narrow by design:

- list sessions
- inspect current persona binding
- bind or unbind a persona for a session

This plugin does **not** currently provide:

- browser chat UI
- browser persona query UI
- browser-side runtime evidence inspection for normal chat turns

Keep it that way unless the architecture is explicitly expanded.

## GUI/Admin Rules

Browser code for this plugin should use service helpers, not reach into runtime internals.

Use:

- `gui_service.py` for list/binding helpers
- `session_binding.py` through the service layer

Do not:

- put runtime-answering logic into page modules
- mutate random storage files directly from page code when a helper already exists
- turn the session binding page into a general persona-control surface

Binding actions are immediate admin mutations, so they can stay as small direct handlers instead of queue jobs.

Example shape:

```python
def _on_change(value: str, session_id: int) -> None:
    persona_name = None if value == "(None)" else value
    bind_persona_to_session(data_dir, session_id, persona_name)
    ui.notify(f"Session {session_id} bound to {value}")
```

This is the right level of work for the browser here: validate, call helper, notify.

## Deterministic Preprocessing

- `@persona_name` or `@alias` can load a persona before model execution
- the mention token is stripped before the model sees the query

## Invariants

- schema v3 foundation is required for full grounding metadata
- imports rebuild derived artifacts when needed
- citation validation ensures cited `[P#]` packets exist in retrieved context
