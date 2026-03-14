# Plan: Reusable `pytest-recording` CLI Integration Framework (V1) + Subprocess Harness

## Summary

Build a two-lane integration framework:

1. **Recorded lane (in-process, default CI/local runs):**
   - Covers one-shot CLI, normal session flows, and research-local flows.
   - Uses `pytest-recording` cassettes in replay mode by default.
   - Uses explicit opt-in env switch for cassette refresh.
   - Freezes prompt datetime for replay-stable LLM request bodies.

2. **Subprocess lane (process realism):**
   - Covers one representative interactive flow now.
   - Adds reusable PTY/subprocess harness for future banner/live-render regression tests.
   - Uses a local fake LLM HTTP server for subprocess tests that need runtime realism, not proxy/requests monkeypatching.

V1 target size: **12-18 tests** (plan below defines **14**).

## Definition of Done

- Running `uv run pytest` executes recorded CLI integration tests by default in replay-only mode.
- Recorded tests fail if cassettes are missing or if unexpected live network is attempted.
- One explicit refresh workflow records/updates cassettes after manual acceptance of model outputs.
- Test helpers allow per-test model alias override with one canonical default alias.
- One subprocess interactive integration test exists and passes.
- PTY harness exists for future banner regression tests.
- Docs and architecture/devlog are updated.
- Full suite still passes; runtime delta is measured against baseline (`1383 passed in 12.21s`, wall `12.764s`).

## Locked Decisions (from you)

- Default mode: replay in CI/local default runs.
- Canonical alias default, with per-test alias override support.
- Assertion style: invariant checks (key expected sentences/regex); exact-output checks only for small outputs.
- V1 scope: core 12-18 tests.
- Research source strategy in V1: local corpus fixtures first.
- V2 direction: add recorded/replayed web search + URL retrieval coverage.
- Boundary: hybrid split.
- Subprocess network strategy: local fake LLM server.
- Include banner harness now for future regression tests.

## Public Interfaces / Contracts Added

1. New test-only env vars:
   - `ASKY_CLI_RECORD=1` enables live cassette refresh path.
   - `ASKY_CLI_MODEL_ALIAS=<alias>` overrides canonical model alias for recorded tests.
   - `ASKY_CLI_FIXED_TIME=<iso8601>` optional override for frozen datetime fixture.
2. New pytest markers:
   - `recorded_cli`
   - `subprocess_cli`
   - `live_record` (used only for refresh commands).
3. New helper API (test-only):
   - `run_cli_inprocess(argv: list[str], env_overrides: dict[str, str] | None) -> CliRunResult`
   - `normalize_cli_output(text: str) -> str`
   - `assert_output_contains_sentences(text: str, sentences: list[str])`
   - `FakeLLMServer` fixture for subprocess lane.
   - `run_cli_subprocess_pty(...)` harness for future live-render/banner regression tests.

## Files To Modify / Create

### Modify
- [pyproject.toml](/Users/evren/code/asky/pyproject.toml)
- [tests/conftest.py](/Users/evren/code/asky/tests/conftest.py)
- [tests/AGENTS.md](/Users/evren/code/asky/tests/AGENTS.md)
- [ARCHITECTURE.md](/Users/evren/code/asky/ARCHITECTURE.md)
- [devlog/DEVLOG.md](/Users/evren/code/asky/devlog/DEVLOG.md)

### Create
- [tests/integration/cli_recorded/conftest.py](/Users/evren/code/asky/tests/integration/cli_recorded/conftest.py)
- [tests/integration/cli_recorded/helpers.py](/Users/evren/code/asky/tests/integration/cli_recorded/helpers.py)
- [tests/integration/cli_recorded/test_cli_one_shot_recorded.py](/Users/evren/code/asky/tests/integration/cli_recorded/test_cli_one_shot_recorded.py)
- [tests/integration/cli_recorded/test_cli_session_recorded.py](/Users/evren/code/asky/tests/integration/cli_recorded/test_cli_session_recorded.py)
- [tests/integration/cli_recorded/test_cli_research_local_recorded.py](/Users/evren/code/asky/tests/integration/cli_recorded/test_cli_research_local_recorded.py)
- [tests/integration/cli_recorded/test_cli_interactive_subprocess.py](/Users/evren/code/asky/tests/integration/cli_recorded/test_cli_interactive_subprocess.py)
- [tests/integration/cli_recorded/cassettes/](/Users/evren/code/asky/tests/integration/cli_recorded/cassettes/)
- [docs/testing_recorded_cli.md](/Users/evren/code/asky/docs/testing_recorded_cli.md)
- [scripts/refresh_cli_cassettes.sh](/Users/evren/code/asky/scripts/refresh_cli_cassettes.sh)

## Before / After (by area)

