# Extra Integration Test Coverage Review Fixes RALF Handoff

## Summary

Fix the review findings from the extra CLI integration coverage handoff so the recorded integration lane stays exhaustive, deterministic, and fast enough to use as a real quality gate.

This follow-up starts from the current reviewed head and is limited to correctness, determinism, and runtime issues introduced by the handoff. Do not broaden scope into unrelated CLI redesigns or new feature work.

## Git Tracking

- Plan Branch: `main`
- Pre-Handoff Base HEAD: `056831a5b11e2a82932c844517d0c2bed81ed812`
- Last Reviewed HEAD: `none`
- Parent Plan: `plans/extra-integration-tests.md`
- Review Log:
  - None yet.

## Review Findings To Fix

1. `tests/integration/cli_recorded/test_cli_interactive_subprocess.py` contains a PTY helper that can wait on a fixed deadline instead of exiting when the child process is done. In replay mode this makes `test_subprocess_fake_llm_smoke` take about 31.6 seconds by itself.
2. `tests/integration/cli_recorded/test_debug.py` and `tests/integration/cli_recorded/cassettes/test_debug/test_debug_db.yaml` were committed as debug artifacts and are not part of the intended CLI surface.
3. `tests/integration/cli_recorded/cli_surface.py` and `tests/integration/cli_recorded/test_cli_surface_manifest.py` do not make the manifest authoritative for the full promised surface. Coverage ownership is incomplete and there is no failing test that proves every required surface item has an owner.
4. `tests/integration/cli_recorded/conftest.py` enables a broad plugin roster for every recorded test, including heavier plugins that most tests do not need. This increases setup cost and makes the harness less obviously deterministic.
5. `tests/integration/cli_recorded/test_cli_plugin_surface_recorded.py` patches the daemon service method instead of the foreground launcher actually called by CLI dispatch.
6. `devlog/DEVLOG.md` and `docs/testing_recorded_cli.md` contain statements that do not match the verified code state or current command results:
   - the recorded lane count is stale,
   - the docs/devlog claim VCR body matching, but `vcr_config` currently does not match on `body`.

## Done Means

- `uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=none'` passes cleanly.
- The recorded replay lane no longer contains any accidental debug tests or debug cassettes.
- `test_subprocess_fake_llm_smoke` exits promptly after the child exits and no longer burns tens of seconds on idle PTY polling.
- No new or modified test in this handoff exceeds one second unless it is inherently slow and explicitly marked `@pytest.mark.slow`.
- The CLI surface manifest is truly authoritative:
  - every required public top-level flag has an owner,
  - every required grouped command has an owner,
  - every required persona subcommand has an owner,
  - every required plugin-contributed flag has an owner,
  - hidden internal translators are excluded only through an explicit mapping.
- The manifest tests fail if a supported public surface item exists without ownership.
- Plugin dispatch tests stub the real final call boundary that the CLI invokes.
- Docs and devlog state only facts that were re-verified in this handoff.
- Final verification is green:
  - `/usr/bin/time -p uv run pytest -q`
  - `uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=none' --durations=20`
  - `uv run pytest tests/integration/cli_recorded/test_cli_interactive_subprocess.py -q -o addopts='-n0 --record-mode=none'`
  - if `tests/integration/cli_recorded/conftest.py` changes, also run `ASKY_CLI_REAL_PROVIDER=1 uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=none' -m real_recorded_cli`

## Files

Modify only these files unless a verification step proves another file must change:

- `tests/integration/cli_recorded/test_cli_interactive_subprocess.py`
- `tests/integration/cli_recorded/conftest.py`
- `tests/integration/cli_recorded/cli_surface.py`
- `tests/integration/cli_recorded/test_cli_surface_manifest.py`
- `tests/integration/cli_recorded/test_cli_plugin_surface_recorded.py`
- `docs/testing_recorded_cli.md`
- `devlog/DEVLOG.md`

Delete:

- `tests/integration/cli_recorded/test_debug.py`
- `tests/integration/cli_recorded/cassettes/test_debug/test_debug_db.yaml`

Search first before touching anything else:

- `rg -n "recorded_cli|subprocess_cli|real_recorded_cli|body matching|match_on|test_debug|run_daemon_foreground|run_foreground" tests docs devlog src/asky`

## Before / After Expectations

- `tests/integration/cli_recorded/test_cli_interactive_subprocess.py`
  - Before: `run_cli_subprocess_pty()` polls until a fixed deadline and the smoke test spends about 31 seconds in replay mode.
  - After: the PTY helper stops reading as soon as the child has exited and the PTY is drained, with explicit bounded waits and a failure message if the child hangs.

