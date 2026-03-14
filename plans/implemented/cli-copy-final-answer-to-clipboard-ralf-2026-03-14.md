# RALF Handoff Plan: Copy Final Answer To Clipboard CLI Flag

## Summary

Add a new core CLI output-delivery flag pair, `-cc` and `--copy-clipboard`, that copies the raw model final answer text to the system clipboard after the answer has already been rendered to the terminal.

This must be implemented as a core CLI flag, not as a plugin. The copy path must use the existing `pyperclip` dependency for writes (`pyperclip.copy(...)`), mirroring the project's existing clipboard-read usage.

Failure policy is fixed:

- The final answer still prints normally.
- The command still exits successfully.
- The CLI prints a short, readable warning with the clipboard failure reason.
- No traceback, no exception dump, and no process abort for clipboard-write failures.

The documentation update is limited to existing relevant docs:

- update the existing `README.md` `Basic Usage` section with a clipboard-oriented example and the requested alias example
- update `src/asky/cli/AGENTS.md` for the new CLI/output-delivery behavior
- update `devlog/DEVLOG.md`

Do not add a new plugin, new dependency, or a new top-level README section for this work.

## Git Tracking

- Plan Branch: `main`
- Pre-Handoff Base HEAD: `708e1400174709a2224f0231e56f4d4900d9587d`
- Last Reviewed HEAD: `approved+squashed; finalized plan intentionally omits the post-squash SHA`
- Review Log:
  - 2026-03-14: Reviewed the original handoff range from `708e1400174709a2224f0231e56f4d4900d9587d` through the three checkpoint commits (`Add clipboard copy flag`, `Cover clipboard flag in help and CLI surface`, `Document clipboard copy flag`), outcome `approved+squashed`.

## Done Means

The work is done only when all of the following are true:

- `asky -cc ...` and `asky --copy-clipboard ...` are accepted as public top-level CLI flags.
- The flag lives in the core output-delivery CLI surface beside `--open`, not in plugin code.
- On a successful turn with a non-empty final answer, the exact raw `turn_result.final_answer` string is copied to the clipboard.
- The answer is rendered first; clipboard copy happens after render.
- If clipboard copy fails, the answer still remains visible, exit status stays successful, and the CLI emits only a light readable warning that includes the failure reason.
- No clipboard copy is attempted when there is no final answer or when the turn halts before rendering.
- The new flag appears in argparse full help, curated top-level help, and the recorded CLI surface manifest.
- Automated coverage proves success and failure behavior without depending on a real clipboard backend.
- `README.md` contains the improved alias example in an already existing relevant section.
- `src/asky/cli/AGENTS.md` and `devlog/DEVLOG.md` are updated.
- Final verification completes with the full suite, and the resulting runtime is compared against the current baseline:
  - `time uv run pytest` -> `1510 passed in 16.33s`, `real 16.609s`

## Critical Invariants

- The copied text must be the raw final answer string, not rendered Rich output, not HTML report content, and not a title/excerpt.
- Clipboard failure must not change the success/failure outcome of an otherwise successful query.
- Clipboard failure output must stay user-readable and traceback-free.
- The implementation must use `pyperclip.copy(...)`; do not add OS-specific subprocess clipboard calls.
- The flag must remain a core public CLI flag and be included in the CLI surface manifest and help surfaces.
- Existing output-delivery features (`--open`, plugin `--sendmail`, plugin `--push-data`) must keep their current behavior.
- Existing tests that construct partial `argparse.Namespace` objects must not be broken by direct attribute access; use `getattr(..., False)` outside parse-only code where needed.
- Lean mode behavior must remain intact: no banner, answer still prints, clipboard copy still uses the final answer text if requested.

## Forbidden Implementations

- Do not implement this as a new plugin.
- Do not add a new dependency or require new system packages in the repository to make clipboard writes work.
- Do not copy the query text, markdown title, HTML report body, or any post-processed display string instead of the raw final answer.
- Do not raise, rethrow, `sys.exit(1)`, or mark the turn failed because clipboard copy failed.
- Do not print a traceback or raw exception repr block to the terminal for clipboard failures.
- Do not bypass help/discoverability coverage by adding the parser flag without updating the manifest/help surfaces.
- Do not add a new README section solely for this feature.
- Do not modify the root `AGENTS.md`.

## Checkpoints

### [x] Checkpoint 1: Core Flag And Clipboard Write Path

**Goal:**

