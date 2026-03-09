# RALF Handoff: Single HTML Report Per Session + Summarized Auto Session Titles

## Summary

- Replace keyword-based automatic session naming with one shared short-title summarization flow that produces human-readable session names from the first user query.
- Apply that same auto-naming behavior to both new auto-created sessions and history-to-session conversions.
- Change session-backed HTML reports from append-only per-turn files to one logical report per session.
- Keep timestamps in session report filenames, but treat `session_id` as the overwrite identity via an `_s<id>` suffix.
- Preserve current message/answer title behavior: report display titles still come from `extract_markdown_title(final_answer)` with query fallback; this handoff does not add a new answer-title summarizer.
- Keep non-session history reports append-only, except when a history item is promoted into a session and the matching old single-turn report can be absorbed into that new session report.

## Git Tracking

- Plan Branch: `main`
- Pre-Handoff Base HEAD: `be3d1b1773a830b6960ffbf2e9860a732e3b5965`
- Last Reviewed HEAD: `none`
- Review Log:
  - None yet.

## Done Means

- A newly auto-created session gets a short human-readable summarized name, not the current underscore keyword slug.
- A history item promoted to a session via `--continue`, `--reply`, or `session from-message` gets the same style of auto-generated session name.
- Saving a session report produces exactly one live archive entry per `session_id`; later turns replace that session’s prior report instead of appending a second one.
- Session report filenames follow `<session-slug>_<YYYYMMDD_HHMMSS>_s<session_id>.html`.
- Overwrite matching for sessions is authoritative on `session_id`, not on timestamp, and not on session name alone.
- If the first session turn came from a converted history item and a matching single-turn report exists for that assistant message, that old report is absorbed into the session report instead of remaining as noise.
- Sidebar/index behavior no longer assumes multiple files belong to the same session; each session appears once and uses `asky --resume-session <id>` for copy actions.
- Full suite stays green, and final wall time stays in the same order of magnitude as the current baseline: `1405 passed in 38.99s` (`39.325s` total wall clock from `time uv run pytest -q`).
- Final checklist:
  - [ ] Scoped tests added or updated for naming, overwrite/upsert, and history-conversion absorption.
  - [ ] Full suite passes.
  - [ ] No new dependency added.
  - [ ] No SQLite schema change added.
  - [ ] No debug files or commented-out code remain.
  - [ ] `ARCHITECTURE.md`, `devlog/DEVLOG.md`, and affected subdirectory `AGENTS.md` files are updated if their current text covers the changed behavior.

## Critical Invariants

- Auto session naming must use one shared policy across all automatic creation paths; do not leave one path on keyword extraction and another on summarization.
- Storage-layer code must not start making LLM calls directly; summarization belongs in CLI/API/core orchestration, not in SQLite persistence.
- At most one archive entry and one on-disk HTML file may represent a given `session_id` after a successful save.
- Non-session history reports remain append-only unless that exact history item is promoted into a session and explicitly absorbed.
- Session overwrite matching must use `session_id` when available; session name is display data, not the primary identity key.
- Report display titles remain latest-answer-based; session name summarization and report title generation are separate behaviors.
- Filename timestamp stays present and updates on rewrite; this handoff must not switch to permanently stable timestamp-less session filenames.

## Forbidden Implementations

- Do not key session overwrite matching only on slug or session name.
- Do not put archive filenames or report paths into SQLite tables.
- Do not remove timestamps from session report filenames.
- Do not append a fresh index entry for a session that already has one.
- Do not change non-session report behavior globally just to simplify session logic.
- Do not push LLM summarization into [`sqlite.py`](/Users/evren/code/asky/src/asky/storage/sqlite.py).
- Do not introduce a new JS test framework or new package for this change.

## Checkpoints

### [x] Checkpoint 1: Unify Automatic Session Naming

**Goal:**

- Implement one shared short-title summarization path for automatic session naming and thread it through all auto-created session flows.

**Context Bootstrapping:**

- Run these commands before editing:
- `pwd`
- `git status --short`
- `rg -n "generate_session_name|convert_history_to_session|_build_session_name_from_user_content|session_from_message|--continue" src/asky tests/asky`
- `sed -n '1,260p' src/asky/core/session_manager.py`
- `sed -n '1,120p' src/asky/storage/sqlite.py`
- `sed -n '1975,2045p' src/asky/cli/main.py`
- If this is Checkpoint 1, capture the git tracking values before any edits:
- `git branch --show-current`
- `git rev-parse HEAD`

