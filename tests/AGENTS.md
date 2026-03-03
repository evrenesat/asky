# Tests Directory (`tests/`)

Pytest-based test suite organized to mirror `src/asky`.

## Running Tests

```bash
# Full test suite (parallel by default via `-n auto`)
uv run pytest

# Verbose with output
uv run pytest -v

# Force single-process execution when debugging
uv run pytest -n 0

# Specific component directory
uv run pytest tests/asky/cli

# Specific test file
uv run pytest tests/asky/cli/test_cli.py

# Specific test function
uv run pytest tests/asky/cli/test_cli.py::test_function_name
```

## Layout

- `tests/asky/`: Component and module tests mirroring `src/asky/`
- `tests/asky/api/`: `asky.api` orchestration and preload behavior
- `tests/asky/cli/`: CLI parsing, command routing, inline help, and command handlers
- `tests/asky/core/`: Conversation engine and core runtime contracts
- `tests/asky/daemon/`: Daemon lifecycle, startup, tray/menubar behavior
- `tests/asky/config/`: Config loading and defaults
- `tests/asky/storage/`: SQLite persistence and session lifecycle
- `tests/asky/memory/`: User memory extraction/recall flows
- `tests/asky/research/`: Retrieval/RAG pipelines, shortlist, embeddings, vector store
- `tests/asky/evals/research_pipeline/`: Eval dataset/assertion/matrix/source-provider contracts
- `tests/asky/plugins/`: Shared plugin runtime tests
- `tests/asky/plugins/<plugin_name>/`: Plugin-specific tests (xmpp_daemon, persona_manager, gui_server, transcribers, etc.)
- `tests/integration/`: Cross-component integration tests
- `tests/performance/`: Performance guardrails
- `tests/scripts/`: Script-level tests

## Fixtures (`conftest.py`)

- `tests/conftest.py` remains the shared top-level fixture module.
- Keep common fixtures here unless scope/locality requires a package-level `conftest.py`.

## Conventions

- Prefer test placement that matches source module ownership.
- Keep cross-cutting tests in `tests/integration/` rather than a component bucket.
- Use `@pytest.mark.slow` for tests expected to exceed one second.
- Avoid path-depth assumptions from `__file__`; prefer repository-root discovery by locating `pyproject.toml`.
