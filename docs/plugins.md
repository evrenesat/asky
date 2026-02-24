# Plugin Runtime and Built-in Plugins

This document explains user-facing plugin behavior in the current implementation.

## 1. How Plugin Runtime Is Started

Plugins are loaded from:

- `~/.config/asky/plugins.toml`

Runtime initialization happens when asky starts query execution:

- Local CLI query flow (`asky ...`)
- XMPP daemon flow (`asky --xmpp-daemon`)

If no plugin is enabled in `plugins.toml`, runtime stays disabled.

## 2. Built-in Plugins (Current State)

Current built-in plugins:

- `manual_persona_creator`
- `persona_manager`
- `gui_server`

Important: only `gui_server` currently has a browser UI page. Persona plugins currently expose tool-based entry points (LLM tool calls), not a dedicated GUI panel.

## 3. GUI Server Entry Points

The GUI sidecar is started only from daemon service lifecycle.

Required:

1. `gui_server` plugin enabled in `~/.config/asky/plugins.toml`
2. Daemon running (`asky --xmpp-daemon`)

Default URL:

- [http://127.0.0.1:8766/settings/general](http://127.0.0.1:8766/settings/general)
- [http://127.0.0.1:8766/plugins](http://127.0.0.1:8766/plugins)

Host/port can be overridden with plugin config file referenced from `plugins.toml`:

```toml
[plugin.gui_server]
enabled = true
module = "asky.plugins.gui_server.plugin"
class = "GUIServerPlugin"
config_file = "plugins/gui_server.toml"
```

`~/.config/asky/plugins/gui_server.toml`:

```toml
host = "127.0.0.1"
port = 8766
```

## 4. Persona Plugin Entry Points (Current)

Persona features are currently entered through LLM tool calls.

There is no standalone CLI command like `asky --create-persona ...` yet.

### 4.1 Manual Persona Creator Tools

Registered tool names:

- `manual_persona_create`
- `manual_persona_add_sources`
- `manual_persona_list`
- `manual_persona_export`

Practical usage in chat:

- Ask the model explicitly to call one of these tools with concrete args.
- In verbose mode, tool calls and payloads are visible.

Example prompt patterns:

- "Create a persona named `analyst_alpha` with behavior prompt 'Answer with concise risk-first analysis', and ingest sources `/Users/me/docs/a.md` and `/Users/me/docs/b.md` using `manual_persona_create`."
- "Export persona `analyst_alpha` with `manual_persona_export` and return archive path."

### 4.2 Persona Manager Tools

Registered tool names:

- `persona_import_package`
- `persona_load`
- `persona_unload`
- `persona_current`
- `persona_list`

Important runtime requirement:

- `persona_load` requires an active session context; otherwise it returns: `no active session; load persona within a session`.

Recommended flow:

1. Start/resume a session (`-ss` or `-rs`)
2. Import persona package if needed (`persona_import_package`)
3. Load persona into active session (`persona_load`)
4. Ask normal queries; plugin injects persona prompt + top persona knowledge chunks

Example prompt patterns:

- "In this active session, call `persona_load` with name `analyst_alpha`."
- "Show current loaded persona by calling `persona_current`."

## 5. Where Persona Data Lives

Persona plugin data is stored under asky plugin data directory:

- `~/.config/asky/plugins/personas/<persona_name>/...`

Typical files:

- `metadata.toml`
- `behavior_prompt.md`
- `chunks.json`
- `embeddings.json` (after import/rebuild)

Session bindings are persisted in:

- `~/.config/asky/plugins/session_bindings.toml`

## 6. Current Limitations (Explicit)

- No dedicated persona GUI page yet (only general settings page exists today).
- No dedicated persona CLI commands yet.
- Persona workflows depend on model/tool-call behavior; explicit prompts to use exact tool names are currently the practical entry path.
- GUI server startup visibility is minimal right now (no explicit CLI status line/menu action yet).

## 7. Near-term Documentation Intent

When persona GUI and direct CLI entry points are added, this file should be updated first with exact user flows and examples.