1. `pytest` config
- Before: no `pytest-recording` dependency or recorded CLI markers.
- After: `pytest-recording` enabled; markers documented; replay-by-default policy enforced via fixtures.

2. CLI integration shape
- Before: integration tests mostly storage/plugin orchestration, minimal real CLI output baselines.
- After: dedicated `cli_recorded` suite for one-shot/session/research-local requests with accepted LLM baselines.

3. Interactive/process realism
- Before: mostly function-level patching of interactive logic.
- After: one subprocess interactive case + reusable PTY harness for future banner regression tests.

4. Determinism
- Before: prompt datetime dynamic (`CURRENT_DATE` varies by minute) can break replay matching.
- After: fixed datetime in recorded lane; stable normalization utilities for output assertions.

## Sequential Atomic Implementation Steps

1. Add dependency and marker scaffolding
- Files: [pyproject.toml](/Users/evren/code/asky/pyproject.toml), [tests/AGENTS.md](/Users/evren/code/asky/tests/AGENTS.md)
- Change: add `pytest-recording` to dev dependency group; define marker docs and refresh policy in tests AGENTS.
- Verification command: `uv sync --group dev && uv run pytest --help | rg "record-mode|vcr"`

2. Add top-level safety gates for recorded suite
- Files: [tests/conftest.py](/Users/evren/code/asky/tests/conftest.py)
- Change: add shared guards for accidental live network when `ASKY_CLI_RECORD` is not set; keep existing HOME/DB isolation behavior.
- Verification command: `uv run pytest tests/integration/cli_recorded -q -n0 --record-mode=none` (expected pass once cassettes exist; fail-fast if missing).

3. Implement recorded-lane fixtures and cassette policy
- Files: [tests/integration/cli_recorded/conftest.py](/Users/evren/code/asky/tests/integration/cli_recorded/conftest.py)
- Change:
  - `vcr_config` fixture with filtered headers (`Authorization`, provider keys).
  - default record mode behavior tied to env guard (`ASKY_CLI_RECORD`).
  - deterministic time fixture freezing prompt time.
  - canonical model alias fixture (`ASKY_CLI_MODEL_ALIAS`, default `gf`).
- Verification command: `uv run pytest tests/integration/cli_recorded -q -n0 -k "not subprocess"`

4. Build reusable helpers for CLI invocation and stable assertions
- Files: [tests/integration/cli_recorded/helpers.py](/Users/evren/code/asky/tests/integration/cli_recorded/helpers.py)
- Change:
  - in-process CLI runner (`sys.argv` patch + stdout/stderr capture).
  - output normalizer stripping ANSI and dynamic timing lines.
  - sentence/regex assertion helpers.
  - fixture utilities for local research corpus fixture documents.
- Verification command: `uv run pytest tests/integration/cli_recorded -q -n0 -k "helper or one_shot"`

5. Add one-shot recorded tests (3 tests)
- Files: [tests/integration/cli_recorded/test_cli_one_shot_recorded.py](/Users/evren/code/asky/tests/integration/cli_recorded/test_cli_one_shot_recorded.py)
- Cases:
  - simple direct question, invariant sentence checks.
  - small-output case with exact normalized output comparison.
  - per-test model override case proving alias override works.
- Verification command: `uv run pytest tests/integration/cli_recorded/test_cli_one_shot_recorded.py -q -n0 --record-mode=none`

6. Add normal-session recorded tests (5 tests)
- Files: [tests/integration/cli_recorded/test_cli_session_recorded.py](/Users/evren/code/asky/tests/integration/cli_recorded/test_cli_session_recorded.py)
- Cases:
  - create session with query.
  - follow-up turn in same session.
  - `session show` transcript integrity.
  - `session end` behavior.
  - grouped command strictness error behavior in session context.
- Verification command: `uv run pytest tests/integration/cli_recorded/test_cli_session_recorded.py -q -n0 --record-mode=none`

7. Add research-local recorded tests (4 tests)
- Files: [tests/integration/cli_recorded/test_cli_research_local_recorded.py](/Users/evren/code/asky/tests/integration/cli_recorded/test_cli_research_local_recorded.py)
- Cases:
  - `-r <local_fixture>` research answer includes expected evidence phrases.
  - follow-up in same research session retains research profile.
  - deterministic corpus query command behavior.
  - section summarize flow behavior with section query/id.
- Verification command: `uv run pytest tests/integration/cli_recorded/test_cli_research_local_recorded.py -q -n0 --record-mode=none`

8. Add subprocess harness and one representative interactive subprocess test (2 tests total in file)
- Files: [tests/integration/cli_recorded/test_cli_interactive_subprocess.py](/Users/evren/code/asky/tests/integration/cli_recorded/test_cli_interactive_subprocess.py)
- Change:
  - add `run_cli_subprocess` and `run_cli_subprocess_pty` utilities.
  - add one interactive flow (model config path) via stdin.
  - add one subprocess smoke using local fake LLM server to verify process-real query roundtrip shape.
