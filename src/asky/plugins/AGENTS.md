# Plugins Package (`asky/plugins/`)

Optional plugin runtime for asky.

## Module Overview

| Module | Purpose |
| --- | --- |
| `manifest.py` | Plugin roster entry validation (`plugins.toml`) |
| `manager.py` | Plugin discovery/import/dependency order/lifecycle |
| `hooks.py` | Ordered hook registration and invocation |
| `hook_types.py` | Hook constants and mutable payload contracts |
| `runtime.py` | Runtime bootstrap + process-level cache |
| `base.py` | `AskyPlugin`, `PluginContext`, `PluginStatus` contracts |

## Hook Ordering

Hook callbacks run in deterministic order:

1. `priority` ascending
2. `plugin_name` ascending
3. `registration_index` ascending

Hook callback exceptions are logged and isolated; remaining callbacks still run.

## v1 Hook Surface

- `TOOL_REGISTRY_BUILD`
- `SESSION_RESOLVED`
- `PRE_PRELOAD`
- `POST_PRELOAD`
- `SYSTEM_PROMPT_EXTEND` (chain)
- `PRE_LLM_CALL`
- `POST_LLM_RESPONSE`
- `PRE_TOOL_EXECUTE`
- `POST_TOOL_EXECUTE`
- `TURN_COMPLETED`
- `DAEMON_SERVER_REGISTER`

Deferred in v1:

- `CONFIG_LOADED`
- `POST_TURN_RENDER`
- `SESSION_END`

## Built-in Plugins

- `manual_persona_creator/` — manual persona creation/ingestion/export tools
- `persona_manager/` — persona import/session binding/prompt+preload injection
- `gui_server/` — NiceGUI daemon sidecar and page extension registry

## User Entry Points (Current State)

- Runtime config entrypoint: `~/.config/asky/plugins.toml`
- GUI entrypoint (only when daemon is running): `http://127.0.0.1:8766/settings/general`
- Persona entrypoints: tool calls only (`manual_persona_*`, `persona_*`), not
  dedicated CLI flags or dedicated GUI pages yet.

For user-focused usage and limitations, see `docs/plugins.md`.
