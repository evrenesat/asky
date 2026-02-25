# CLI Package (`asky/cli/`)

Command-line interface layer handling argument parsing, command routing, and user interaction.

## Module Overview

| Module                    | Purpose                                                                                                                                        |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `main.py`                 | Entry point, argument parsing, command routing                                                                                                 |
| `chat.py`                 | Chat conversation orchestration                                                                                                                |
| `mention_parser.py`       | @mention syntax parsing for deterministic persona loading                                                                                      |
| `persona_commands.py`     | Persona management CLI commands (create, load, import, export, alias)                                                                          |
| `presets.py`              | Backslash command preset expansion/listing (`\\name`, `\\presets`)                                                                             |
| `local_ingestion_flow.py` | Pre-LLM local source preload for research mode (path-redacted local KB context)                                                                |
| `research_commands.py`    | Manual corpus query commands (no-LLM retrieval inspection)                                                                                     |
| `section_commands.py`     | Manual section listing/summarization for local corpus (no main model call)                                                                     |
| `shortlist_flow.py`       | Pre-LLM shortlist execution + banner updates                                                                                                   |
| `completion.py`           | Shell completion with argcomplete                                                                                                              |
| `display.py`              | Banner rendering, live status updates                                                                                                          |
| `history.py`              | History viewing/deletion commands                                                                                                              |
| `sessions.py`             | Session management commands                                                                                                                    |
| `prompts.py`              | User prompt listing                                                                                                                            |
| `models.py`               | Interactive model add/edit commands, including role assignment (main/summarization/interface) and per-model capability flags (`image_support`) |
| `daemon_config.py`        | Interactive daemon config editor (`--edit-daemon`) and startup-at-login toggles                                                                |
| `openrouter.py`           | OpenRouter API client for model discovery                                                                                                      |
| `terminal.py`             | Terminal context fetching                                                                                                                      |
| `utils.py`                | Query expansion, config printing                                                                                                               |

## Entry Point (`main.py`)

- Parses arguments with `argparse`
  - Help placeholders (`metavar`) are intentionally explicit typed descriptors
    (e.g., `HISTORY_IDS`, `SESSION_SELECTOR`, `LINE_COUNT`) to keep `--help`
    output user-oriented instead of mirroring internal destination names.
- Routes to appropriate handler based on command flags
- Implements lazy startup for fast CLI response:
  - Completion, imports, DB init are deferred until needed
  - Quick commands (`--add-model`, `-p`) short-circuit before heavy setup

### Key CLI Flags

| Flag                           | Handler                                                                                                                                                                                                                                                                     |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `-m, --model`                  | Model selection                                                                                                                                                                                                                                                             |
| `-c, --continue-chat`          | Context loading from previous IDs                                                                                                                                                                                                                                           |
| `-H, --history`                | `history.py`                                                                                                                                                                                                                                                                |
| `-pa, --print-answer`          | `history.py`                                                                                                                                                                                                                                                                |
| `-v, --verbose` / `-vv`        | `chat.py` + `core/engine.py` (verbose / double-verbose traces)                                                                                                                                                                                                              |
| `-ss, --sticky-session`        | `sessions.py`                                                                                                                                                                                                                                                               |
| `-rs, --resume-session`        | `sessions.py`                                                                                                                                                                                                                                                               |
| `-off, -tool-off, --tool-off`  | `chat.py` (runtime tool exclusion, supports `all`)                                                                                                                                                                                                                          |
| `--list-tools`                 | `main.py` (list all LLM tools and exit)                                                                                                                                                                                                                                     |
| `--query-corpus`               | `research_commands.py` (deterministic corpus retrieval, no model call)                                                                                                                                                                                                      |
| `--summarize-section`          | `section_commands.py` (deterministic section list/summary, no main model call)                                                                                                                                                                                              |
| `--section-id`                 | `section_commands.py` (deterministic section selection override)                                                                                                                                                                                                            |
| `--section-include-toc`        | `section_commands.py` (include TOC/debug rows in list mode)                                                                                                                                                                                                                 |
| `-r, --research`               | Enable/promote research mode with optional corpus pointer list                                                                                                                                                                                                              |
| `--shortlist auto\|on\|off`    | Per-run shortlist override                                                                                                                                                                                                                                                  |
| `-sfm, --session-from-message` | `history.py`                                                                                                                                                                                                                                                                |
| `--clean-session-research`     | `sessions.py`                                                                                                                                                                                                                                                               |
| `--xmpp-daemon`                | macOS menubar daemon (`daemon/menubar.py`) or foreground fallback (`daemon/service.py`); on macOS menubar path, duplicate launches are blocked with exit code `1`, and a `~/Applications/AskyDaemon.app` bundle is automatically created/updated for Spotlight integration. |
| `--edit-daemon`                | `daemon_config.py` interactive daemon settings editor                                                                                                                                                                                                                       |
| `persona <subcommand>`         | `persona_commands.py` persona management (create, load, unload, import, export, alias)                                                                                                                                                                                      |

