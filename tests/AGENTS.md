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
- `@pytest.mark.real_recorded_cli`: Applied to real-provider cassette-backed replay tests under `cli_recorded`.
- `@pytest.mark.subprocess_cli`: Applied to subprocess integration tests (e.g. interactive sessions, PTY realism).
- `@pytest.mark.live_research`: Applied to slow live research capability checks under `tests/integration/cli_live/`.
- `@pytest.mark.live_record`: Applied to the cassette refresh workflows. 

### Refresh Policy
- **By default**, tests run in `none` record mode (replay only). Tests will fail if a cassette is missing or live network access is attempted.
- **To refresh fake cassettes**, run: `./scripts/refresh_cli_cassettes.sh fake`
- **To refresh real-provider cassettes**, run: `ASKY_CLI_REAL_PROVIDER=1 ./scripts/refresh_cli_cassettes.sh real` (requires `OPENROUTER_API_KEY`).
- `real_recorded_cli` replay/record runs are intentionally gated by `ASKY_CLI_REAL_PROVIDER=1`.
- Real-provider recorded and live research assertions must use model-backed `-r <source> <question>` turns. Keep deterministic `--query-corpus` / `corpus query` coverage in the fake recorded lane.
- The project default pytest addopts excludes `recorded_cli`, `subprocess_cli`, and `live_research` markers from `uv run pytest -q`. Run lanes explicitly with:
  - `uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=none' -m "recorded_cli and not real_recorded_cli"`
  - `ASKY_CLI_REAL_PROVIDER=1 uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=none' -m real_recorded_cli`
  - `uv run pytest tests/integration/cli_live -q -o addopts='-n0 -m live_research'`
- Recorded in-process CLI tests target a local fake OpenAI-compatible endpoint for deterministic cassette generation and replay.
- Never allow cassette auto-growth in default runs. Redact sensitive headers/auth tokens in the `vcr_config` fixture.

### Enforcement
- The research quality gate is **not automatic** unless invoked.
- Use `scripts/run_research_quality_gate.sh` in local `pre-push` and CI required checks.
- Treat `pyproject.toml` as research-gate scope because it controls marker registration and default lane exclusions.
- Reference policy/integration examples: `docs/research_testing_strategy.md`.

## Exhaustive CLI Coverage Surface

The `tests/integration/cli_recorded/` suite provides mandatory exhaustive coverage for the Asky CLI:

- **Mandatory**: All new public CLI flags or subcommands MUST have a corresponding test in this lane.
- **Mechanism**: Fast in-process execution (`run_cli_inprocess`) and realism-focused subprocess execution.
- **Determinism**: Matches on stable ports (worker-specific) and request bodies. Time is frozen via fixture.
- **Surface Area**:
  - Chat controls (model selection, turns, lean mode, verbose, system prompts)
  - Session/History management (listing, creation, deletion, resumption, auto-naming)
  - Research/Corpus manual commands (`--query-corpus`, `--summarize-section`)
  - Memory surface (list, delete, clear)
  - Persona surface (create, import/export, aliases, @mentions)
  - Plugin-contributed flags (email, push, browser, daemon)
  - Interactive configuration flows (model add/edit, daemon config)
