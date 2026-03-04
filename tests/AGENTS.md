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
- All tests run with HOME/ASKY_HOME/ASKY_DB_PATH rooted under `tests/.test_home/` (gitignored) to prevent any writes to real user configuration.

## Conventions

- Prefer test placement that matches source module ownership.
- Keep cross-cutting tests in `tests/integration/` rather than a component bucket.
- Use `@pytest.mark.slow` for tests expected to exceed one second.
- Avoid path-depth assumptions from `__file__`; prefer repository-root discovery by locating `pyproject.toml`.

## CLI Integration Testing & pytest-recording

The `tests/integration/cli_recorded/` suite uses `pytest-recording` (VCR.py) to snapshot CLI interactions with LLM providers. 

### Custom Markers
- `@pytest.mark.recorded_cli`: Applied to in-process recorded CLI tests.
- `@pytest.mark.subprocess_cli`: Applied to subprocess integration tests (e.g. interactive sessions, PTY realism).
- `@pytest.mark.live_record`: Applied to the cassette refresh workflows. 

### Refresh Policy
- **By default**, tests run in `none` record mode (replay only). Tests will fail if a cassette is missing or live network access is attempted.
- **To refresh cassettes**, you must explicitly opt-in: `ASKY_CLI_RECORD=1 uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=once' -m recorded_cli`
- The project default pytest addopts excludes `recorded_cli` and `subprocess_cli` markers from `uv run pytest -q`. Run this lane explicitly with:
  - `uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=none'`
- Recorded in-process CLI tests target a local fake OpenAI-compatible endpoint for deterministic cassette generation and replay.
- Never allow cassette auto-growth in default runs. Redact sensitive headers/auth tokens in the `vcr_config` fixture.