- Add the new core CLI flag and wire clipboard copy into the post-render CLI flow with the fixed warning-only failure behavior.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `sed -n '1,220p' AGENTS.md`
- `sed -n '1,240p' src/asky/cli/AGENTS.md`
- `sed -n '1,220p' ARCHITECTURE.md`
- `sed -n '1,220p' devlog/DEVLOG.md`
- `sed -n '760,1105p' src/asky/cli/main.py`
- `sed -n '900,1105p' src/asky/cli/chat.py`
- `sed -n '1,180p' src/asky/cli/utils.py`
- If this is Checkpoint 1, capture the git tracking values before any edits:
- `git branch --show-current`
- `git rev-parse HEAD`

**Scope & Blast Radius:**

- May create/modify:
  - `src/asky/cli/main.py`
  - `src/asky/cli/chat.py`
  - `src/asky/cli/utils.py`
  - `tests/asky/cli/test_cli.py`
- Must not touch:
  - `src/asky/plugins/**`
  - `src/asky/api/**`
  - `src/asky/core/**`
  - `root AGENTS.md`
- Constraints:
  - Add `-cc` and `--copy-clipboard` as a core parser argument in the output-delivery group near `--open`.
  - Use a small helper in `src/asky/cli/utils.py` for clipboard writing so pyperclip access is centralized.
  - The helper must not print by itself; it should return success/failure information to the caller.
  - `run_chat()` must copy only when `final_answer` is truthy and the flag is enabled.
  - The warning must be emitted after the answer has already rendered.
  - The warning style should be light and readable, for example a single yellow warning line using Rich, not a red error block.
  - The warning may include the backend-provided reason string, but no traceback.
  - Use `getattr(args, "copy_clipboard", False)` where manual test namespaces might not include the new attribute.

**Steps:**

- [x] Step 1: Add `-cc` / `--copy-clipboard` to the core CLI parser in `src/asky/cli/main.py`, placing it in the output-delivery group with help text that clearly states it copies the final answer to the clipboard.
- [x] Step 2: Add a `copy_text_to_clipboard(text: str) -> str | None` style helper in `src/asky/cli/utils.py` that calls `pyperclip.copy(text)` and returns `None` on success or a short reason string on failure.
- [x] Step 3: Update `src/asky/cli/chat.py` so that after a successful non-empty final answer has been rendered, and before the function exits, it conditionally attempts the clipboard copy and prints a single readable warning when the helper returns a failure reason.
- [x] Step 4: Add focused unit coverage in `tests/asky/cli/test_cli.py` for:
  - parse acceptance of both spellings
  - successful clipboard write with the exact final answer string
  - clipboard failure warning path without crashing
  - no copy attempt when `final_answer` is empty or the turn is halted
  - lean mode copy path if the existing test harness can cover it without extra complexity

**Dependencies:**

