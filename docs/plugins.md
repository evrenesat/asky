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
- `manual_persona_creator`: Persona authoring via CLI-first workflows.
- `persona_manager`: Session persona binding and grounded runtime orchestration.
- `playwright_browser`: Headless browser capability for research fetching.
- `push_data`: Provides `--push-data` HTTP webhook invocation tools.
- `voice_transcriber`: Processes incoming audio messages via local MLX models.
- `xmpp_daemon`: Headless messaging daemon supporting macOS tray interface.

Important: only `gui_server` currently has a browser UI page. Persona features are now primary CLI-driven and integrated into the core chat loop.

## 3. Persona Plugin Entry Points

Persona features are accessible via direct CLI commands and deterministic preprocessing.

### 3.1 Persona CLI Commands

Common management:
- `asky persona list` - List all available personas.
- `asky persona create <name> --prompt <file>` - Create new persona from prompt file.
- `asky persona add-sources <name> <sources...>` - Add knowledge sources to persona (with deduplication).
- `asky persona load <name>` - Load persona into current session.
- `asky persona unload` - Unload current persona.
- `asky persona current` - Show currently loaded persona.
- `asky persona import <path>` - Import persona from ZIP file.
- `asky persona export <name>` - Export persona to ZIP file.
- `asky persona alias <alias> <name>` - Create persona alias.

Authored Book Ingestion:
- `asky persona ingest-book <persona> <path>` - Ingest a long-form source (PDF, EPUB, Text) into a persona.
- `asky persona reingest-book <persona> <book_key> <path>` - Replace an existing book's data.
- `asky persona books <persona>` - List all ingested books for a persona.
- `asky persona book-report <persona> <book_key>` - View detailed ingestion report.
- `asky persona viewpoints <persona> [--book <key>] [--topic <query>] [--limit <n>]` - Query extracted viewpoints.

### 3.2 Mentions and Auto-loading

You can load a persona for a single query using the `@` syntax. This is handled as a **preprocessing operation** before the query reaches the model:
- `@arendt How does she define labor?` - Loads the `arendt` persona and removes the mention from the query.

### 3.3 Minimal Grounding Contract

When a persona is loaded, the runtime enforces a grounded answer contract. The model is instructed to follow this format:

```text
Answer: <the grounded answer>
Grounding: <direct_evidence | supported_pattern | bounded_inference | insufficient_evidence>
Evidence: <citations like [P1], [P2]>
```

If the response lacks required grounding or citations while evidence was provided, the runtime automatically collapses the reply to a safe fallback:
- `I don't have enough grounded persona evidence to answer this reliably.`

## 4. Persona Data and Schema

Persona plugin data uses **Schema v3** and is stored under:

- `~/.config/asky/plugins/persona_manager/personas/<persona_name>/...`

Core layout:
- `metadata.toml`: Persona metadata and schema version.
- `behavior_prompt.md`: The system prompt for the persona.
- `chunks.json`: Normalized knowledge chunks (v1/v2 compatibility).
- `persona_knowledge/sources.json`: Canonical record of all ingested sources.
- `persona_knowledge/entries.json`: Canonical catalog of viewpoints, excerpts, and chunks.

### 4.1 Ingestion and Deduplication
Manual source ingestion (`add-sources`) uses deterministic content fingerprints. If you attempt to add a file that already exists in the persona's catalog, it will be skipped automatically to prevent duplicate knowledge and unnecessary embedding costs.

## 5. GUI Server Entry Points

The GUI sidecar is started only from daemon service lifecycle. Default URL: [http://127.0.0.1:8766/settings/general](http://127.0.0.1:8766/settings/general).

## 6. Current Limitations

- No dedicated persona GUI page yet.
- GUI server startup visibility is minimal right now.
