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
- `DAEMON_SERVER_REGISTER` — collect sidecar server specs (start/stop callables)
- `DAEMON_TRANSPORT_REGISTER` — register exactly one daemon transport (run/stop callables)

Deferred in v1:

- `CONFIG_LOADED`
- `POST_TURN_RENDER`
- `SESSION_END`

## Built-in Plugins

- `manual_persona_creator/` — CLI-based persona creation/ingestion/export
- `persona_manager/` — persona import/session binding/prompt+preload injection with @mention syntax
- `gui_server/` — NiceGUI daemon sidecar and page extension registry
- `xmpp_daemon/` — XMPP transport for daemon mode (router, executor, voice/image pipelines)

## xmpp_daemon Plugin

`xmpp_daemon/` provides the XMPP transport layer for `asky --daemon`. It registers itself via the `DAEMON_TRANSPORT_REGISTER` hook. The daemon core (`daemon/service.py`) is transport-agnostic; `xmpp_daemon` is the only built-in transport.

Key modules:

| Module                      | Purpose                                                    |
| --------------------------- | ---------------------------------------------------------- |
| `plugin.py`                 | `XMPPDaemonPlugin` — registers XMPP transport via hook     |
| `xmpp_service.py`           | `XMPPService` — per-JID queue + XMPP client wiring        |
| `xmpp_client.py`            | Slixmpp transport wrapper                                  |
| `router.py`                 | `DaemonRouter` — ingress policy (allowlist, room binding)  |
| `command_executor.py`       | Command/query bridge — policy gate, `AskyClient.run_turn`  |
| `session_profile_manager.py`| Room/session bindings + session override file management   |
| `interface_planner.py`      | LLM-based intent classification for non-prefixed messages  |
| `voice_transcriber.py`      | Background audio transcription via `mlx-whisper`           |
| `image_transcriber.py`      | Background image description via image-capable LLM         |
| `transcript_manager.py`     | Transcript lifecycle, pending confirmation tracking        |
| `chunking.py`               | Outbound response chunking                                 |

One-way dependency rule: `xmpp_daemon` may import from `asky.daemon.errors`; `daemon/` core must not import from `asky.plugins.xmpp_daemon`.

## User Entry Points (Current State)

- Runtime config entrypoint: `~/.config/asky/plugins.toml`
- GUI entrypoint (only when daemon is running): `http://127.0.0.1:8766/settings/general`
- Persona entrypoints: CLI commands (`asky persona <command>`) and @mention syntax in queries
  - No LLM tools registered for persona operations (CLI-only by design)
  - See `plugins/persona_manager/AGENTS.md` for full CLI command reference

For user-focused usage and limitations, see `docs/plugins.md`.