- `tests/integration/cli_recorded/conftest.py`
  - Before: one global recorded harness enables a wide plugin set for every test and claims determinism that is broader than required by most tests.
  - After: the default recorded harness is minimal and deterministic, with only the plugin/config enablement needed by shared tests. Surfaces that need extra plugins must opt in through explicit helper/config setup instead of paying that cost globally.

- `tests/integration/cli_recorded/cli_surface.py`
  - Before: the manifest inventories the public surface, but ownership is only partial.
  - After: one explicit ownership map covers the full required surface, including top-level flags, grouped commands, persona subcommands, and plugin flags.

- `tests/integration/cli_recorded/test_cli_surface_manifest.py`
  - Before: parity tests only compare parser/plugin surfaces to the manifest inventory and use a subprocess `uv run asky persona --help` call that costs about 2.9 seconds.
  - After: tests also assert ownership completeness and use direct parser/plugin inspection instead of a CLI subprocess where possible.

- `tests/integration/cli_recorded/test_cli_plugin_surface_recorded.py`
  - Before: the daemon test patches `DaemonService.run_foreground`, which is not the symbol imported by CLI dispatch.
  - After: the test patches the actual launcher boundary used by `src/asky/cli/main.py` and asserts the expected call arguments or dispatch behavior.

- `docs/testing_recorded_cli.md` and `devlog/DEVLOG.md`
  - Before: counts and body-matching claims are stale/inaccurate.
  - After: both documents match the final verified implementation and exact commands run in this handoff.

## Assumptions To Keep Explicit

- Python and pytest behavior should stay aligned with the current repo toolchain under `uv`; do not add dependencies.
- The default full suite currently passes on this head: `/usr/bin/time -p uv run pytest -q` -> `1409 passed in 51.40s` (`real 52.00`).
- Current recorded replay lane passes but is too slow: `53 passed, 5 skipped in 46.02s`, dominated by `test_subprocess_fake_llm_smoke` at about `31.59s`.
- The fake recorded lane still uses the shared local fake OpenAI-compatible endpoint and should remain the default deterministic path.
- If body matching is truly required for correctness, prove it with a failing replay case before changing `vcr_config`; otherwise fix the docs instead of changing cassette semantics.

## Constraints

- Do not change user-facing CLI behavior unless a test first proves an actual supported-behavior bug.
- Do not add or remove pytest markers, default addopts, or performance thresholds.
- Do not leave print-based debugging, ad hoc debug tests, or extra cassettes in the tree.
- Do not use subprocess shellouts in manifest/meta tests when direct parser inspection can provide the same signal.
- Do not enable heavyweight plugins globally if a smaller per-test or helper-level setup can cover the surface.
- Do not rewrite or refresh real-provider cassettes unless a shared recorded helper change breaks replay and the replay command proves it.
- Do not modify `ARCHITECTURE.md`, `pyproject.toml`, `scripts/**`, or root `AGENTS.md` in this fix handoff unless a verification step proves a documented statement is false and cannot be corrected in narrower docs.

## Edge Cases That Are Requirements

- PTY subprocess tests must fail quickly and diagnostically if the child hangs; they must not silently sit until a hardcoded long timeout.
- Interactive config tests must work both in isolated single-test runs and in the full subprocess file run.
- The ownership-completeness check must treat hidden internal flags only through the explicit translator mapping, not via broad ignore lists.
- Plugin surface tests must not contact real SMTP, webhook, browser automation, or daemon services.
- If reducing the default plugin roster breaks persona or other existing recorded tests, move that setup into the smallest shared helper or fixture that still preserves determinism.
- Verification notes in `DEVLOG.md` must use the actual post-change counts and runtimes from commands run in this handoff.

## Checkpoints

### [x] Checkpoint 1: Remove Artifacts And Fix Slow Subprocess Behavior

**Objective**

- Eliminate accidental debug coverage and bring the subprocess lane back to reasonable runtime without changing supported CLI behavior.

**Files**

- Modify: `tests/integration/cli_recorded/test_cli_interactive_subprocess.py`
- Delete: `tests/integration/cli_recorded/test_debug.py`
- Delete: `tests/integration/cli_recorded/cassettes/test_debug/test_debug_db.yaml`

**Steps**

