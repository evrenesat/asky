# CLI Package (`asky/cli/`)

Command-line interface layer handling argument parsing, command routing, and user interaction.

## Module Overview

| Module | Purpose |
|--------|---------|
| `main.py` | Entry point, argument parsing, command routing |
| `chat.py` | Chat conversation orchestration |
| `completion.py` | Shell completion with argcomplete |
| `display.py` | Banner rendering, live status updates |
| `history.py` | History viewing/deletion commands |
| `sessions.py` | Session management commands |
| `prompts.py` | User prompt listing |
| `models.py` | Interactive model add/edit commands |
| `openrouter.py` | OpenRouter API client for model discovery |
| `terminal.py` | Terminal context fetching |
| `utils.py` | Query expansion, config printing |

## Entry Point (`main.py`)

- Parses arguments with `argparse`
- Routes to appropriate handler based on command flags
- Implements lazy startup for fast CLI response:
  - Completion, imports, DB init are deferred until needed
  - Quick commands (`--add-model`, `-p`) short-circuit before heavy setup

### Key CLI Flags

| Flag | Handler |
|------|---------|
| `-m, --model` | Model selection |
| `-c, --continue-chat` | Context loading from previous IDs |
| `-H, --history` | `history.py` |
| `-pa, --print-answer` | `history.py` |
| `-ss, --sticky-session` | `sessions.py` |
| `-rs, --resume-session` | `sessions.py` |
| `-p, --prompts` | `prompts.py` |
| `--add-model`, `--edit-model` | `models.py` |

## Chat Flow (`chat.py`)

Main conversation entry point via `run_chat()`:

1. **Context Loading**: `load_context()` fetches previous interactions
2. **Source Shortlisting**: Optional pre-LLM source ranking (lazy-loaded)
3. **Message Building**: `build_messages()` constructs the prompt
4. **Engine Invocation**: Passes to `ConversationEngine.run()`
5. **Output Handling**: Saves interaction, optional browser/email/push

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
├── chat.py → core/engine.py, core/session_manager.py
├── history.py → storage/sqlite.py
├── sessions.py → storage/sqlite.py
├── prompts.py → config/
├── models.py → config/loader.py
└── completion.py → storage/sqlite.py (for completions)
```
