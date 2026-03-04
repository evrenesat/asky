# CLI Integration Testing with `pytest-recording`

The Asky CLI integration tests use a dual-lane strategy to balance deterministic fast feedback and process-realism.

## 1. Recorded Lane (In-Process)
- **Location**: `tests/integration/cli_recorded/`
- **Mechanism**: We use `pytest-recording` (built on VCR.py) to snapshot exact HTTP requests/responses against a local fake OpenAI-compatible endpoint.
- **Default State**: Tests run in `none` record mode. They replay existing cassettes and fail if a cassette is missing or if unexpected network traffic occurs.
- **Default Full Suite Behavior**: `uv run pytest -q` excludes `recorded_cli` and `subprocess_cli` markers by default; run this lane explicitly with `-o addopts=...`.
- **Home Isolation**: All tests run with `HOME`/`ASKY_HOME`/`ASKY_DB_PATH` rooted under `tests/.test_home/` (gitignored), so local user config/database is never touched.
- **Determinism**: The `freeze_time` fixture locks the internal prompt clock, ensuring request bodies remain stable for cassette matching.

### Running Recorded + Subprocess Lane Explicitly

```bash
uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=none'
```

### Refreshing Cassettes
If you modify prompt structures or change test behaviors, explicitly refresh cassettes:

```bash
# Run the refresh script (sets ASKY_CLI_RECORD=1 internally)
./scripts/refresh_cli_cassettes.sh
```

By default, this refresh path does not require external provider keys because recorded tests target the local fake endpoint. If you intentionally switch tests to real-provider recording, set `ASKY_CLI_REAL_PROVIDER=1` and the required provider key.

## 2. Subprocess Lane
- **Location**: `tests/integration/cli_recorded/test_cli_interactive_subprocess.py`
- **Mechanism**: Tests that require actual TTY, interactive prompts, or process boundary realism are executed via `subprocess.Popen` or `pty.openpty()`.
- **Backend**: Instead of VCR, we use a local fake LLM HTTP server to mock model responses securely and quickly without real network requests.

## V2 Roadmap
Currently, V1 focuses on core CLI flags, session continuity, and local research functionality. V2 will expand the recorded suite to cover web search capabilities and more complex tool-calling flows using real web payloads.
