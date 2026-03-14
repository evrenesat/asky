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

Source-Aware Ingestion and Review (Milestone 3):
- `asky persona ingest-source <persona> <kind> <path>` - Ingest various source kinds (biography, article, interview, etc.).
- `asky persona sources <persona> [--status <filter>] [--kind <filter>]` - List ingested source bundles.
- `asky persona source-report <persona> <source_id>` - View extraction report for a specific source bundle.
- `asky persona approve-source <persona> <source_id>` - Approve and project knowledge from a pending source.
- `asky persona reject-source <persona> <source_id>` - Reject a source bundle.
- `asky persona facts <persona> [--source <id>] [--topic <query>]` - Query approved biographical facts.
- `asky persona timeline <persona> [--source <id>] [--year <n>]` - Query approved chronological events.
- `asky persona conflicts <persona> [--topic <query>]` - Query preserved contradictions between sources.

### 3.2 Mentions and Auto-loading

You can load a persona for a single query using the `@` syntax. This is handled as a **preprocessing operation** before the query reaches the model:
- `@arendt How does she define labor?` - Loads the `arendt` persona and removes the mention from the query.

### 3.3 Milestone-2 Grounding Contract

When a persona is loaded, the runtime enforces a grounded answer contract. The model is provided with **Structured Evidence Packets** which include source class, trust level, and linked evidence excerpts.

The model is instructed to follow this exact format:

```text
Answer: <the grounded answer>
Grounding: <direct_evidence | supported_pattern | bounded_inference | insufficient_evidence>
Evidence: <citations like [P1], [P2]>
Current Context: <citations like [W1] for fresh web context, only when used>
```

#### 3.3.1 Structured Retrieval and Priority
Retrieval uses a multi-level priority system to ensure the most reliable information is presented first:
1. **Viewpoints**: Extracted high-level worldview claims from authored books.
2. **Evidence Excerpts**: Direct supporting quotes linked to viewpoints.
3. **Raw Chunks**: General knowledge fragments from manual sources.

#### 3.3.2 Current Context Attribution
If live tools (like web search) are used during a persona turn, the model must attribute them separately in the `Current Context:` section using `[W#]` citations. If persona knowledge is synthesized with live context, `Grounding: bounded_inference` is required.

#### 3.3.3 Validation and Fallback
If the response lacks required grounding or citations while evidence was provided, the runtime automatically collapses the reply to a safe fallback:
- `I don't have enough grounded persona evidence to answer this reliably.`
- The fallback includes a list of the evidence packets the model was supposed to consider.

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
