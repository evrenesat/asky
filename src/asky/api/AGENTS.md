# API Package (`asky/api/`)

Programmatic library surface for full asky orchestration without CLI coupling.

## Module Overview

| Module | Purpose |
|--------|---------|
| `client.py` | `AskyClient` orchestration entrypoint |
| `types.py` | Typed request/result dataclasses |
| `context.py` | History selector parsing and context loading |
| `session.py` | Session lifecycle resolution (create/resume/auto/research) |
| `preload.py` | Local-ingestion + shortlist preload pipeline |
| `exceptions.py` | Public error exports |

## Primary Entry Point

Use `AskyClient.run_turn(request)` for CLI-equivalent orchestration:

1. Resolve history context (`context.py`)
2. Resolve session state (`session.py`)
3. Run pre-LLM preload pipeline (`preload.py`)
4. Build messages and execute `ConversationEngine`
5. Generate summaries and persist session/history turns

## Runtime Boundary

- `asky.api` does not render terminal UI.
- Callers pass optional callbacks for status/events/display integration.
- Shell-sticky session lock behavior is injected via optional callbacks, so API
  callers can opt in/out of CLI lock-file semantics.
