# CLI Integration Testing with `pytest-recording`

The Asky CLI research integration tests use three complementary lanes:
- fake recorded replay for fast deterministic guardrails,
- real-provider recorded replay for capability-level regressions without live latency,
- live research checks for slow end-to-end quality gates.

For governance and enforcement details, see:
- `docs/research_testing_strategy.md`

## 1. Fake Recorded Lane (In-Process)
- **Location**: `tests/integration/cli_recorded/`
- **Marker**: `recorded_cli` (excluding `real_recorded_cli`)
- **Mechanism**: `pytest-recording` (VCR.py) snapshots requests/responses against a local fake OpenAI-compatible endpoint.
- **Default State**: Tests run in `none` record mode. They replay existing cassettes and fail if a cassette is missing or if unexpected network traffic occurs.
- **Default Full Suite Behavior**: `uv run pytest -q` excludes `recorded_cli`, `subprocess_cli`, and `live_research` markers by default.
- **Home Isolation**: All tests run with `HOME`/`ASKY_HOME`/`ASKY_DB_PATH` rooted under `tests/.test_home/` (gitignored), so local user config/database is never touched.
- **Determinism**: The `freeze_time` fixture locks the internal prompt clock, ensuring request bodies remain stable for cassette matching.

### Running Fake Recorded Replay

```bash
uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=none' -m "recorded_cli and not real_recorded_cli"
```

### Refreshing Fake Cassettes

```bash
./scripts/refresh_cli_cassettes.sh fake
```

## 2. Real-Provider Recorded Lane
- **Location**: `tests/integration/cli_recorded/test_cli_real_model_recorded.py`
- **Marker**: `real_recorded_cli` (also tagged `recorded_cli`)
- **Mechanism**: Cassettes are recorded against the configured real provider (OpenRouter by default), then replayed offline in `record-mode=none`.
- **Research Coverage Rule**: Real research assertions in this lane must use model-backed `-r <source> <question>` turns. Deterministic `--query-corpus` checks belong in the fake recorded lane.
- **Purpose**: Validate behavior that fake keyword echo cannot cover (instruction following, session continuity, local-corpus fact extraction, and research subject-awareness pivot behavior).

### Running Real Recorded Replay

```bash
ASKY_CLI_REAL_PROVIDER=1 uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=none' -m real_recorded_cli
```

### Refreshing Real-Provider Cassettes

```bash
ASKY_CLI_REAL_PROVIDER=1 ./scripts/refresh_cli_cassettes.sh real
```

This requires `OPENROUTER_API_KEY`. The refresh script fails fast when the key is missing.
For replay runs, set `ASKY_CLI_REAL_PROVIDER=1` so `real_recorded_cli` tests are enabled.

## 3. Subprocess Lane
- **Location**: `tests/integration/cli_recorded/test_cli_interactive_subprocess.py`
- **Mechanism**: Tests that require actual TTY, interactive prompts, or process boundary realism are executed via `subprocess.Popen` or `pty.openpty()`.
- **Backend**: Instead of VCR, we use a local fake LLM HTTP server to mock model responses securely and quickly without real network requests.

## 4. Live Research Gate (Slow)
- **Location**: `tests/integration/cli_live/`
- **Marker**: `live_research` (and `slow`)
- **Mechanism**: Real model, live network, realistic multi-file corpus (including PDFs/EPUB), and model-backed `-r` research turns.
- **Policy**: Excluded from default test runs; required for research-related changes via the gate script.

### Running Live Research Checks

```bash
uv run pytest tests/integration/cli_live -q -o addopts='-n0 -m live_research'
```

### Path-Scoped Mandatory Gate

```bash
./scripts/run_research_quality_gate.sh --base HEAD~1 --head HEAD
```

When research-scoped paths change, this gate runs:
1. fake recorded replay
2. real recorded replay
3. live research checks

Research-scoped paths include `pyproject.toml` because marker registration and default lane exclusion policy live there.

## Enforcement Model

This gate is only enforced when you call it.

Recommended setup:
1. Local `pre-push` hook calls `run_research_quality_gate.sh`.
2. CI job calls the same script and is marked as a required branch protection check.