**Scope & Blast Radius:**

- May create/modify: [`src/asky/core/session_manager.py`](/Users/evren/code/asky/src/asky/core/session_manager.py), [`src/asky/api/session.py`](/Users/evren/code/asky/src/asky/api/session.py), [`src/asky/cli/main.py`](/Users/evren/code/asky/src/asky/cli/main.py), [`src/asky/storage/interface.py`](/Users/evren/code/asky/src/asky/storage/interface.py), [`src/asky/storage/sqlite.py`](/Users/evren/code/asky/src/asky/storage/sqlite.py), [`src/asky/summarization.py`](/Users/evren/code/asky/src/asky/summarization.py), [`src/asky/config/__init__.py`](/Users/evren/code/asky/src/asky/config/__init__.py), [`src/asky/data/config/prompts.toml`](/Users/evren/code/asky/src/asky/data/config/prompts.toml), [`tests/asky/storage/test_sessions.py`](/Users/evren/code/asky/tests/asky/storage/test_sessions.py), [`tests/asky/core/test_feature_reply.py`](/Users/evren/code/asky/tests/asky/core/test_feature_reply.py), [`tests/asky/cli/test_cli_continue.py`](/Users/evren/code/asky/tests/asky/cli/test_cli_continue.py), [`tests/asky/api/test_api_turn_resolution.py`](/Users/evren/code/asky/tests/asky/api/test_api_turn_resolution.py)
- Must not touch: archive rendering behavior, sidebar JS, unrelated plugin/session cleanup logic.
- Constraints: keep storage pure; keep legacy fallback deterministic; preserve existing public CLI flags and API behavior.

**Steps:**

- [ ] Add one shared helper that takes raw first-user-query text, strips the terminal-context wrapper, asks the summarization model for a short plain-text session title, normalizes whitespace/punctuation, and falls back deterministically if the summarizer returns empty or errors.
- [ ] Keep the existing `generate_session_name(...)` call sites working, but change the returned value to a display-ready session title rather than an underscore slug. Filenames will continue to be slugified later by rendering.
- [ ] Add a dedicated short-title prompt/config constant for session naming rather than reusing the long-form answer summary prompt.
- [ ] Extend [`convert_history_to_session(...)`](/Users/evren/code/asky/src/asky/storage/sqlite.py) with an optional `session_name` override so CLI callers can pass the summarized name without moving LLM work into storage.
- [ ] In CLI auto-conversion paths (`--continue`, `--reply`, `session from-message`), compute the summarized session name before or immediately after conversion and persist it through the override/update path so converted sessions use the same naming policy as fresh auto sessions.
- [ ] Preserve deterministic fallback naming for tests or offline/mocked paths where summarization is patched or unavailable.

**Dependencies:**