- Depends on no previous checkpoint.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/cli/test_cli.py -q -n0`
- Run non-regression tests: `uv run pytest tests/asky/plugins/test_plugin_manager.py -q -n0`

**Done When:**

- Verification commands pass cleanly.
- `asky -cc ...` and `asky --copy-clipboard ...` both parse.
- The exact raw final answer is passed to `pyperclip.copy(...)` when enabled.
- Clipboard copy failures only produce a light warning and do not abort the command.
- A git commit is created with message: `Add clipboard copy flag`

**Stop and Escalate If:**

- Implementing the write path appears to require a new dependency, a new plugin, or an OS-specific subprocess clipboard command.
- The only viable hook point would require changing API/core behavior rather than the CLI layer.
- The warning requirement cannot be met without breaking the existing post-render flow semantics.

### [x] Checkpoint 2: Help Surfaces, Manifest, And Recorded CLI Coverage

**Goal:**

- Make the new public flag discoverable everywhere this codebase requires, and cover the public surface in the recorded CLI lane.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `sed -n '100,260p' src/asky/cli/help_catalog.py`
- `sed -n '1,280p' tests/integration/cli_recorded/cli_surface.py`
- `sed -n '1,220p' tests/integration/cli_recorded/test_cli_chat_controls_recorded.py`
- `sed -n '1,220p' tests/asky/cli/test_help_discoverability.py`

**Scope & Blast Radius:**

- May create/modify:
  - `src/asky/cli/help_catalog.py`
  - `tests/integration/cli_recorded/cli_surface.py`
  - `tests/integration/cli_recorded/test_cli_chat_controls_recorded.py`
- Must not touch:
  - plugin manifest ownership for unrelated flags
  - recorded cassettes unless a new networked interaction becomes absolutely necessary
- Constraints:
  - The curated top-level help should expose the new flag under the output-delivery surface, alongside `--open`.
  - The public CLI surface manifest must include both `-cc` and `--copy-clipboard`.
  - Coverage ownership for both spellings must map to `test_cli_chat_controls_recorded.py`.
  - Recorded CLI tests must mock `pyperclip.copy`; they must not depend on a working real clipboard backend.
  - Do not move this flag into `PLUGIN_FLAGS`.

**Steps:**

- [x] Step 1: Update `src/asky/cli/help_catalog.py` so curated top-level help shows `-cc, --copy-clipboard` in the output-delivery section.
- [x] Step 2: Update `tests/integration/cli_recorded/cli_surface.py` to add both public spellings to `PUBLIC_TOP_LEVEL_FLAGS` and `COVERAGE_OWNERSHIP`.
- [x] Step 3: Add recorded CLI coverage in `tests/integration/cli_recorded/test_cli_chat_controls_recorded.py` that patches `pyperclip.copy`, runs a one-shot query with `-cc`, asserts exit code `0`, and verifies the copy function was called with the returned answer text.
- [x] Step 4: If needed, add an additional recorded assertion that a mocked clipboard failure still leaves the answer in stdout and emits the warning text without a traceback.

**Dependencies:**

- Depends on Checkpoint 1.

**Verification:**

- Run scoped tests: `uv run pytest tests/integration/cli_recorded/test_cli_chat_controls_recorded.py -q -o addopts='-n0 --record-mode=none'`
- Run non-regression tests: `uv run pytest tests/asky/cli/test_help_discoverability.py tests/integration/cli_recorded/test_cli_surface_manifest.py -q -n0`

**Done When:**

- Verification commands pass cleanly.
- The new flag appears in curated help and `--help-all`.
- The public CLI manifest includes the new flag and its ownership is assigned.
- Recorded CLI coverage proves the clipboard copy path without requiring a real clipboard backend.
- A git commit is created with message: `Cover clipboard flag in help and CLI surface`

**Stop and Escalate If:**

- Making the flag discoverable requires a broader CLI help contract change than a normal surface addition.
- Recorded CLI coverage cannot verify the clipboard path without introducing brittle environment-specific behavior.

### [x] Checkpoint 3: Documentation Parity, Devlog, And Final Verification

**Goal:**

- Update the existing relevant docs, record the behavior change, and close the handoff with full-suite verification and runtime comparison.

**Context Bootstrapping:**

- Run these commands before editing:
- `cd /home/evren/code/asky`
- `sed -n '1,220p' README.md`
- `sed -n '1,240p' src/asky/cli/AGENTS.md`
- `sed -n '1,240p' devlog/DEVLOG.md`
- `time uv run pytest`

**Scope & Blast Radius:**

- May create/modify:
  - `README.md`
  - `src/asky/cli/AGENTS.md`
  - `devlog/DEVLOG.md`
- Must not touch:
  - `ARCHITECTURE.md`
  - root `AGENTS.md`
  - unrelated docs files
- Constraints:
  - Update only an already relevant README section. Use the existing `Basic Usage` area; do not add a new README section just for this feature.
  - Include the requested alias example with an improved prompt tuned for command-only terminal usage.
  - Keep the alias example shell-safe and readable.
  - `src/asky/cli/AGENTS.md` should mention the new output-delivery flag and that clipboard copy is a post-render CLI-side behavior.
  - `ARCHITECTURE.md` should remain unchanged because this feature does not alter architecture, package boundaries, or data flow enough to warrant an architecture edit.
  - `devlog/DEVLOG.md` must include the date, summary, what changed, why, gotchas, and verification commands/results.

**Steps:**

- [x] Step 1: Update `README.md` in the existing `Basic Usage` section with:
  - one direct clipboard example using `-cc`
  - the improved alias example:
    - `alias al='asky -L -cc -sp "You are a CLI assistant. Answer briefly. When the user asks for a shell command, return only the command text. No markdown, no code fences, no explanation."'`
- [x] Step 2: Update `src/asky/cli/AGENTS.md` so future implementers know the CLI owns `-cc/--copy-clipboard` as an output-delivery flag and that copy happens after final-answer render with warning-only failure handling.
- [x] Step 3: Update `devlog/DEVLOG.md` with a factual entry including the clipboard-copy behavior, failure semantics, doc updates, and final verification/runtime numbers.
- [x] Step 4: Run the full suite, compare runtime against the baseline from this handoff, and confirm no disproportionate regression.

**Dependencies:**

- Depends on Checkpoint 2.

**Verification:**

- Run scoped tests: `uv run pytest tests/asky/cli/test_cli.py tests/integration/cli_recorded/test_cli_chat_controls_recorded.py tests/asky/cli/test_help_discoverability.py -q -n0`
- Run non-regression tests: `time uv run pytest`

**Done When:**

- Verification commands pass cleanly.
- `README.md` shows the improved clipboard alias example in an existing relevant section.
- `src/asky/cli/AGENTS.md` and `devlog/DEVLOG.md` are updated.
- The final full-suite runtime is recorded and compared to the baseline `1510 passed in 16.33s`, `real 16.609s`.
- A git commit is created with message: `Document clipboard copy flag`

**Stop and Escalate If:**

- The README lacks an existing relevant place for the alias example after re-reading the file.
- Full-suite runtime regresses materially beyond the added test cost and the cause is not obvious.

## Behavioral Acceptance Tests

- Given `asky -cc -off all --shortlist off "Just say apple."`, the terminal still shows the answer, and the clipboard helper receives exactly the model's final answer text.
- Given `asky --copy-clipboard -off all --shortlist off "Just say apple."`, the long flag behaves the same as `-cc`.
- Given `asky -L -cc "Just say apple."`, lean mode still prints the answer without the live banner, and the clipboard copy path still uses the raw final answer text.
- Given a clipboard backend failure during `-cc`, the answer is still visible, process exit remains successful, and the CLI prints a short warning with the reason but no traceback.
- Given a halted turn or empty final answer, no clipboard copy is attempted and no clipboard warning is emitted.
- Given `asky --help`, the curated help output includes `-cc, --copy-clipboard` in the output-delivery area.
- Given `asky --help-all`, both public spellings appear in the argparse reference.
- Given the recorded CLI surface manifest, both spellings are tracked as public top-level flags and owned by the recorded chat-controls file.
- Given the updated README, a user can discover a clipboard-first alias for command-only terminal usage without reading a new doc section.

## Plan-to-Verification Matrix

| Requirement | Verification |
| --- | --- |
| `-cc` and `--copy-clipboard` parse as public core flags | `uv run pytest tests/asky/cli/test_cli.py -q -n0` |
| Clipboard write uses exact raw final answer text | unit assertion in `tests/asky/cli/test_cli.py`; recorded assertion in `uv run pytest tests/integration/cli_recorded/test_cli_chat_controls_recorded.py -q -o addopts='-n0 --record-mode=none'` |
| Clipboard failure is warning-only | failure-path assertion in `tests/asky/cli/test_cli.py` and, if added, recorded failure assertion in `tests/integration/cli_recorded/test_cli_chat_controls_recorded.py` |
| No copy attempt for empty/halted results | `uv run pytest tests/asky/cli/test_cli.py -q -n0` |
| Curated help shows the new flag | `uv run pytest tests/asky/cli/test_help_discoverability.py -q -n0` plus `uv run python -m asky --help` manual spot-check if needed |
| `--help-all` includes the new flag | `uv run pytest tests/asky/cli/test_help_discoverability.py -q -n0` |
| Public CLI manifest tracks the new flag | `uv run pytest tests/integration/cli_recorded/test_cli_surface_manifest.py -q -n0` |
| Existing output-delivery features are not regressed | `uv run pytest tests/asky/plugins/test_plugin_manager.py -q -n0` and the final `time uv run pytest` |
| User-facing docs mention the workflow and alias example | manual diff check of `README.md`; recorded in `devlog/DEVLOG.md` |
| No disproportionate suite runtime regression | compare final `time uv run pytest` output to baseline `1510 passed in 16.33s`, `real 16.609s` |

## Assumptions And Defaults

- The implementation target is the current worktree rooted at `/home/evren/code/asky`.
- The existing `pyperclip` package remains the only clipboard library used.
- Clipboard copy should be attempted only for successful turns with a non-empty `final_answer`.
- The copy source is the raw `turn_result.final_answer` string exactly as returned by the model pipeline.
- The CLI warning can include the backend error string from `pyperclip`, but it must stay to a short single-line or near-single-line user-readable message without a traceback.
- The improved alias example should replace the user-provided draft with a stricter command-only prompt:
  - `alias al='asky -L -cc -sp "You are a CLI assistant. Answer briefly. When the user asks for a shell command, return only the command text. No markdown, no code fences, no explanation."'`
- `ARCHITECTURE.md` is intentionally left unchanged for this handoff because the feature adds a small CLI flag and post-render behavior, not a structural architecture shift.
- No new dependency approvals are needed because the repo already depends on `pyperclip`.
