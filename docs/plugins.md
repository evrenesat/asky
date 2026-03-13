# Plugin Runtime and Built-in Plugins

This document explains user-facing plugin behavior in the current implementation.

## 1. How Plugin Runtime Is Started

Plugins are loaded from:

- `~/.config/asky/plugins.toml`

Runtime initialization happens when asky starts query execution:

- Local CLI query flow (`asky ...`)
- XMPP daemon flow (`asky --daemon`)

If no plugin is enabled in `plugins.toml`, runtime stays disabled.

## 2. Built-in Plugins (Current State)

Current built-in plugins:

- `email_sender`: Provides `--mail` CLI argument support and email dispatch tools.
- `gui_server`: Provides local web interface settings and status pages.
- `image_transcriber`: Processes incoming image attachments for daemon mode.
- `manual_persona_creator`: Persona authoring via tool execution.
- `persona_manager`: Session persona binding via tool execution.
- `playwright_browser`: Headless browser capability for research fetching.
- `push_data`: Provides `--push-data` HTTP webhook invocation tools.
- `voice_transcriber`: Processes incoming audio messages via local MLX models.
- `xmpp_daemon`: Headless messaging daemon supporting macOS tray interface.

Important: only `gui_server` currently has a browser UI page. Persona plugins currently expose tool-based entry points (LLM tool calls), not a dedicated GUI panel.

## 3. GUI Server Entry Points

The GUI sidecar is started only from daemon service lifecycle.

Required:

1. `gui_server` plugin enabled in `~/.config/asky/plugins.toml`
2. Daemon running (`asky --daemon`)

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

## 4. Persona Plugin Entry Points

Persona features are accessible via direct CLI commands and LLM tool calls.

### 4.1 Persona CLI Commands

Common management:
- `asky persona list` - List all available personas.
- `asky persona create <name> --prompt <file>` - Create new persona from prompt file.
- `asky persona load <name>` - Load persona into current session.
- `asky persona unload` - Unload current persona.
- `asky persona current` - Show currently loaded persona.
- `asky persona import <path>` - Import persona from ZIP file.
- `asky persona export <name>` - Export persona to ZIP file.
- `asky persona alias <alias> <name>` - Create persona alias.

Authored Book Ingestion:
- `asky persona ingest-book <persona> <path>` - Ingest a long-form source (PDF, EPUB, Text) into a persona. Includes metadata lookup and structured viewpoint extraction.
- `asky persona reingest-book <persona> <book_key> <path>` - Replace an existing book's data while preserving its identity.
- `asky persona books <persona>` - List all ingested books for a persona.
- `asky persona book-report <persona> <book_key>` - View detailed ingestion report (timings, warnings, targets).
- `asky persona viewpoints <persona> [--book <key>] [--topic <query>] [--limit <n>]` - Query extracted viewpoints across one or all books.

### 4.2 Mentions and Auto-loading

You can load a persona for a single query (or start a session with it) using the `@` syntax:
- `@arendt How does she define labor?` - Loads the `arendt` persona before executing the query.

### 4.3 Plugin Tools (LLM Entry Points)

Persona plugins still expose runtime tools for import/load/unload style operations where the runtime surface needs them, but persona creation and authored-book ingestion are now CLI-first workflows.

Use the CLI when you need deterministic file-based persona management.
Use runtime persona loading when you need to bind an already-created persona to the current session.
Patterns for chat usage:
- "Create a persona named `analyst_alpha`..."
- "Load persona `arendt` in this session."

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