- Depends on none.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/storage/test_sessions.py tests/asky/core/test_feature_reply.py tests/asky/cli/test_cli_continue.py tests/asky/api/test_api_turn_resolution.py -q`
- Run non-regression tests: `uv run pytest tests/asky/cli/test_cli.py -q`

**Done When:**

- Verification commands pass cleanly.
- New auto-created sessions and converted history sessions both receive the same summarized naming style.
- Storage still has no direct LLM call path.
- A git commit is created with message: `Unify automatic session naming`

**Stop and Escalate If:**

- The only feasible implementation requires LLM calls from storage code.
- The summarization dependency would force auto-naming on non-creation code paths and materially slow normal resumed turns.

### [x] Checkpoint 2: Upsert Session Reports Instead of Appending

**Goal:**

- Make session-backed HTML reports overwrite logically by `session_id`, while keeping timestamped filenames and absorbing eligible converted-history reports.

**Context Bootstrapping:**

- Run these commands before editing:
- `git status --short`
- `rg -n "save_html_report|_save_to_archive|_update_sidebar_index|message_id|session_id" src/asky tests/asky`
- `sed -n '194,390p' src/asky/rendering.py`
- `sed -n '960,1060p' src/asky/cli/chat.py`
- `sed -n '1988,2045p' src/asky/cli/main.py`

**Scope & Blast Radius:**

- May create/modify: [`src/asky/rendering.py`](/Users/evren/code/asky/src/asky/rendering.py), [`src/asky/cli/chat.py`](/Users/evren/code/asky/src/asky/cli/chat.py), [`src/asky/cli/main.py`](/Users/evren/code/asky/src/asky/cli/main.py), [`tests/asky/test_html_report.py`](/Users/evren/code/asky/tests/asky/test_html_report.py), [`tests/asky/cli/test_cli.py`](/Users/evren/code/asky/tests/asky/cli/test_cli.py), [`tests/asky/cli/test_cli_continue.py`](/Users/evren/code/asky/tests/asky/cli/test_cli_continue.py)
- Must not touch: SQLite schema, message persistence format, non-session history rendering semantics outside the explicit conversion-absorb case.
- Constraints: write the new file before deleting the superseded one; keep index metadata source-of-truth in `index.html`; do not rely on filename parsing alone when index metadata already gives `session_id` or `message_id`.

**Steps:**

- [ ] Change session report filename generation to `<slug>_<timestamp>_s<session_id>.html`, where `slug` is built from the current session name and `timestamp` is still refreshed on each save.
- [ ] Teach the report save path to upsert by `session_id`: if an existing session entry/file exists, generate the new timestamped filename, write the replacement file, update the same logical index entry, and delete the superseded session file after the new write succeeds.
- [ ] Thread one CLI-only field through the auto-conversion path to remember the pivot assistant/history message id that was converted into the session.
- [ ] On the first session save after conversion, if no prior session report exists but an index entry exists for that pivot `message_id`, absorb that single-turn report into the new session report instead of leaving both.
- [ ] Keep non-session report creation append-only and unchanged for ordinary one-off turns.
- [ ] Update or add tests that prove: session report rewrite does not append duplicates, timestamped filenames still change across saves, and converted history reports can be absorbed by message id.

**Dependencies:**

- Depends on Checkpoint 1.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/test_html_report.py tests/asky/cli/test_cli.py tests/asky/cli/test_cli_continue.py -q`
- Run non-regression tests: `uv run pytest tests/asky/storage/test_storage.py tests/asky/storage/test_sessions.py -q`

**Done When:**

- Verification commands pass cleanly.
- Repeated saves for the same `session_id` leave one archive entry and one current file for that session.
- The first session turn after history conversion can absorb the matching old single-turn report when its `message_id` matches.
- A git commit is created with message: `Deduplicate session HTML reports`

**Stop and Escalate If:**

- Existing metadata is insufficient to identify the converted history report without adding persistent DB state.
- Safe replace semantics cannot be achieved without risking archive loss on failed writes.

### [x] Checkpoint 3: Remove Sidebar Assumptions About Multi-File Sessions and Update Docs

**Goal:**

- Align sidebar behavior and docs with the new one-report-per-session model and verify full-suite non-regression.

**Context Bootstrapping:**

- Run these commands before editing:
- `git status --short`
- `sed -n '1,220p' src/asky/data/asky-sidebar.js`
- `rg -n "Auto-Naming|session report|sidebar|archive|History" ARCHITECTURE.md devlog/DEVLOG.md src/asky/core/AGENTS.md src/asky/api/AGENTS.md src/asky/cli/AGENTS.md README.md src/asky -g 'README.md'`
- `time uv run pytest -q`

**Scope & Blast Radius:**

- May create/modify: [`src/asky/data/asky-sidebar.js`](/Users/evren/code/asky/src/asky/data/asky-sidebar.js), [`tests/asky/test_html_report.py`](/Users/evren/code/asky/tests/asky/test_html_report.py), [`ARCHITECTURE.md`](/Users/evren/code/asky/ARCHITECTURE.md), [`devlog/DEVLOG.md`](/Users/evren/code/asky/devlog/DEVLOG.md), [`src/asky/core/AGENTS.md`](/Users/evren/code/asky/src/asky/core/AGENTS.md), [`src/asky/api/AGENTS.md`](/Users/evren/code/asky/src/asky/api/AGENTS.md), [`src/asky/cli/AGENTS.md`](/Users/evren/code/asky/src/asky/cli/AGENTS.md), relevant existing README sections only if search finds a directly related section.
- Must not touch: root [`AGENTS.md`](/Users/evren/code/asky/AGENTS.md), unrelated README areas, unrelated JS/CSS styling.
- Constraints: keep sidebar grouping mode for non-session history items if it still adds value, but do not group session items as if multiple files per session still exist.

**Steps:**

