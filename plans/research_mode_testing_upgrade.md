# Plan: Research-Capability Test Strategy Upgrade (Fake + Real Recorded + Live Gate)

## Summary
Current verdict: the existing research recorded tests are only **light smoke tests** and do not validate real research capability depth.

Observed facts:
1. Current research recorded tests rely on `-L/--lean`, which disables tool behavior and preload side effects ([main.py](/Users/evren/code/asky/src/asky/cli/main.py:1090)).
2. The recorded fake backend is keyword-echo logic, so assertions mostly confirm prompt text routing, not research quality ([conftest.py](/Users/evren/code/asky/tests/integration/cli_recorded/conftest.py:53)).
3. The local corpus fixture is tiny and synthetic (2 short files), so corpus realism is low ([conftest.py](/Users/evren/code/asky/tests/integration/cli_recorded/conftest.py:228)).
4. Existing test assertions in the target file are minimal string checks ([test_cli_research_local_recorded.py](/Users/evren/code/asky/tests/integration/cli_recorded/test_cli_research_local_recorded.py:12)).

Chosen direction from your inputs:
1. Keep current fake recorded lane.
2. Add real-model recorded tests (including non-research) with manual cassette refresh.
3. Add a live slow research gate required when research-related files are touched.
4. Commit a realistic multi-file + PDF corpus fixture.

Baselines to preserve/track:
1. Full suite: `1383 passed in 13.34s`.
2. Recorded CLI lane: `14 passed in 6.72s`.

## Important Interface/Contract Changes
1. Add pytest marker: `real_recorded_cli` (real-provider cassette-backed replay tests).
2. Add pytest marker: `live_research` (slow live model research tests, excluded from default suite).
3. Extend recorded refresh workflow to support fake-only and real-provider subsets.
4. Add a repo script for path-scoped mandatory research quality checks.
5. Add committed realistic corpus fixtures under `tests/fixtures`.

## Definition of Done
1. The target file’s tests are upgraded to validate meaningful research/session behavior (not just echoed phrases).
2. A new real-model recorded test file exists and includes:
   - non-research behavior checks,
   - research follow-up subject-awareness regression coverage.
3. A new live slow research test file exists and runs against the real model for capability checks.
4. A path-scoped gate script fails if research-related files changed and required quality checks are not run.
5. Docs (`testing`, `architecture`, `tests guidance`) and devlog are updated.
6. Default `uv run pytest -q` remains fast by excluding recorded/subprocess/live-research lanes.
7. No secrets are stored in cassettes.

## File Plan

### Modify
1. [test_cli_research_local_recorded.py](/Users/evren/code/asky/tests/integration/cli_recorded/test_cli_research_local_recorded.py)
2. [conftest.py](/Users/evren/code/asky/tests/integration/cli_recorded/conftest.py)
3. [helpers.py](/Users/evren/code/asky/tests/integration/cli_recorded/helpers.py)
4. [refresh_cli_cassettes.sh](/Users/evren/code/asky/scripts/refresh_cli_cassettes.sh)
5. [pyproject.toml](/Users/evren/code/asky/pyproject.toml)
6. [tests/AGENTS.md](/Users/evren/code/asky/tests/AGENTS.md)
7. [testing_recorded_cli.md](/Users/evren/code/asky/docs/testing_recorded_cli.md)
8. [ARCHITECTURE.md](/Users/evren/code/asky/ARCHITECTURE.md)
9. [DEVLOG.md](/Users/evren/code/asky/devlog/DEVLOG.md)

### Create
1. [test_cli_real_model_recorded.py](/Users/evren/code/asky/tests/integration/cli_recorded/test_cli_real_model_recorded.py)
2. [conftest.py](/Users/evren/code/asky/tests/integration/cli_live/conftest.py)
3. [test_cli_research_live.py](/Users/evren/code/asky/tests/integration/cli_live/test_cli_research_live.py)
4. [run_research_quality_gate.sh](/Users/evren/code/asky/scripts/run_research_quality_gate.sh)
5. [README.md](/Users/evren/code/asky/tests/fixtures/research_corpus/subject_awareness_v1/README.md)
6. [alpha_overview.md](/Users/evren/code/asky/tests/fixtures/research_corpus/subject_awareness_v1/alpha_overview.md)
7. [beta_risks.txt](/Users/evren/code/asky/tests/fixtures/research_corpus/subject_awareness_v1/beta_risks.txt)
8. [cross_team_notes.md](/Users/evren/code/asky/tests/fixtures/research_corpus/subject_awareness_v1/cross_team_notes.md)
9. [release_appendix.pdf](/Users/evren/code/asky/tests/fixtures/research_corpus/subject_awareness_v1/release_appendix.pdf)
10. New cassette files under [cassettes/](/Users/evren/code/asky/tests/integration/cli_recorded/cassettes/) for real-model recorded tests.

