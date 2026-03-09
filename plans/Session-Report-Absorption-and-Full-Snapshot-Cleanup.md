# RALF Fix Plan: Complete Session Report Absorption and Full Snapshot Cleanup

## Summary

- Fix the missing converted-history absorption marker for the `--reply` and `session from-message` conversion path so all three conversion entrypoints behave the same.
- Change session report replacement to delete every superseded session snapshot that is being collapsed out of the index, not just the first one.
- Add targeted regression tests for both gaps, then rerun the full suite.

## Git Tracking

- Plan Branch: `main`
- Pre-Handoff Base HEAD: `be3d1b1773a830b6960ffbf2e9860a732e3b5965`
- Last Reviewed HEAD: `e5ae2cc3cff95ba2ae84fb9e148f8183eb9500d4`
- Review Log:
  - 2026-03-09: reviewed `be3d1b1773a830b6960ffbf2e9860a732e3b5965..e5ae2cc3cff95ba2ae84fb9e148f8183eb9500d4`, outcome `changes-requested`

## Checkpoints

### [x] Checkpoint 1: Fix explicit conversion absorption paths

**Goal:**

- Make `--reply` and `session from-message` set the same converted-history marker as `--continue`.

**Context Bootstrapping:**

- Run these commands before editing:
- `git status --short`
- `nl -ba src/asky/cli/main.py | sed -n '2018,2028p'`
- `nl -ba src/asky/cli/main.py | sed -n '2272,2280p'`
- `rg -n "_converted_message_id|session_from_message|reply" tests/asky/cli`

**Scope & Blast Radius:**

- May create/modify: [`src/asky/cli/main.py`](/Users/evren/code/asky/src/asky/cli/main.py), [`tests/asky/cli/test_cli.py`](/Users/evren/code/asky/tests/asky/cli/test_cli.py), [`tests/asky/cli/test_cli_continue.py`](/Users/evren/code/asky/tests/asky/cli/test_cli_continue.py)
- Must not touch: rendering/sidebar code in this checkpoint.
- Constraints: use the same pivot `target_id` already selected for conversion; do not invent a second matching key.

**Steps:**

- [ ] Set `args._converted_message_id = target_id` in the explicit conversion block that handles `--reply` / `session from-message`.
- [ ] Add regression coverage proving all three conversion entrypoints propagate the marker needed for report absorption.
- [ ] Keep current session-name override behavior unchanged.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/cli/test_cli.py tests/asky/cli/test_cli_continue.py -q`
- Run non-regression tests: `uv run pytest tests/asky/test_html_report.py -q`

**Done When:**

- Verification commands pass cleanly.
- `--continue`, `--reply`, and `session from-message` all feed the converted history id into the session-report save path.
- A git commit is created with message: `Fix converted history report absorption paths`

### [ ] Checkpoint 2: Delete all superseded session snapshots

**Goal:**

- Ensure a session save leaves only one physical HTML snapshot for that session, not just one index entry.

**Context Bootstrapping:**

- Run these commands before editing:
- `git status --short`
- `nl -ba src/asky/rendering.py | sed -n '283,405p'`
- `sed -n '190,290p' tests/asky/test_html_report.py`

**Scope & Blast Radius:**

- May create/modify: [`src/asky/rendering.py`](/Users/evren/code/asky/src/asky/rendering.py), [`tests/asky/test_html_report.py`](/Users/evren/code/asky/tests/asky/test_html_report.py)
- Must not touch: naming logic, docs, or plan file content in this checkpoint.
- Constraints: continue writing the new file before unlinking old ones; delete only files that were actually matched as superseded entries for the same session or converted message.

**Steps:**

- [ ] Change `_update_sidebar_index()` to return every superseded filename being removed, not just the first one.
- [ ] Update `_save_to_archive()` to unlink each superseded file after the new session report is written and the index is rewritten.
- [ ] Add a regression test that seeds multiple old session entries/files for the same `session_id` and verifies a new save removes them all.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/test_html_report.py -q`
- Run non-regression tests: `uv run pytest tests/asky/cli/test_cli.py tests/asky/storage/test_sessions.py -q`

**Done When:**

- Verification commands pass cleanly.
- A new save for a session leaves one current HTML file on disk for that `session_id`.
- A git commit is created with message: `Delete all superseded session report snapshots`

### [ ] Checkpoint 3: Final verification and squash readiness

**Goal:**

- Re-verify the whole handoff after the fixes so the next review pass can squash confidently.

**Context Bootstrapping:**

- Run these commands before editing:
- `git status --short`
- `git log --oneline --decorate --no-merges be3d1b1773a830b6960ffbf2e9860a732e3b5965..HEAD`

**Scope & Blast Radius:**

- May create/modify: test files only if a failing regression requires tightening assertions; docs only if behavior wording changed.
- Must not touch: unrelated feature code.
- Constraints: do not squash in this checkpoint; this is the pre-squash validation pass.

**Steps:**

- [ ] Run targeted tests for the fixed paths.
- [ ] Run the full suite.
- [ ] If docs mention “single report per session,” verify the final behavior now fully matches that claim.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/test_html_report.py tests/asky/cli/test_cli.py tests/asky/cli/test_cli_continue.py -q`
- Run non-regression tests: `time uv run pytest -q`

**Done When:**

- Verification commands pass cleanly.
- No remaining review findings block squash.
- A git commit is created with message: `Validate session report dedup follow-up fixes`

## Assumptions And Defaults

- No history rewrite should happen until a follow-up review confirms these fixes.
- The recorded pre-handoff base stays `be3d1b1773a830b6960ffbf2e9860a732e3b5965`.
- The next review should start from `e5ae2cc3cff95ba2ae84fb9e148f8183eb9500d4`.