- Verification command: `uv run pytest tests/integration/cli_recorded/test_cli_interactive_subprocess.py -q -n0`

9. Record cassettes in explicit refresh mode
- Files: [tests/integration/cli_recorded/cassettes/](/Users/evren/code/asky/tests/integration/cli_recorded/cassettes/), [scripts/refresh_cli_cassettes.sh](/Users/evren/code/asky/scripts/refresh_cli_cassettes.sh)
- Change:
  - record cassettes only under explicit env switch.
  - script sets required env and uses serial run (`-n0`) to avoid cassette write races.
- Verification command:
  - `ASKY_CLI_RECORD=1 uv run pytest tests/integration/cli_recorded -q -n0 --record-mode=once`
  - then replay check: `uv run pytest tests/integration/cli_recorded -q -n0 --record-mode=none`

10. Documentation and architecture/devlog updates
- Files: [docs/testing_recorded_cli.md](/Users/evren/code/asky/docs/testing_recorded_cli.md), [ARCHITECTURE.md](/Users/evren/code/asky/ARCHITECTURE.md), [tests/AGENTS.md](/Users/evren/code/asky/tests/AGENTS.md), [devlog/DEVLOG.md](/Users/evren/code/asky/devlog/DEVLOG.md)
- Change:
  - document lanes, refresh flow, env vars, assertion philosophy, and V2 roadmap.
- Verification command: `rg -n "recorded|cassette|subprocess|banner|refresh" docs ARCHITECTURE.md tests/AGENTS.md devlog/DEVLOG.md`

11. Final validation and runtime comparison
- Command set:
  - `time uv run pytest tests/integration/cli_recorded -q`
  - `time uv run pytest -q`
- Acceptance:
  - all pass
  - runtime delta recorded in devlog vs baseline.

## V1 Test Matrix (14 tests)

1. One-shot simple query invariant assertions.
2. One-shot small-output exact normalized check.
3. One-shot per-test model alias override.
4. Session create + first answer.
5. Session follow-up continuity.
6. Session show transcript structure.
7. Session end behavior.
8. Grouped command strictness in session context.
9. Research local corpus initial answer with expected sentences.
10. Research session follow-up profile persistence.
11. Corpus query deterministic command behavior.
12. Section summarize query path behavior.
13. Interactive subprocess representative flow.
14. Subprocess fake-LLM smoke + PTY harness path validation.

## Explicit Constraints (What NOT to do)

- Do not introduce proxy architecture in V1.
- Do not patch/replace `requests` via PYTHONPATH/sitecustomize tricks in V1.
- Do not include Playwright-based rendering integration in this suite.
- Do not assert huge full-response snapshots for large research outputs.
- Do not allow cassette auto-growth in default runs.
- Do not run cassette refresh in parallel xdist mode.

## Edge Cases as Requirements

- Missing cassette in replay mode must fail clearly.
- Accidental live network in default mode must fail.
- Frozen datetime must be applied to every recorded in-process case.
- ANSI/timing noise must be removed before invariant/exact assertions.
- Session and research tests must isolate DB/home state per test.
- Subprocess harness must tolerate non-TTY and PTY modes.
- Interactive subprocess test must be deterministic without external network.
- Cassettes must redact auth headers and sensitive tokens.

## Assumptions and Defaults

- Canonical model alias default is `gf` unless `ASKY_CLI_MODEL_ALIAS` overrides.
- Recorded lane uses in-process CLI execution due `pytest-recording` subprocess boundary.
- Local corpus fixtures are committed under test data and are stable.
- V1 web/retrieval recorded coverage is deferred; V2 adds those cassettes.
- Banner regression test itself may land after banner fix, but harness lands in V1.

## Verification Commands (stepwise + final)

1. `uv sync --group dev`
2. `uv run pytest tests/integration/cli_recorded -q -n0 --record-mode=none`
3. `ASKY_CLI_RECORD=1 uv run pytest tests/integration/cli_recorded -q -n0 --record-mode=once`
4. `uv run pytest tests/integration/cli_recorded -q -n0 --record-mode=none`
5. `time uv run pytest -q`

## Final Checklist

- [ ] `pytest-recording` dependency added and working.
- [ ] Recorded lane tests run by default in full suite.
- [ ] Explicit refresh workflow implemented and documented.
- [ ] 14 V1 tests implemented and passing.
- [ ] One subprocess interactive test implemented and passing.
- [ ] PTY subprocess harness added for future banner regression tests.
- [ ] Cassettes redact secrets.
- [ ] No large brittle full-output snapshots for research answers.
- [ ] `ARCHITECTURE.md` updated.
- [ ] `tests/AGENTS.md` updated.
- [ ] `devlog/DEVLOG.md` updated with runtime comparison.