## Before/After by Area

1. Research recorded tests (`test_cli_research_local_recorded.py`)
- Before: lean-mode phrase echo checks.
- After: deterministic assertions on session research-profile persistence + corpus command behavior + section workflow metadata.

2. Recorded backend selection
- Before: fake backend for all in-process recorded tests.
- After: fake backend remains default; `real_recorded_cli` tests run against real-provider config when recording and replay from real-provider cassettes otherwise.

3. Capability realism
- Before: no committed realistic corpus; no PDF fixture.
- After: committed multi-file + PDF corpus used by research tests.

4. Subject-awareness regression coverage
- Before: no test explicitly checks turn-2 query focus shift vs turn-1 inertia.
- After: explicit two-turn research tests in both real-recorded lane and live lane.

5. Mandatory enforcement
- Before: no path-scoped required quality gate script.
- After: path-scoped script triggers fake replay + real replay + live slow checks on research-related changes.

## Sequential Atomic Steps

1. Add fixture corpus (multi-file + PDF) and fixture docs.
- Files: fixture files listed above.
- Verification: `uv run pytest tests/integration/cli_recorded/test_cli_research_local_recorded.py -q -o addopts='-n0 --record-mode=none'`

2. Upgrade fake recorded research tests to meaningful deterministic checks.
- Files: [test_cli_research_local_recorded.py](/Users/evren/code/asky/tests/integration/cli_recorded/test_cli_research_local_recorded.py), [helpers.py](/Users/evren/code/asky/tests/integration/cli_recorded/helpers.py)
- Verification: `uv run pytest tests/integration/cli_recorded/test_cli_research_local_recorded.py -q -o addopts='-n0 --record-mode=none'`

3. Add real-recorded backend path in recorded fixtures.
- Files: [conftest.py](/Users/evren/code/asky/tests/integration/cli_recorded/conftest.py)
- Dependency: Step 1 fixture corpus exists.
- Verification: `uv run pytest tests/integration/cli_recorded/test_cli_real_model_recorded.py -q -o addopts='-n0 --record-mode=none'` (with cassettes present)

4. Add real-model recorded test set (non-research + research subject-awareness).
- Files: [test_cli_real_model_recorded.py](/Users/evren/code/asky/tests/integration/cli_recorded/test_cli_real_model_recorded.py), new cassettes.
- Verification (record once): `ASKY_CLI_RECORD=1 ASKY_CLI_REAL_PROVIDER=1 uv run pytest tests/integration/cli_recorded/test_cli_real_model_recorded.py -q -o addopts='-n0 --record-mode=once'`
- Verification (replay): `uv run pytest tests/integration/cli_recorded/test_cli_real_model_recorded.py -q -o addopts='-n0 --record-mode=none'`

5. Add live slow research capability tests.
- Files: [conftest.py](/Users/evren/code/asky/tests/integration/cli_live/conftest.py), [test_cli_research_live.py](/Users/evren/code/asky/tests/integration/cli_live/test_cli_research_live.py)
- Dependency: Step 1 fixture corpus exists.
- Verification: `uv run pytest tests/integration/cli_live -q -o addopts='-n0 -m live_research'`

6. Wire marker policy and default exclusions.
- Files: [pyproject.toml](/Users/evren/code/asky/pyproject.toml)
- Changes: register `real_recorded_cli`, `live_research`; exclude `live_research` in default addopts.
- Verification: `uv run pytest -q`

