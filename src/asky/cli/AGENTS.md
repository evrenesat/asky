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
| `daemon_config.py`        | Interactive daemon config editor (entered via `--config daemon edit`) and startup-at-login toggles                                             |
| `openrouter.py`           | OpenRouter API client for model discovery                                                                                                      |
| `terminal.py`             | Terminal context fetching                                                                                                                      |
| `utils.py`                | Query expansion, config printing                                                                                                               |

## Entry Point (`main.py`)

- Parses arguments with `argparse`
  - Help placeholders (`metavar`) are intentionally explicit typed descriptors
    (e.g., `HISTORY_IDS`, `SESSION_SELECTOR`, `LINE_COUNT`) to keep `--help`
    output user-oriented instead of mirroring internal destination names.
  - Top-level `--help` is curated around grouped user-facing commands; corpus-
    specific option details are emitted only from grouped sub-help pages
    (`corpus query --help`, `corpus summarize --help`).
  - Curated top-level help includes concise one-line semantics for key flags
    and grouped operations so users can discover behavior quickly.
  - `--help-all` prints argparse-generated full option reference for power users.
- Routes to appropriate handler based on command flags
- Implements lazy startup for fast CLI response:
  - Completion, imports, DB init are deferred until needed
  - Quick commands (`--config ...`, grouped list/show commands, `-p`) short-circuit before heavy setup

### Key CLI Surface

| Entry                                                | Behavior                                                                                   |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `--config model add` / `--config model edit [alias]` | Model configuration mutation entrypoint                                                    |
| `--config daemon edit`                               | Daemon configuration mutation entrypoint                                                   |
| `history ...`                                        | Grouped history operations (`list/show/delete`)                                            |
| `session ...`                                        | Grouped session operations (`list/show/create/use/end/delete/clean-research/from-message`) |
| `memory ...`                                         | Grouped memory operations (`list/delete/clear`)                                            |
| `corpus query ...` / `corpus summarize ...`          | Grouped deterministic corpus operations                                                    |
| `--session <query...>`                               | Create session named from query text and run query                                         |
| `--tools`                                            | Tool controls (`list`, `off`, `reset`)                                                     |
| `--shortlist on\|off\|reset`                         | Session shortlist override (`on/off`) or clear (`reset`)                                   |
| `--daemon`                                           | macOS menubar daemon (`daemon/menubar.py`) or foreground fallback (`daemon/service.py`)    |
| `--browser <url>`                                    | Browser session flow (Playwright plugin login/session capture path)                        |
| `persona <subcommand>`                               | Persona management (create, load, unload, import, export, alias)                           |

Preset invocation notes:

- first-token `\\name ...` expands using `[command_presets]` from config before normal CLI parsing.
- `\\presets` lists configured command presets and exits.

Grouped command routing notes:

- Recognized grouped domains (`history`, `session`, `memory`, `corpus`, `prompts`) are strict: missing/invalid subcommands do not fall back to query execution.
- `session` (without action) prints grouped session help and current shell-session status.
- `session show` without selector resolves to current shell session (or prints `No active session.` / stale-lock cleanup notice).
- `session clean-research` is session-scoped research cleanup (findings/vectors + session corpus metadata/link rows). It is not a direct purge of shared `research_cache`/chunk/link rows.
- `session delete` removes sessions, their messages, and associated research data. It implicitly runs the same cleanup as `session clean-research` (findings/vectors and upload links) for all deleted sessions.

History command behavior:

- `history list/show/delete` operate across all messages in the unified store and do not filter by session binding.
- Partner expansion for query/answer pairs is still session-scoped (same session for bound messages, global scope for `session_id IS NULL` messages).

### Chat Flow (`chat.py`)

Main conversation entry point via `run_chat()`:

1. **Session Identification**: Resolve session variables (`SS`, `RS`, shell-id) and run `_check_idle_session_timeout()` **before** starting the banner. Shell-session locks persist across process exits in the same shell until explicit end/detach.
2. **Mention Parsing**: Parse `@persona_name` syntax from query and load persona before model invocation.
3. **CLI Adaptation**: Parse args into `AskyTurnRequest` + UI callbacks.
4. **API Orchestration**: `AskyClient.run_turn()` performs context/session/preload/model/persist flow.
5. **UI Rendering**: `chat.py` maps API notices/events into Rich output + banner updates.
6. **Interface Side Effects**: optional browser/email/push/report handling (including dynamic sidebar index updates).

Research mode is session-owned:

`POST_TURN_RENDER` hooks always receive a populated `answer_title` for non-empty answers (markdown title when present, otherwise query-text fallback), including lean mode (`-L`) turns.

Research mode is session-owned:

- Resumed sessions with `research_mode=true` continue in research mode even when `-r` is omitted.
- Passing `-r` on a non-research session promotes and persists that session as research.
- Corpus pointers passed with `-r` replace the session's stored corpus pointer list.
- Follow-up turns in that session reuse persisted corpus/source-mode settings automatically.

Section CLI behavior:

- `--summarize-section` with no value lists canonical body sections by default.
- `--section-include-toc` reveals TOC/micro heading rows for debugging.
- list output includes copy-pastable `section_ref` values (`corpus://cache/<id>#section=<section-id>`).
- positional `--summarize-section <value>` is always `SECTION_QUERY` (strict title/query match fallback), not `SECTION_ID`.
- grouped `corpus summarize <value>` translates to `--summarize-section <SECTION_QUERY>` with identical semantics.
- deterministic ID targeting must use `--section-id <section-id>`; wrappers should not treat positional values as section IDs.

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
  history finalization.

## Shell Completion (`completion.py`)

- Argcomplete integration for bash/zsh
- Dynamic completers for history IDs, session names, model aliases
- Answer-ID completion includes assistant messages from both session-bound and non-session history.
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