Preset invocation notes:

- first-token `\\name ...` expands using `[command_presets]` from config before normal CLI parsing.
- `\\presets` lists configured command presets and exits.

### Chat Flow (`chat.py`)

Main conversation entry point via `run_chat()`:

1. **Session Identification**: Resolve session variables (`SS`, `RS`, shell-id) and run `_check_idle_session_timeout()` **before** starting the banner.
2. **Mention Parsing**: Parse `@persona_name` syntax from query and load persona before model invocation.
3. **CLI Adaptation**: Parse args into `AskyTurnRequest` + UI callbacks.
4. **API Orchestration**: `AskyClient.run_turn()` performs context/session/preload/model/persist flow.
5. **UI Rendering**: `chat.py` maps API notices/events into Rich output + banner updates.
6. **Interface Side Effects**: optional browser/email/push/report handling (including dynamic sidebar index updates).

Research mode is session-owned:

- Resumed sessions with `research_mode=true` continue in research mode even when `-r` is omitted.
- Passing `-r` on a non-research session promotes and persists that session as research.
- Corpus pointers passed with `-r` replace the session's stored corpus pointer list.
- Follow-up turns in that session reuse persisted corpus/source-mode settings automatically.

Section CLI behavior:

- `--summarize-section` with no value lists canonical body sections by default.
- `--section-include-toc` reveals TOC/micro heading rows for debugging.
- list output includes copy-pastable `section_ref` values (`corpus://cache/<id>#section=<section-id>`).

### Error Handling

- Context overflow errors are surfaced as `ContextOverflowError` from core engine.
- CLI is responsible for user-facing retry guidance and terminal messaging.

### Live Banner Integration

- `InterfaceRenderer` manages Rich Live console
- Status callbacks update during shortlist/tool execution
- Verbose output routed through live console to avoid redraw issues
- Double-verbose (`-vv`) streams boxed main-model request/response payloads live through the active console:
  - outbound request messages (all roles, full payload bodies),
  - inbound response message payloads (including tool-call structures).
- Main-model HTTP transport metadata is merged into those main request/response boxes (no standalone duplicate transport boxes for source=`main_model`).
- Outbound main-model request traces include structured enabled-tool definitions (`name`, required/optional params, description) and enabled tool-guideline lines.
- Preload stage emits a `Preloaded Context Sent To Main Model` panel summarizing seed-document status, selected shortlist URLs, and warnings before the first model call.
- Tool/summarization/shortlist internals in verbose mode are rendered as transport metadata panels (endpoint, status, response type/size) rather than full payload bodies.
- After final answer rendering, research-mode chat keeps Live active during deferred
  history finalization and drains pending background research summaries before the
  last banner refresh/stop so summary-token usage is reflected in the final banner.

## Shell Completion (`completion.py`)

- Argcomplete integration for bash/zsh
- Dynamic completers for history IDs, session names, model aliases
- Preview labels show context in completions
- Lazy-gated by `_ARGCOMPLETE` env var for normal CLI performance

## Display (`display.py`)

- `InterfaceRenderer` class for live banner rendering
- Compact vs full banner modes (configurable)
- Transient status line for tool/shortlist progress
- Token usage display with embedding stats
- Banner totals row always reflects database-wide message/session counts, even when no active session is attached

## Dependencies

```
main.py
├── chat.py → api/client.py
├── presets.py → config/
├── local_ingestion_flow.py → research/adapters.py, research/cache.py, research/vector_store.py
├── research_commands.py → research/tools.py, research/cache.py, local_ingestion_flow.py
├── section_commands.py → research/sections.py, summarization.py, research/cache.py, local_ingestion_flow.py
├── history.py → storage/sqlite.py
├── sessions.py → storage/sqlite.py
├── prompts.py → config/
├── models.py → config/loader.py
└── completion.py → storage/sqlite.py (for completions)
```