7. Extend cassette refresh workflow for fake/real subsets.
- Files: [refresh_cli_cassettes.sh](/Users/evren/code/asky/scripts/refresh_cli_cassettes.sh)
- Verification fake: `./scripts/refresh_cli_cassettes.sh`
- Verification real: `ASKY_CLI_REAL_PROVIDER=1 ./scripts/refresh_cli_cassettes.sh`

8. Add path-scoped mandatory quality gate script.
- Files: [run_research_quality_gate.sh](/Users/evren/code/asky/scripts/run_research_quality_gate.sh)
- Behavior: detect touched files; run required lanes when research scope matches.
- Verification: `./scripts/run_research_quality_gate.sh --base HEAD~1 --head HEAD`

9. Documentation and architecture/devlog updates.
- Files: [tests/AGENTS.md](/Users/evren/code/asky/tests/AGENTS.md), [testing_recorded_cli.md](/Users/evren/code/asky/docs/testing_recorded_cli.md), [ARCHITECTURE.md](/Users/evren/code/asky/ARCHITECTURE.md), [DEVLOG.md](/Users/evren/code/asky/devlog/DEVLOG.md)
- Verification: `rg -n "real_recorded_cli|live_research|research quality gate|subject awareness|refresh" /Users/evren/code/asky/tests/AGENTS.md /Users/evren/code/asky/docs/testing_recorded_cli.md /Users/evren/code/asky/ARCHITECTURE.md /Users/evren/code/asky/devlog/DEVLOG.md`

10. Final runtime and regression validation.
- Verification: `uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=none'`
- Verification: `uv run pytest tests/integration/cli_live -q -o addopts='-n0 -m live_research'`
- Verification: `uv run pytest -q`

## Required Test Scenarios

1. Fake recorded research tests:
- Session research profile persists after follow-up without re-passing `-r`.
- `corpus query` returns stable deterministic table/metadata.
- `corpus summarize` list/error/explicit-source flows produce correct deterministic CLI semantics.

2. Real recorded tests:
- Non-research one-shot instruction-following invariant.
- Non-research session follow-up continuity invariant.
- Research two-turn subject-awareness invariant:
  - turn 1 answers topic A from corpus,
  - turn 2 pivots to topic B without repeating turn-1 focus.

3. Live research tests:
- Multi-file + PDF synthesis answer includes required corpus facts.
- Two-turn subject-awareness with live model and invariant checks.

## Explicit Constraints / Non-Goals

1. No new third-party dependencies.
2. Do not replace existing fake recorded lane.
3. Do not rely on exact full-answer snapshots for long outputs.
4. Do not store secrets in cassettes or committed fixture files.
5. Do not make live-research tests part of default `uv run pytest -q`.
6. Do not remove existing recorded/subprocess markers or workflows.

## Edge Cases as Requirements

1. Missing real-model API key:
- Replay lanes still run.
- Refresh/live commands fail fast with clear error.

2. Cassette drift:
- Replay mismatch must fail clearly and force deliberate refresh/review.

3. Subject-awareness regression:
- If turn 2 repeats turn-1 focus and ignores latest query, tests fail.

4. Corpus ambiguity:
- Section command ambiguous-source path remains explicitly tested.

5. PDF extraction variance:
- Assertions must use invariant terms, not brittle full-string snapshots.

## Assumptions and Defaults

1. Real provider for recorded/live lanes uses OpenRouter with your default Gemini Flash Lite model mapping.
2. Real-recorded cassette refresh is manual; replay is part of scoped PR checks.
3. Research quality gate runs when touched paths include research/CLI-research/session-preload related files.
4. Live lane is marked `slow` and `live_research`, excluded from default full-suite runs.
5. Runtime target: fake recorded lane increase remains proportional; live lane accepted as slower by design.

## Final Checklist

- [ ] Improved research recorded tests now assert meaningful behavior, not just echoed phrases.
- [ ] Real-recorded tests (non-research + research) added with cassettes.
- [ ] Live slow research tests added and pass with real model.
- [ ] Path-scoped mandatory quality gate script added.
- [ ] Refresh workflow supports fake and real subsets.
- [ ] Marker/addopts policy updated without slowing default suite.
- [ ] Docs + architecture + devlog updated.
- [ ] Full suite still passes and runtime deltas are documented against current baselines.
