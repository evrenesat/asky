# CLI Package (`asky/cli/`)

Command-line interface layer handling argument parsing, command routing, and user interaction.

## Module Overview

| Module                    | Purpose                                                                         |
| ------------------------- | ------------------------------------------------------------------------------- |
| `main.py`                 | Entry point, argument parsing, command routing                                  |
| `chat.py`                 | Chat conversation orchestration                                                 |
| `local_ingestion_flow.py` | Pre-LLM local source preload for research mode (path-redacted local KB context) |
| `shortlist_flow.py`       | Pre-LLM shortlist execution + banner updates                                    |
| `completion.py`           | Shell completion with argcomplete                                               |
| `display.py`              | Banner rendering, live status updates                                           |
| `history.py`              | History viewing/deletion commands                                               |
| `sessions.py`             | Session management commands                                                     |
| `prompts.py`              | User prompt listing                                                             |
| `models.py`               | Interactive model add/edit commands                                             |
| `openrouter.py`           | OpenRouter API client for model discovery                                       |
| `terminal.py`             | Terminal context fetching                                                       |
| `utils.py`                | Query expansion, config printing                                                |

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

| Flag                           | Handler                                       |
| ------------------------------ | --------------------------------------------- |
| `-m, --model`                  | Model selection                               |
| `-c, --continue-chat`          | Context loading from previous IDs             |
| `-H, --history`                | `history.py`                                  |
| `-pa, --print-answer`          | `history.py`                                  |
| `-ss, --sticky-session`        | `sessions.py`                                 |
| `-rs, --resume-session`        | `sessions.py`                                 |
| `-off, -tool-off, --tool-off`  | `chat.py` (runtime tool exclusion)            |
| `-r, --research`               | Enable deep research mode                     |
| `-lc, --local-corpus`          | Explicit local research corpus (implies `-r`) |
| `-sfm, --session-from-message` | `history.py`                                  |
| `--clean-session-research`     | `sessions.py`                                 |

## Chat Flow (`chat.py`)

Main conversation entry point via `run_chat()`:

1. **CLI Adaptation**: Parse args into `AskyTurnRequest` + UI callbacks.
2. **API Orchestration**: `AskyClient.run_turn()` performs context/session/preload/model/persist flow.
3. **UI Rendering**: `chat.py` maps API notices/events into Rich output + banner updates.
4. **Interface Side Effects**: optional browser/email/push/report handling.

### Error Handling

- Context overflow errors are surfaced as `ContextOverflowError` from core engine.
- CLI is responsible for user-facing retry guidance and terminal messaging.

### Live Banner Integration

- `InterfaceRenderer` manages Rich Live console
- Status callbacks update during shortlist/tool execution
- Verbose output routed through live console to avoid redraw issues

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

## Dependencies

```
main.py
├── chat.py → api/client.py
├── local_ingestion_flow.py → research/adapters.py, research/cache.py, research/vector_store.py
├── history.py → storage/sqlite.py
├── sessions.py → storage/sqlite.py
├── prompts.py → config/
├── models.py → config/loader.py
└── completion.py → storage/sqlite.py (for completions)
```