- [ ] Update sidebar JS so session-backed entries render as single items keyed by `session_id`, with copy action `asky --resume-session <id>`.
- [ ] Remove or bypass the current grouping path that collapses multiple session files by `session_name`; grouping, if kept, should apply only to non-session history items or other duplicate-free heuristics.
- [ ] Document the new separation of concerns: session names are summarized once, report titles still track the latest answer title, and session reports are upserted instead of appended.
- [ ] Update `ARCHITECTURE.md` for session naming/report archive flow, `devlog/DEVLOG.md` for the delivered change, and the affected subdirectory `AGENTS.md` files only where their current text mentions the changed behavior.
- [ ] Search root and subdirectory README files for an already-relevant archive/session section; update only that existing section if found, otherwise leave README untouched and note why.

**Dependencies:**

- Depends on Checkpoint 2.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/test_html_report.py tests/asky/cli/test_cli.py -q`
- Run non-regression tests: `time uv run pytest -q`

**Done When:**

- Verification commands pass cleanly.
- Sidebar no longer assumes multiple report files for the same session.
- Docs describe only the implemented behavior and do not promise extra archive migration.
- Final suite runtime remains proportionate to the added coverage relative to the current `38.99s` pytest baseline.
- A git commit is created with message: `Update sidebar and docs for single session reports`

**Stop and Escalate If:**

- A meaningful sidebar verification requires introducing a new JS runtime or test framework.
- Existing docs contain conflicting session/archive guidance that cannot be updated without widening scope beyond this handoff.

## Behavioral Acceptance Tests

- Given a new auto-created session from a query like terminal-wrapped or plain text, the stored session name is a short readable title derived from the user query, not a keyword slug such as `debug_pytest_fixture`.
- Given a non-session history answer that is converted into a session via `asky -c ...`, the resulting session gets the same auto-naming style as a fresh session.
- Given multiple turns in the same session, only one HTML archive entry remains associated with that `session_id`, and opening it shows the latest full session transcript including earlier turns.
- Given two saves for the same session, the newer file path has a newer timestamp but still ends in `_s<session_id>.html`, and the older session report file is no longer the live artifact.
- Given a history item that already had a single-turn report and is then converted into a session, the first session report reuses/absorbs that report identity instead of leaving both a history report and a session report behind.
- Given the archive sidebar, a session appears once and copying its command yields `asky --resume-session <session_id>`.
- Given a non-session one-off turn that is never promoted to a session, its report behavior stays append-only and unchanged.

## Plan-to-Verification Matrix

- Automatic session naming is shared across auto-create and conversion.
  Verification: `uv run pytest tests/asky/storage/test_sessions.py tests/asky/core/test_feature_reply.py tests/asky/api/test_api_turn_resolution.py -q`
- Storage remains free of direct LLM/session-title summarization calls.
  Verification: `rg -n "get_llm_msg|_summarize_content|summariz" /Users/evren/code/asky/src/asky/storage`
- Session report identity is one-per-session and keyed by `session_id`.
  Verification: `uv run pytest tests/asky/test_html_report.py -q`
- Session filenames keep timestamp plus `_s<id>` suffix.
  Verification: `uv run pytest tests/asky/test_html_report.py -q`
- Converted history reports can be absorbed into the first session report.
  Verification: `uv run pytest tests/asky/cli/test_cli_continue.py tests/asky/cli/test_cli.py -q`
- Sidebar no longer groups multiple files for one session.
  Verification: `rg -n "item\\.session_name && sessionItem|groupId = item\\.session_name" /Users/evren/code/asky/src/asky/data/asky-sidebar.js`
- Full non-regression and runtime sanity hold.
  Verification: `time uv run pytest -q`

## Assumptions And Defaults

- Session auto-names should be human-readable display titles, not underscore slugs.
- Filename slugs should continue to come from `generate_slug(...)`; session names and filenames are intentionally separate representations.
- Report display titles remain latest-answer-based in this handoff; no change is planned for `extract_markdown_title(final_answer)` behavior.
- Non-session reports stay append-only unless their exact history item is promoted into a session and can be matched by the converted pivot `message_id`.
- No archive backfill/migration is required for pre-existing historical session duplicates beyond the files touched by new saves.
- No new dependency is permitted.
- Because this turn is in non-mutating Plan Mode, this markdown is not being written under `plans/`; before implementation begins, persist this exact handoff under `plans/session-report-dedup-and-session-title-handoff.md` or a collision-safe variant if that filename already exists.
