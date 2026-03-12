# Test Architecture

This document explains how the `asky` test suite is split into lanes, how those
lanes are isolated, and which gates decide what runs during a normal local
`uv run pytest`.

## Mental Model

There are three separate concerns:

1. Test placement, which decides where coverage lives.
2. Lane markers, which decide what plain `uv run pytest` excludes every time.
3. Feature-domain deselection, which decides whether a configured heavy domain
   is active for the current git worktree.

If you mix those up, the suite is hard to reason about.

## Directory Shape

The main test buckets are:

- `tests/asky/`: fast component and module coverage mirroring `src/asky/`
- `tests/integration/cli_recorded/`: recorded CLI integration lane
- `tests/integration/cli_live/`: live provider research lane
- `tests/scripts/`: script-level checks
- `tests/performance/`: runtime guardrails
- `tests/fixtures/`: committed corpus and cassette-support fixtures

`tests/integration/` is reserved for real CLI behavior and subprocess realism.
Non-CLI wiring tests belong with the owning package under `tests/asky/`.

## Default Local Command

Plain `uv run pytest` is not "run everything." It means:

```bash
uv run pytest
```

with default `pyproject.toml` addopts:

```text
-n 3 --record-mode=none -m "not subprocess_cli and not real_recorded_cli and not live_research"
```

So the default local suite includes the fast component tests plus the fake
recorded in-process CLI lane, but it does not include subprocess realism, real
provider cassette replay, or the live research lane.

## Lane Breakdown

### Component lane: `tests/asky/**`

Purpose:

- fast ownership-based coverage for modules and packages

Notes:

- runs by default
- uses the shared root fixtures in `tests/conftest.py`
- plain-query helper behavior is disabled by default unless the test opts in

### Fake recorded CLI lane: `recorded_cli`

Purpose:

- exhaustive CLI coverage with deterministic replay

Mechanics:

- lives under `tests/integration/cli_recorded/`
- runs by default
- uses `pytest-recording` in replay-only mode
- uses the fake local OpenAI-compatible endpoint for ordinary recorded cases
- runs CLI commands in-process through `tests/integration/cli_recorded/helpers.py`

Why it exists:

- much faster than subprocess realism
- gives broad CLI surface coverage without live provider cost

### Real recorded CLI lane: `real_recorded_cli`

Purpose:

- replay committed real-provider cassettes for a smaller set of model-backed
  invariants

Mechanics:

- currently centered in `tests/integration/cli_recorded/test_cli_real_model_recorded.py`
- excluded from default runs by marker
- also guarded by `ASKY_CLI_REAL_PROVIDER=1`

Why it exists:

- keeps a real-provider regression lane without paying live network cost during
  ordinary local runs

### Subprocess CLI lane: `subprocess_cli`

Purpose:

- PTY and subprocess behavior that the in-process lane cannot prove

Mechanics:

- centered in `tests/integration/cli_recorded/test_cli_interactive_subprocess.py`
- excluded from default runs by marker

Why it exists:

- shell/TTY behavior is a separate failure mode from normal CLI dispatch

### Live research lane: `live_research`

Purpose:

- real model plus local research/vector pipeline checks

Mechanics:

- lives in `tests/integration/cli_live/`
- excluded from default runs by marker
- requires `OPENROUTER_API_KEY`
- marked `slow`

Why it exists:

- only this lane tells us whether the full live provider plus local research
  stack still behaves end-to-end

## Static Marker Gate

The first gate is static and unconditional.

Configured in `pyproject.toml`:

- exclude `subprocess_cli`
- exclude `real_recorded_cli`
- exclude `live_research`

This is just a local-default policy. If you override `addopts`, those lanes can
run normally.

## Dynamic Feature-Domain Gate

The second gate is dynamic and path-aware.

Implementation:

- plugin: `src/asky/testing/pytest_feature_domains.py`
- shared matcher: `src/asky/testing/feature_domains.py`
- loaded from `tests/conftest.py`

How it works:

1. Read `[tool.asky.pytest_feature_domains]` from `pyproject.toml`.
2. Collect staged, unstaged, and untracked git paths from the current worktree.
3. Mark domains active when changed paths match their `activation_paths`.
4. Deselect collected tests whose domain `test_paths` are inactive.
5. If git state cannot be resolved, fall back to running everything.

