# Tests Directory (`tests/`)

Pytest suite for `asky`. This file is the short operational guide. For the
full testing architecture, lane wiring, and gating details, read
`tests/ARCHITECTURE.md`.

## Default Run

Plain `uv run pytest` currently means:

```bash
uv run pytest
```

That expands to:

- `-n 3`
- `--record-mode=none`
- `-m "not subprocess_cli and not real_recorded_cli and not live_research"`

So the default lane includes:

- `tests/asky/**`
- `tests/scripts/**`
- `tests/performance/**`
- the fake recorded in-process CLI lane marked `recorded_cli`

The default lane excludes:

- `subprocess_cli`
- `real_recorded_cli`
- `live_research`

On top of that static marker filter, the shared feature-domain plugin may
deselect configured heavy suites based on the current uncommitted git worktree.
Today that dynamic gate only applies to the heaviest research lanes. It does
not exclude fast research unit tests or the fake recorded local-research file.

## Where Tests Belong

- `tests/asky/`: module and package tests that mirror `src/asky/`
- `tests/integration/cli_recorded/`: in-process CLI integration tests and the
  authoritative CLI surface coverage
- `tests/integration/cli_live/`: live provider research capability checks
- `tests/performance/`: performance guardrails
- `tests/scripts/`: script-level tests

Do not put non-CLI wiring tests in `tests/integration/` just because they span
multiple modules. If the public surface under test is not the CLI, prefer the
owning `tests/asky/<package>/` directory.

## Test Lanes

### `tests/asky/**`

- Fast unit/component coverage.
- Runs by default.
- Uses the root sandbox fixtures in `tests/conftest.py`.
- The plain-query helper is disabled by default here unless a test explicitly
  opts in through the existing allowlist or fixture overrides.

### `recorded_cli`

- Lives under `tests/integration/cli_recorded/`.
- Runs by default.
- Uses replay-only `pytest-recording` cassettes with the fake local
  OpenAI-compatible server for the ordinary lane.
- Uses per-test fake HOME/config/database sandboxes under `temp/test_home/`.
- Exercises the real CLI surface in-process via `run_cli_inprocess()`.

Run it explicitly when debugging:

```bash
uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=none' -m "recorded_cli and not real_recorded_cli"
```

### `real_recorded_cli`

- Lives in `tests/integration/cli_recorded/test_cli_real_model_recorded.py`.
- Marked both `recorded_cli` and `real_recorded_cli`.
- Replays committed real-provider cassettes and is intentionally not part of
  the default suite.
- Requires `ASKY_CLI_REAL_PROVIDER=1` even for replay so we do not run it by
  accident in ordinary local loops.

Run it explicitly:

```bash
ASKY_CLI_REAL_PROVIDER=1 uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=none' -m real_recorded_cli
```

### `subprocess_cli`

- Lives in `tests/integration/cli_recorded/test_cli_interactive_subprocess.py`.
- Covers PTY/subprocess realism that the in-process lane cannot.
- Excluded from default runs because startup and terminal handling make it
  slower and more brittle than the in-process lane.

Run it explicitly:

```bash
uv run pytest tests/integration/cli_recorded/test_cli_interactive_subprocess.py -q -o addopts='-n0 --record-mode=none'
```

### `live_research`

- Lives under `tests/integration/cli_live/`.
- Uses the real provider via `OPENROUTER_API_KEY`.
- Marked `live_research` and `slow`.
- Excluded from default runs.
- These tests validate the real model plus the local research/vector pipeline.

Run it explicitly:

```bash
uv run pytest tests/integration/cli_live -q -o addopts='-n0 -m live_research'
```

## Gating Mechanisms

There are two separate gates. Do not mix them up.

### Static marker gate

Configured in `pyproject.toml` through default `addopts`.

- `subprocess_cli`, `real_recorded_cli`, and `live_research` stay out of plain
  `uv run pytest`.
- This is unconditional until the command line overrides `addopts`.

### Dynamic feature-domain gate

Implemented by `asky.testing.pytest_feature_domains`, loaded from
`tests/conftest.py`.

- Reads `[tool.asky.pytest_feature_domains]` from `pyproject.toml`.
- Inspects staged, unstaged, and untracked git paths in the current worktree.
- Deselects configured heavy domain tests when no matching domain paths changed.
- If git state is unavailable, it runs everything.
- `ASKY_PYTEST_RUN_ALL_DOMAINS=1` disables the dynamic gate.
- Explicit test path/node selection bypasses the dynamic deselection for that
  domain.

Today the `research` domain only targets the heavy real-provider research files:

- `tests/integration/cli_live/test_cli_research_live.py`
- `tests/integration/cli_recorded/test_cli_real_model_recorded.py`

Fast research-owned tests still run by default:

- `tests/asky/research/**`
- `tests/asky/evals/research_pipeline/**`
- `tests/integration/cli_recorded/test_cli_research_local_recorded.py`

## Isolation And Sandboxes

All tests must stay off real user state.

- The root sandbox fixture writes under `temp/test_home/<worker>/<pid>/...`.
- It patches `HOME`, `ASKY_HOME`, and `ASKY_DB_PATH`.
- Worker roots are deleted at session start and again at session teardown.
- Recorded/live integration fixtures create their own per-test homes inside the
  worker root and manage their own config files.

If you touch config loading, keep this invariant intact:

- tests must be able to redirect config through `ASKY_HOME`

`src/asky/config/loader.py` now honors `ASKY_HOME` directly. If that behavior
regresses, integration lanes will silently start loading the real user config.

## Recorded CLI Harness Rules

- `tests/integration/cli_recorded/helpers.py` reloads stateful modules before
  each in-process CLI invocation. If you add new long-lived singletons or
  import-time caches that affect CLI behavior, extend that reload/reset path.
- Do not assume the fake recorded lane and the live lane can share process
  state safely without that reset path.
- Keep exhaustive CLI surface assertions in the recorded lane. New public CLI
  flags and subcommands should get coverage there unless they require true PTY
  behavior.
- Do not let ordinary replay tests make live outbound network calls. The root
  network guard exists for that reason.

## Research Gate Script

`scripts/run_research_quality_gate.sh` is the explicit full research gate.

- It uses the same shared feature-domain matcher as pytest.
- When research-scoped files changed, it runs:
  1. fake recorded replay
  2. real recorded replay
  3. live research checks
- It does nothing unless you call it directly or wire it into CI/pre-push.

## Runtime Expectations

- Prefer `-n0` when debugging fixture leakage or import-order issues.
- Use `--durations` when deciding whether a test should be marked `slow`.
- We aim to keep ordinary local tests under one second per case unless the test
  is inherently expensive.
- A live/provider test failing because the provider answered poorly is a lane
  stability problem, not a reason to move more coverage out of the default lane.