1. Delete the debug test and its cassette.
2. Refactor the PTY helper so it exits when the child process has terminated and no more PTY output remains, instead of waiting on a fixed long deadline.
3. Keep explicit short timeouts and emit useful assertion context if the child does not exit.
4. Re-run only the subprocess file and confirm the smoke test no longer dominates runtime.

**Verification**

- `uv run pytest tests/integration/cli_recorded/test_cli_interactive_subprocess.py -q -o addopts='-n0 --record-mode=none' --durations=10`
- `rg -n "test_debug|DEBUG|print\\(" tests/integration/cli_recorded`

### [ ] Checkpoint 2: Minimize The Recorded Harness And Fix Boundary Patching

**Objective**

- Keep the shared recorded environment deterministic while avoiding unnecessary plugin startup cost and patching the real CLI call boundaries.

**Files**

- Modify: `tests/integration/cli_recorded/conftest.py`
- Modify: `tests/integration/cli_recorded/test_cli_plugin_surface_recorded.py`

**Steps**

1. Identify which recorded tests truly need each plugin.
2. Reduce the default plugin config to the smallest safe set.
3. Introduce the narrowest helper or fixture needed for tests that require extra plugin enablement.
4. Patch daemon dispatch at the launcher boundary actually imported by CLI code.
5. Re-run the plugin surface tests and a representative recorded subset that exercises personas and research fixtures.

**Verification**

- `uv run pytest tests/integration/cli_recorded/test_cli_plugin_surface_recorded.py -q -o addopts='-n0 --record-mode=none'`
- `uv run pytest tests/integration/cli_recorded/test_cli_persona_recorded.py tests/integration/cli_recorded/test_cli_research_local_recorded.py -q -o addopts='-n0 --record-mode=none'`

### [ ] Checkpoint 3: Make The Manifest Authoritative And Cheap To Run

**Objective**

- Ensure manifest drift fails mechanically for the full required CLI surface, without paying a subprocess startup cost for metadata tests.

**Files**

- Modify: `tests/integration/cli_recorded/cli_surface.py`
- Modify: `tests/integration/cli_recorded/test_cli_surface_manifest.py`

**Steps**

1. Expand ownership data so every required surface item from the parent plan is covered.
2. Add a test that asserts ownership completeness across the union of public flags, grouped commands, persona subcommands, and plugin flags, excluding only mapped hidden translators.
3. Replace persona subprocess-help scraping with direct parser/subparser inspection or another in-process mechanism that matches existing test patterns.
4. Keep failure messages specific so a future CLI addition tells the implementer exactly which surface item lacks ownership.

**Verification**

- `uv run pytest tests/integration/cli_recorded/test_cli_surface_manifest.py -q -o addopts='-n0 --record-mode=none' --durations=10`
- `uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=none' --durations=20`

### [ ] Checkpoint 4: Repair Documentation Truthfulness And Final Verification

**Objective**

- Make the docs and devlog match the final verified code state and record the real post-fix runtime.

**Files**

- Modify: `docs/testing_recorded_cli.md`
- Modify: `devlog/DEVLOG.md`

**Steps**

1. Update the recorded-lane guidance only where the implementation actually changed.
2. Remove or correct any stale claims about counts, VCR body matching, or lane behavior.
3. Record the final exact command outputs and runtimes in `DEVLOG.md`.
4. Run the full verification matrix and stop if any lane regresses.

**Verification**

- `/usr/bin/time -p uv run pytest -q`
- `uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=none' --durations=20`
- `uv run pytest tests/integration/cli_recorded/test_cli_interactive_subprocess.py -q -o addopts='-n0 --record-mode=none'`
- `ASKY_CLI_REAL_PROVIDER=1 uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=none' -m real_recorded_cli`
  - Run this last command only if `tests/integration/cli_recorded/conftest.py` changed.

## Final Checklist

- [ ] No debug test files or debug cassettes remain under `tests/integration/cli_recorded/`.
- [ ] The subprocess smoke test no longer waits on a fixed long PTY deadline.
- [ ] No modified test exceeds one second unless explicitly justified and marked slow.
- [ ] Manifest ownership covers the entire required CLI surface.
- [ ] Manifest tests use in-process inspection wherever practical.
- [ ] Plugin dispatch tests patch the actual final boundary called by CLI code.
- [ ] Recorded replay lane passes in `record-mode=none`.
- [ ] Full suite passes and the total runtime is recorded.
- [ ] Docs and devlog only claim behavior verified in this handoff.
- [ ] No new dependencies, marker changes, or performance-threshold changes were introduced.