Current shipped domain:

- `research`

Current heavy research `test_paths`:

- `tests/integration/cli_live/test_cli_research_live.py`
- `tests/integration/cli_recorded/test_cli_real_model_recorded.py`

Important:

- fast research component tests are not dynamically gated
- fake recorded local-research tests are not dynamically gated
- `ASKY_PYTEST_RUN_ALL_DOMAINS=1` disables the dynamic gate
- explicit path/node selection bypasses deselection for that domain

The dynamic gate is about trimming expensive local feedback loops, not about
hiding most research coverage until CI.

## Research Quality Gate Script

The explicit research gate script is:

```bash
./scripts/run_research_quality_gate.sh
```

It uses the same shared domain matcher as the pytest plugin, but it runs the
full research policy when research-scoped files changed:

1. fake recorded replay
2. real recorded replay
3. live research checks

This script is the place to enforce broader research coverage in CI or a
pre-push hook. Default local pytest stays intentionally lighter.

## Sandboxes And State Isolation

All tests must stay off the real user environment.

### Root sandbox

Defined in `tests/conftest.py`.

- session root: `temp/test_home/<worker>/<pid>/`
- per-test homes under that worker root
- patches:
  - `HOME`
  - `ASKY_HOME`
  - `ASKY_DB_PATH`

Worker roots are deleted at session start and again at teardown. The sandbox was
moved out of `tests/` so pytest does not waste time walking generated fake-home
trees during top-level collection.

### Why `ASKY_HOME` matters

The integration harness relies on config redirection through `ASKY_HOME`.
`src/asky/config/loader.py` must honor that environment variable directly. If
the loader falls back to `Path.home()` first, recorded/live tests start reading
the real user config and failures become misleading.

### Recorded/live per-test homes

The integration fixtures create their own per-test homes inside the worker root:

- recorded: `recorded-<digest>`
- live: `live-<digest>`

They write lane-specific `general.toml`, `models.toml`, `api.toml`,
`research.toml`, and related config files into that sandbox before each test.

## In-Process CLI Reload Strategy

`tests/integration/cli_recorded/helpers.py` is the critical reset point for the
in-process integration lane.

Before each CLI invocation it:

- patches argv/stdin/stdout/stderr
- patches environment and `Path.home()`
- resets plugin runtime cache
- clears research-related singleton instances
- reloads config, storage, plugin, API, research, and CLI modules in a stable order
- recreates the lock directory inside the fake home
- reinitializes SQLite state

If you add a new singleton, import-time cache, or module-level runtime that can
affect CLI behavior across calls, extend this reset path. Otherwise tests from
different lanes can contaminate each other inside one worker process.

## Network Policy

Recorded replay tests should not make live outbound calls.

The root fixture blocks live socket connections for the ordinary recorded lane
unless a cassette refresh workflow explicitly opts into recording.

Live research and real-provider refresh flows are the exception. Those are the
lanes that are allowed to use actual provider credentials.

## Practical Commands

Default suite:

```bash
uv run pytest
```

Single-process debugging:

```bash
uv run pytest -n0
```

Fake recorded lane only:

```bash
uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=none' -m "recorded_cli and not real_recorded_cli"
```

Real recorded replay:

```bash
ASKY_CLI_REAL_PROVIDER=1 uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=none' -m real_recorded_cli
```

Live research:

```bash
uv run pytest tests/integration/cli_live -q -o addopts='-n0 -m live_research'
```

Force all feature domains:

```bash
ASKY_PYTEST_RUN_ALL_DOMAINS=1 uv run pytest
```

## Rules For New Tests

- Put tests in the owning package unless the CLI is the thing under test.
- Add new public CLI flags/subcommands to the recorded CLI lane.
- Use `@pytest.mark.slow` when a test is inherently expected to exceed one
  second.
- Do not move fast research-owned tests behind the dynamic gate just because
  they mention research.
- Prefer path-based feature-domain membership. Use
  `@pytest.mark.feature_domain("name")` only when the path does not describe the
  domain cleanly.
