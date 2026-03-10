# Extra Integration Test Coverage RALF Handoff

## Summary

Build exhaustive integration coverage for the supported asky CLI surface using the existing fake LLM infrastructure and subprocess fake server patterns, without adding dependencies and without weakening existing test gates.

This handoff is about closing CLI integration coverage gaps, not redesigning product behavior. The implementation must follow the existing `tests/integration/cli_recorded/` and `tests/integration/cli_recorded/test_cli_interactive_subprocess.py` patterns instead of inventing a new harness.

Observed baseline on 2026-03-09 before this handoff:

- `/usr/bin/time -p uv run pytest -q` -> `1 failed, 1408 passed in 49.83s` (`real 51.24`)
- Failing test: `tests/performance/test_startup_performance.py::test_help_startup_time_guardrail`
- Failure detail: median `python -m asky --help` startup exceeded the `0.60s` budget on this machine (`0.807s` in the full-suite run, `0.985s` on a focused rerun)

Because the user explicitly wants every checkpoint to finish only on a green suite, implementation must not proceed past bootstrap if the baseline is still red. Record the failure and stop unless the baseline is already green on the implementation machine or the user explicitly restarts the handoff from a fixed base.

Required CLI surface for this handoff:

- Direct top-level flags and public entrypoints:
  - `-m/--model`
  - `-c/--continue-chat`
  - `-s/--summarize`
  - `-t/--turns`
  - `--delete-messages`
  - `--delete-sessions`
  - `--clean-session-research`
  - `--all`
  - `-H/--history`
  - `-pa/--print-answer`
  - `-ps/--print-session`
  - `-p/--prompts`
  - `-v/--verbose`
  - `-o/--open`
  - `-ss/--sticky-session`
  - `--config model add`
  - `--config model edit [alias]`
  - `--config daemon edit`
  - `--session <query...>`
  - `--tools`
  - `-rs/--resume-session`
  - `-se/-es/--session-end`
  - `-sh/--session-history`
  - `-r/--research`
  - `-sfm/--session-from-message`
  - `--reply`
  - `-L/--lean`
  - `--shortlist`
  - `-off/-tool-off/--tool-off`
  - `--list-tools`
  - `--query-corpus`
  - `--query-corpus-max-sources`
  - `--query-corpus-max-chunks`
  - `--summarize-section`
  - `--section-source`
  - `--section-id`
  - `--section-include-toc`
  - `--section-detail`
  - `--section-max-chunks`
  - `--list-memories`
  - `--delete-memory`
  - `--clear-memories`
  - `-em/--elephant-mode`
  - `-tl/--terminal-lines`
  - `-sp/--system-prompt`
  - `--completion-script`
- Grouped commands:
  - `history list`
  - `history show`
  - `history delete`
  - `session list`
  - `session show`
  - `session create`
  - `session use`
  - `session end`
  - `session delete`
  - `session clean-research`
  - `session from-message`
  - `memory list`
  - `memory delete`
  - `memory clear`
  - `corpus query`
  - `corpus summarize`
  - `prompts list`
- Persona CLI surface:
  - `persona create --prompt --description`
  - `persona add-sources`
  - `persona import`
  - `persona export --output`
  - `persona load`
  - `persona unload`
  - `persona current`
  - `persona list`
  - `persona alias`
  - `persona unalias`
  - `persona aliases`
  - `@mention` and alias mention inside real CLI turns
- Plugin-contributed CLI flags and public behavior:
  - `--daemon`
  - `--sendmail`
  - `--subject`
  - `--push-data`
  - `--browser`

Intentionally hidden internal flags are not separate coverage targets. They must be covered only through their supported public translators or dispatch paths:

- `--add-model`
- `--edit-model`
- `--from-message`
- `--tools-reset`
- `--xmpp-daemon`
- `--edit-daemon`
- `--xmpp-menubar-child`

## Git Tracking

- Plan Branch: `main`
- Pre-Handoff Base HEAD: `5031ab0146e683e6abeb5ee2de73185afad3ed78`
- Last Reviewed HEAD: `none`
- Review Log:
  - None yet.

## Done Means

- Every required surface item listed in `Summary` has at least one integration test in `tests/integration/`.
- New coverage follows existing recorded/subprocess harness patterns:
  - in-process fake recorded tests in `tests/integration/cli_recorded/`
  - subprocess and PTY realism only in `tests/integration/cli_recorded/test_cli_interactive_subprocess.py`
- A canonical manifest exists under `tests/integration/cli_recorded/` so future CLI surface changes cannot land without explicitly updating integration coverage ownership.
- New tests are deterministic:
  - no live network
  - no real email delivery
  - no real webhook delivery
  - no real browser automation install/run
  - no writes outside isolated test HOME and repo-managed temp artifacts
- Existing real-provider recorded and live research suites keep their current semantics and still replay/pass when affected shared harness files change.
- No new dependency is added.
- No pytest marker policy, default addopts, or performance threshold is loosened.
- Relevant documentation is updated only where implementation actually changes testing workflow expectations.
- `devlog/DEVLOG.md` records the work and the post-change runtime.
- Final implementation state is green:
  - `uv run pytest -q`
  - fake recorded replay lane
  - subprocess lane
  - real recorded replay if shared recorded helpers or recorded conftest changed

## Critical Invariants

- The fake recorded lane must keep using the shared fake OpenAI-compatible endpoint in `tests/integration/cli_recorded/conftest.py`; do not create per-test ad hoc model servers outside the existing subprocess-only pattern.
- New integration tests must invoke the actual CLI surface being claimed as covered. Do not replace a CLI integration test with direct calls into storage/helpers when a supported CLI path exists.
- For management surfaces that have no deterministic public create path, fixture-level seeding is allowed only for setup, not as the action under test.
- The canonical CLI surface manifest must be the source of truth for coverage ownership. If a supported CLI flag, grouped command, or persona subcommand changes, the manifest and at least one integration test must change in the same handoff.
- Hidden internal flags remain covered through public translators; do not normalize them into first-class public test targets.
- Real-provider and live research assertions remain model-backed `-r <source> <question>` turns. Do not move deterministic `corpus query` coverage into the real/live lanes.
- Output-delivery and browser tests must stub side effects at the final boundary:
  - email sender function
  - push executor or local fake endpoint
  - browser login call
  - daemon foreground launcher
  They must not contact real external systems.
- New tests must assert user-visible behavior or end-to-end side effects:
  - stdout/stderr
  - persisted DB/session/memory state
  - generated files
  - captured fake provider request payloads
  - stubbed external call arguments
- Do not edit root `AGENTS.md`.

## Forbidden Implementations

- Do not add a new testing package, mocking library, or helper dependency.
- Do not weaken or delete the existing performance guard, marker exclusions, or recorded replay rules to make the suite pass.
- Do not mark new coverage `xfail` or `skip` unless the surface is already intentionally gated by an existing runtime contract, and the test explicitly verifies that gate.
- Do not count parser-only tests in `tests/asky/cli/` as integration coverage for this handoff.
- Do not bypass the CLI for history/session/prompt/persona commands by calling handler functions directly.
- Do not refresh real-provider or live cassettes just because new fake-lane tests were added. Only touch those lanes if a shared helper change breaks replay and the replay command proves it.
- Do not modify `pyproject.toml`, `scripts/refresh_cli_cassettes.sh`, `scripts/run_research_quality_gate.sh`, or `ARCHITECTURE.md` unless a concrete testing workflow or architecture statement becomes false. If that happens, the same checkpoint must update the doc and verification commands accordingly.
- Do not change user-facing CLI behavior solely to make tests easier unless the new test first demonstrates a real supported behavior bug and the corresponding production fix is the minimal compatibility-preserving change.

## Checkpoints

### [x] Checkpoint 1: Canonical CLI Surface Manifest And Harness Extensions

**Goal:**

- Create one authoritative manifest for supported CLI integration coverage and extend the shared recorded helpers only where determinism or observability is currently missing.

**Context Bootstrapping:**

- Run these commands before editing:
- `pwd`
- `sed -n '1,260p' AGENTS.md`
- `sed -n '1,260p' ARCHITECTURE.md`
- `sed -n '1,260p' devlog/DEVLOG.md`
- `sed -n '1,260p' tests/AGENTS.md`
- `sed -n '1,260p' src/asky/cli/AGENTS.md`
- `sed -n '1,280p' tests/integration/cli_recorded/conftest.py`
- `sed -n '1,240p' tests/integration/cli_recorded/helpers.py`
- `uv run asky --help`
- `uv run asky --help-all`
- `uv run asky persona --help`
- `rg -n "parser.add_argument|add_parser|get_cli_contributions" src/asky/cli/main.py src/asky/plugins/*/plugin.py`
- `uv run pytest -q`
- If this is Checkpoint 1, capture the git tracking values before any edits:
- `git branch --show-current`
- `git rev-parse HEAD`

**Scope & Blast Radius:**

- May create/modify:
  - `tests/integration/cli_recorded/cli_surface.py`
  - `tests/integration/cli_recorded/test_cli_surface_manifest.py`
  - `tests/integration/cli_recorded/conftest.py`
  - `tests/integration/cli_recorded/helpers.py`
- Must not touch:
  - `src/asky/**`
  - `pyproject.toml`
  - `scripts/**`
  - `ARCHITECTURE.md`
  - `devlog/DEVLOG.md`
  - root `AGENTS.md`
- Constraints:
  - The manifest must include every required public surface in this plan.
  - Plugin-contributed flags must be discovered from `get_cli_contributions()`, not from `--help-all`, because `_INTERNAL_ONLY_FLAGS` currently skips plugin contribution bootstrap for some help/config invocations.
  - The parity/meta test must ignore only the intentionally hidden internal flag set named in `Summary`.

**Steps:**

- [x] Step 1: Create `tests/integration/cli_recorded/cli_surface.py` with a single canonical inventory of:
  - public top-level flags
  - grouped commands
  - persona subcommands and their subcommand-specific flags
  - plugin-contributed flags
  - explicit mapping from hidden internal flags to their public owners
- [x] Step 2: Add `tests/integration/cli_recorded/test_cli_surface_manifest.py` that fails when:
  - `src/asky/cli/main.py` gains/removes a supported public flag without a manifest update
  - `asky persona` subcommands drift from the manifest
  - built-in plugin CLI contributions drift from the manifest
- [x] Step 3: Extend shared fixtures/helpers only if needed for later checkpoints:
  - captured fake-provider request payload access
  - deterministic prompt-file helpers
  - plugin roster rewrite helper for enabled/disabled test cases
  - report-file locator/helper for `--open`
  - stub call capture helpers for email/push/browser/daemon

**Dependencies:**

- Depends on no prior checkpoint.

**Verification:**

- Run scoped tests: `uv run pytest tests/integration/cli_recorded/test_cli_surface_manifest.py -q -o addopts='-n0 --record-mode=none'`
- Run scoped non-regression: `uv run pytest tests/integration/cli_recorded/test_cli_one_shot_recorded.py tests/integration/cli_recorded/test_cli_session_recorded.py -q -o addopts='-n0 --record-mode=none'`
- Run non-regression tests: `uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=none' -m "recorded_cli and not real_recorded_cli"`
- Run full suite: `uv run pytest -q`

**Done When:**

- Verification commands pass cleanly.
- The manifest can mechanically explain every required surface in this handoff.
- No production code was changed in this checkpoint.
- A git commit is created with message: `test: add cli surface manifest and recorded harness helpers`

**Stop and Escalate If:**

- `uv run pytest -q` is already red before edits.
- Manifest parity requires production code edits rather than test-side discovery.
- A needed surface cannot be represented without arguing about whether it is public or hidden. In that case, keep the manifest aligned with this plan and stop.

### [x] Checkpoint 2: History, Session, And Prompt Surface Coverage

**Goal:**

- Add integration coverage for the history/session/prompt management surface using the existing fake recorded harness and real CLI invocation paths.

**Context Bootstrapping:**

- Run these commands before editing:
- `sed -n '1,240p' tests/integration/cli_recorded/cli_surface.py`
- `sed -n '1,260p' tests/integration/cli_recorded/test_cli_one_shot_recorded.py`
- `sed -n '1,320p' tests/integration/cli_recorded/test_cli_session_recorded.py`
- `sed -n '1,260p' src/asky/cli/main.py`
- `sed -n '1,260p' src/asky/cli/history.py`
- `sed -n '1,260p' src/asky/cli/sessions.py`
- `sed -n '1,220p' src/asky/cli/prompts.py`
- `uv run pytest tests/integration/cli_recorded/test_cli_session_recorded.py -q -o addopts='-n0 --record-mode=none'`

**Scope & Blast Radius:**

- May create/modify:
  - `tests/integration/cli_recorded/test_cli_one_shot_recorded.py`
  - `tests/integration/cli_recorded/test_cli_session_recorded.py`
  - `tests/integration/cli_recorded/test_cli_history_session_recorded.py`
  - `tests/integration/cli_recorded/cassettes/**` for the files above
- May modify only if a new integration case exposes a real supported bug:
  - `src/asky/cli/main.py`
  - `src/asky/cli/history.py`
  - `src/asky/cli/sessions.py`
  - `src/asky/cli/prompts.py`
  - `src/asky/storage/sqlite.py`
- Must not touch:
  - research modules
  - persona modules
  - plugin modules
  - `pyproject.toml`
- Constraints:
  - Prefer seeding history/session state by issuing real CLI turns, not direct DB writes.
  - If direct DB seeding becomes necessary for setup, use it only to establish preconditions, then invoke the CLI surface under test.
  - Keep grouped-command strictness assertions intact.

**Steps:**

- [x] Step 1: Expand or move existing session cases so this checkpoint covers:
  - `-ss/--sticky-session`
  - `--session <query...>`
  - `-rs/--resume-session`
  - `-sh/--session-history`
  - `-ps/--print-session`
  - `-se/-es/--session-end`
  - grouped `session list`
  - grouped `session show`
  - grouped `session create`
  - grouped `session use`
  - grouped `session end`
  - grouped `session delete`
  - grouped `session clean-research`
  - grouped `session from-message`
- [x] Step 2: Add history coverage for:
  - `-H/--history`
  - `-pa/--print-answer`
  - `--delete-messages`
  - grouped `history list`
  - grouped `history show`
  - grouped `history delete`
  - `--all` behavior for message deletion
- [x] Step 3: Add conversion/resume coverage for:
  - `-sfm/--session-from-message`
  - `--reply`
  - `-c/--continue-chat` with explicit selector and implicit last
- [x] Step 4: Add prompt surface coverage for:
  - `-p/--prompts`
  - grouped `prompts list`
  - test-local `prompts.toml` output equality across both entrypoints
- [x] Step 5: Update the manifest ownership/comments if any required surface moved across files.

**Dependencies:**

- Depends on Checkpoint 1.

**Verification:**

- Run scoped tests: `uv run pytest tests/integration/cli_recorded/test_cli_session_recorded.py tests/integration/cli_recorded/test_cli_history_session_recorded.py -q -o addopts='-n0 --record-mode=none'`
- Run prompt-specific tests: `uv run pytest tests/integration/cli_recorded/test_cli_history_session_recorded.py -q -o addopts='-n0 --record-mode=none' -k "prompt or prompts"`
- Run non-regression tests: `uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=none' -m "recorded_cli and not real_recorded_cli"`
- Run full suite: `uv run pytest -q`

**Done When:**

- Verification commands pass cleanly.
- Every history/session/prompt surface item in the manifest has a concrete owning integration test.
- Public translation paths (`--session`, grouped commands, `--reply`, `--session-from-message`) are covered through the public CLI entrypoints, not hidden flags.
- A git commit is created with message: `test: cover history session and prompt cli surface`

**Stop and Escalate If:**

- A new test exposes a bug that requires edits outside the listed CLI/storage files.
- You cannot verify a surface without weakening grouped-command strictness or selector validation behavior.
- The baseline full suite is still red.

### [x] Checkpoint 3: Chat Controls And Memory Surface Coverage

**Goal:**

- Cover the remaining non-research chat controls, observability flags, output-file behavior, and memory-management surface with deterministic fake recorded tests.

**Context Bootstrapping:**

- Run these commands before editing:
- `sed -n '1,240p' tests/integration/cli_recorded/helpers.py`
- `sed -n '1,260p' src/asky/cli/main.py`
- `sed -n '1,260p' src/asky/cli/chat.py`
- `sed -n '1,220p' src/asky/cli/terminal.py`
- `sed -n '1,220p' src/asky/rendering.py`
- `sed -n '1,220p' src/asky/cli/memory_commands.py`
- `uv run pytest tests/integration/cli_recorded/test_cli_one_shot_recorded.py -q -o addopts='-n0 --record-mode=none'`

**Scope & Blast Radius:**

- May create/modify:
  - `tests/integration/cli_recorded/test_cli_chat_controls_recorded.py`
  - `tests/integration/cli_recorded/test_cli_memory_surface_recorded.py`
  - `tests/integration/cli_recorded/test_cli_one_shot_recorded.py`
  - `tests/integration/cli_recorded/cassettes/**` for the files above
- May modify only if a new integration case exposes a real supported bug:
  - `src/asky/cli/main.py`
  - `src/asky/cli/chat.py`
  - `src/asky/cli/terminal.py`
  - `src/asky/rendering.py`
  - `src/asky/cli/memory_commands.py`
  - `src/asky/memory/**`
- Must not touch:
  - research modules
  - persona modules
  - plugin modules
  - `pyproject.toml`
- Constraints:
  - Use captured fake-provider request payloads when stdout alone cannot prove flag behavior.
  - Memory-management command tests may seed memory records in setup because there is no deterministic public create command.
  - `--open` must not launch a real browser in tests.

**Steps:**

- [x] Step 1: Add chat-control coverage for:
  - `-m/--model`
  - `-s/--summarize`
  - `-t/--turns`
  - `-L/--lean`
  - `--shortlist on|off|reset`
  - `--tools`
  - `-off/-tool-off/--tool-off`
  - `--list-tools`
- [x] Step 2: Add observability/request-shaping coverage for:
  - `-sp/--system-prompt`
  - `-tl/--terminal-lines`
  - `-v`
  - `-vv`
  - `--completion-script`
  Use stdout or captured fake-provider payload assertions, whichever is the truly observable end-to-end behavior for that surface.
- [x] Step 3: Add output-file behavior coverage for `-o/--open` by stubbing the final browser boundary and asserting the rendered file path exists and is announced correctly.
- [x] Step 4: Add memory surface coverage for:
  - `-em/--elephant-mode`
  - `--list-memories`
  - `--delete-memory`
  - `--clear-memories`
  - grouped `memory list`
  - grouped `memory delete`
  - grouped `memory clear`
- [x] Step 5: Update the manifest to point each covered surface item at its owning test file.

**Dependencies:**

- Depends on Checkpoint 2.

**Verification:**

- Run scoped tests: `uv run pytest tests/integration/cli_recorded/test_cli_chat_controls_recorded.py tests/integration/cli_recorded/test_cli_memory_surface_recorded.py -q -o addopts='-n0 --record-mode=none'`
- Run non-regression tests: `uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=none' -m "recorded_cli and not real_recorded_cli"`
- Run full suite: `uv run pytest -q`

**Done When:**

- Verification commands pass cleanly.
- Each non-research control/memory surface item in the manifest has a deterministic integration test.
- No real browser, email, webhook, or live network side effect occurs in this checkpoint.
- A git commit is created with message: `test: cover chat control and memory cli surface`

**Stop and Escalate If:**

- A flag cannot be verified without live external dependencies.
- A needed fix requires changing marker policy, addopts, or performance thresholds.
- The baseline full suite is still red.

### [x] Checkpoint 4: Research Manual Commands And Persona Surface Coverage

**Goal:**

- Finish deterministic research/manual corpus command coverage and add true CLI integration coverage for the persona command surface.

**Context Bootstrapping:**

- Run these commands before editing:
- `sed -n '1,320p' tests/integration/cli_recorded/test_cli_research_local_recorded.py`
- `sed -n '1,320p' src/asky/cli/research_commands.py`
- `sed -n '1,320p' src/asky/cli/section_commands.py`
- `sed -n '1,320p' src/asky/cli/persona_commands.py`
- `sed -n '1,220p' src/asky/plugins/manual_persona_creator/AGENTS.md`
- `sed -n '1,220p' src/asky/plugins/persona_manager/AGENTS.md`
- `uv run asky persona --help`
- `uv run pytest tests/integration/cli_recorded/test_cli_research_local_recorded.py -q -o addopts='-n0 --record-mode=none'`

**Scope & Blast Radius:**

- May create/modify:
  - `tests/integration/cli_recorded/test_cli_research_local_recorded.py`
  - `tests/integration/cli_recorded/test_cli_persona_recorded.py`
  - `tests/integration/cli_recorded/cassettes/**` for the files above
- May modify only if a new integration case exposes a real supported bug:
  - `src/asky/cli/main.py`
  - `src/asky/cli/research_commands.py`
  - `src/asky/cli/section_commands.py`
  - `src/asky/cli/persona_commands.py`
  - `src/asky/research/**`
  - `src/asky/plugins/manual_persona_creator/**`
  - `src/asky/plugins/persona_manager/**`
- Must not touch:
  - plugin output-delivery modules
  - daemon modules
  - `pyproject.toml`
- Constraints:
  - Keep new research coverage in the fake recorded lane unless the shared helpers changed and explicit replay proves real-recorded regression.
  - Persona tests must use the actual `asky persona ...` CLI entrypoint, not handler direct calls.
  - Use temp prompt/source files under pytest tmp paths or repo-approved temp helpers; do not create ad hoc files elsewhere.

**Steps:**

- [x] Step 1: Extend fake recorded research coverage to include:
  - `--query-corpus`
  - `--query-corpus-max-sources`
  - `--query-corpus-max-chunks`
  - `--summarize-section`
  - `--section-source`
  - `--section-id`
  - `--section-include-toc`
  - `--section-detail`
  - `--section-max-chunks`
  - grouped `corpus query`
  - grouped `corpus summarize`
- [x] Step 2: Add research profile/state assertions where needed:
  - persisted `local_only` vs `mixed`
  - corpus replacement semantics
  - section listing vs deterministic section-id targeting
  - bounded source/chunk behavior for manual corpus query
- [x] Step 3: Add persona CLI integration tests covering:
  - `persona create --prompt --description`
  - `persona add-sources`
  - `persona export --output`
  - `persona import`
  - `persona list`
  - `persona load`
  - `persona unload`
  - `persona current`
  - `persona alias`
  - `persona unalias`
  - `persona aliases`
- [x] Step 4: Add actual CLI turn coverage for `@persona` and `@alias` mention behavior after persona setup, asserting both:
  - mention token is stripped from the model-facing query
  - session binding/loaded persona side effect occurs
- [x] Step 5: Update the manifest to mark all research/persona surfaces as covered.

**Dependencies:**

- Depends on Checkpoint 3.

**Verification:**

- Run scoped tests: `uv run pytest tests/integration/cli_recorded/test_cli_research_local_recorded.py tests/integration/cli_recorded/test_cli_persona_recorded.py -q -o addopts='-n0 --record-mode=none'`
- Run fake recorded non-regression: `uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=none' -m "recorded_cli and not real_recorded_cli"`
- If `tests/integration/cli_recorded/conftest.py` or `tests/integration/cli_recorded/helpers.py` changed in this checkpoint, run replay non-regression: `ASKY_CLI_REAL_PROVIDER=1 uv run pytest tests/integration/cli_recorded/test_cli_real_model_recorded.py -q -o addopts='-n0 --record-mode=none'`
- Run full suite: `uv run pytest -q`

**Done When:**

- Verification commands pass cleanly.
- Every manual corpus and persona surface item in the manifest has a deterministic integration test.
- Persona tests exercise the real CLI entrypoint and persistent session-binding behavior.
- A git commit is created with message: `test: cover research manual commands and persona cli surface`

**Stop and Escalate If:**

- A persona or research surface requires a new dependency or live provider for deterministic coverage.
- A required fix spills into unrelated non-listed modules.
- The baseline full suite is still red.

### [x] Checkpoint 5: Plugin Flags, Subprocess Paths, And Documentation Parity

**Goal:**

- Cover the remaining plugin-contributed CLI surface and subprocess-only realism paths, then update the testing docs and devlog to match the finished coverage contract.

**Context Bootstrapping:**

- Run these commands before editing:
- `sed -n '1,260p' src/asky/plugins/AGENTS.md`
- `sed -n '1,220p' src/asky/plugins/email_sender/AGENTS.md`
- `sed -n '1,220p' src/asky/plugins/push_data/AGENTS.md`
- `sed -n '1,220p' src/asky/plugins/playwright_browser/AGENTS.md`
- `sed -n '1,220p' src/asky/plugins/xmpp_daemon/AGENTS.md`
- `sed -n '1,280p' tests/integration/cli_recorded/test_cli_interactive_subprocess.py`
- `sed -n '1,220p' docs/testing_recorded_cli.md`
- `sed -n '1,260p' tests/AGENTS.md`
- `sed -n '1,260p' devlog/DEVLOG.md`

**Scope & Blast Radius:**

- May create/modify:
  - `tests/integration/cli_recorded/test_cli_plugin_surface_recorded.py`
  - `tests/integration/cli_recorded/test_cli_interactive_subprocess.py`
  - `tests/integration/cli_recorded/cassettes/**` for the files above
  - `docs/testing_recorded_cli.md`
  - `tests/AGENTS.md`
  - `devlog/DEVLOG.md`
- May modify only if a new integration case exposes a real supported bug:
  - `src/asky/cli/main.py`
  - `src/asky/cli/daemon_config.py`
  - `src/asky/rendering.py`
  - `src/asky/daemon/**`
  - `src/asky/plugins/email_sender/**`
  - `src/asky/plugins/push_data/**`
  - `src/asky/plugins/playwright_browser/**`
  - `src/asky/plugins/xmpp_daemon/**`
- Must not touch:
  - root `AGENTS.md`
  - `pyproject.toml`
  - `ARCHITECTURE.md` unless a testing architecture statement in that file becomes factually wrong
- Constraints:
  - `--sendmail`, `--push-data`, `--browser`, and `--daemon` tests must stub the final side-effect boundary and assert arguments/dispatch, not run real external systems.
  - `--browser` must cover both the disabled-by-default user-visible failure path and an enabled-path dispatch case using a fake runtime/plugin object or equivalent deterministic hook.
  - Keep subprocess coverage in the existing subprocess file; do not scatter PTY tests into the recorded in-process files.

**Steps:**

- [x] Step 1: Add plugin surface coverage for:
  - `--sendmail`
  - `--subject`
  - `--push-data`
  - `--daemon`
  - `--browser`
  - `--config model add`
  - `--config model edit`
  - `--config daemon edit`
- [x] Step 2: Extend subprocess coverage only where true process-boundary behavior matters:
  - existing model edit interactive flow
  - optional model add interactive smoke if still uncovered
  - PTY rendering realism that cannot be proved in-process
- [x] Step 3: Update `tests/AGENTS.md` so it explicitly requires:
  - updating the canonical CLI surface manifest when CLI surface changes
  - adding fake recorded or subprocess coverage for every new CLI feature
  - keeping plugin side effects stubbed/deterministic in fake recorded tests
- [x] Step 4: Update `docs/testing_recorded_cli.md` to document the expanded fake recorded lane and where subprocess/plugin coverage lives.
- [x] Step 5: Update `devlog/DEVLOG.md` with:
  - date and summary
  - what changed and why
  - runtime before/after
  - any gotchas or remaining follow-up
- [x] Step 6: Review `ARCHITECTURE.md`. If no architecture/data-flow statement changed, leave it untouched and state that decision in the final summary. If a testing-architecture statement there became wrong, update only the relevant lines in the same checkpoint.

**Dependencies:**

- Depends on Checkpoint 4.

**Verification:**

- Run scoped tests: `uv run pytest tests/integration/cli_recorded/test_cli_plugin_surface_recorded.py tests/integration/cli_recorded/test_cli_interactive_subprocess.py -q -o addopts='-n0 --record-mode=none'`
- Run fake recorded lane: `uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=none' -m "recorded_cli and not real_recorded_cli"`
- Run subprocess lane explicitly: `uv run pytest tests/integration/cli_recorded/test_cli_interactive_subprocess.py -q -o addopts='-n0 --record-mode=none'`
- Run real recorded replay if shared recorded helpers/conftest changed: `ASKY_CLI_REAL_PROVIDER=1 uv run pytest tests/integration/cli_recorded/test_cli_real_model_recorded.py -q -o addopts='-n0 --record-mode=none'`
- Run full suite with timing capture: `/usr/bin/time -p uv run pytest -q`

**Done When:**

- Verification commands pass cleanly.
- Every remaining plugin/subprocess surface item in the manifest has an owning integration test.
- Docs/devlog updates reflect only implemented behavior and test workflow facts.
- Runtime comparison against the pre-change baseline is recorded and justified.
- A git commit is created with message: `test: cover remaining plugin cli surface and update docs`

**Stop and Escalate If:**

- A plugin flag cannot be covered deterministically without adding a dependency or talking to a real external system.
- The baseline full suite is still red.
- Updating docs would require describing behavior that was not implemented in this handoff.

## Behavioral Acceptance Tests

- Given a fresh fake recorded test home, `asky --session "what is 2+2"` creates a session named from the query, runs the query, and later `session show` prints that transcript.
- Given prior history without an attached session, `asky --reply -- "What did I just tell you?"` or `asky --session-from-message <id>` converts the prior history into a session and the follow-up turn can use that context.
- Given history entries exist, `asky history show <selector>` and `asky --print-answer <selector>` print the stored assistant answer text, while `history delete` and `--delete-messages` remove the intended records and honor `--all`.
- Given a research session with cached local corpus data, `asky corpus query ... --query-corpus-max-sources 1 --query-corpus-max-chunks 1` reports bounded deterministic results, and `asky corpus summarize` plus `--section-id` deterministically selects the requested section.
- Given `--shortlist on`, a defaults-only invocation persists the session preference, and a later turn without the flag uses that stored setting; `reset` removes it.
- Given `--terminal-lines 5` and a deterministic patched terminal context provider, the model-facing request contains the expected terminal lines; given `--system-prompt "X"`, the request contains that override.
- Given `-v` or `-vv`, the CLI still prints the final answer and emits the expected verbose or double-verbose transport output without crashing the live console path.
- Given `--open`, the CLI renders an HTML report file and calls the final browser-open boundary exactly once without opening a real browser during tests.
- Given pre-seeded memory rows, `memory list`, `memory delete`, and `memory clear` manage them via the CLI; given `--elephant-mode`, the session defaults persist that setting for future turns.
- Given a created persona, `asky persona export --output <zip>` writes a ZIP, `asky persona import <zip>` restores it into a fresh home, and `persona load/current/unload/alias/unalias/aliases` all behave through the real `asky persona` CLI entrypoint.
- Given a persona alias exists, a query like `@dev explain this` strips the mention from the model-facing query and binds the correct persona to the active session before the turn runs.
- Given `--sendmail a@example.com --subject Demo`, the email sender boundary is called with the final answer and explicit subject; given `--push-data notion?title=Demo`, the push executor boundary receives endpoint, params, query, answer, and model.
- Given `--browser https://example.com` while Playwright is disabled, the CLI prints the deterministic disabled-plugin error; given a fake active Playwright plugin runtime, it dispatches one `run_login_session()` call for that URL.
- Given `--daemon`, the CLI dispatches the daemon foreground path without attempting a normal chat turn; given `--config daemon edit` or `--config model edit`, the public config entrypoints dispatch the expected interactive handlers.

## Plan-to-Verification Matrix

| Requirement | Verification |
| --- | --- |
| Canonical CLI surface manifest exists and stays in sync | `uv run pytest tests/integration/cli_recorded/test_cli_surface_manifest.py -q -o addopts='-n0 --record-mode=none'` |
| History/session/prompt surface covered | `uv run pytest tests/integration/cli_recorded/test_cli_session_recorded.py tests/integration/cli_recorded/test_cli_history_session_recorded.py -q -o addopts='-n0 --record-mode=none'` |
| Chat controls and memory surface covered | `uv run pytest tests/integration/cli_recorded/test_cli_chat_controls_recorded.py tests/integration/cli_recorded/test_cli_memory_surface_recorded.py -q -o addopts='-n0 --record-mode=none'` |
| Research manual corpus and section surface covered | `uv run pytest tests/integration/cli_recorded/test_cli_research_local_recorded.py -q -o addopts='-n0 --record-mode=none'` |
| Persona CLI surface covered | `uv run pytest tests/integration/cli_recorded/test_cli_persona_recorded.py -q -o addopts='-n0 --record-mode=none'` |
| Plugin flags and subprocess realism covered | `uv run pytest tests/integration/cli_recorded/test_cli_plugin_surface_recorded.py tests/integration/cli_recorded/test_cli_interactive_subprocess.py -q -o addopts='-n0 --record-mode=none'` |
| Fake recorded lane still replays end-to-end | `uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=none' -m "recorded_cli and not real_recorded_cli"` |
| Shared recorded helper changes do not break real replay | `ASKY_CLI_REAL_PROVIDER=1 uv run pytest tests/integration/cli_recorded/test_cli_real_model_recorded.py -q -o addopts='-n0 --record-mode=none'` |
| Default suite still passes and runtime stays reasonable | `/usr/bin/time -p uv run pytest -q` |
| Docs/devlog were updated only where warranted | `rg -n "cli surface manifest|recorded lane|subprocess lane|sendmail|push-data|browser|daemon" tests/AGENTS.md docs/testing_recorded_cli.md devlog/DEVLOG.md` |

## Assumptions And Defaults

- Python and packaging remain as currently configured in the repo (`uv`, Python 3.11+ compatible).
- All new coverage should use the existing fake LLM provider or the subprocess fake LLM server. No new real-provider or live tests are required for the newly added CLI surface coverage.
- Shared helper/conftest changes are allowed, but they must preserve the existing fake recorded lane, subprocess lane, and real recorded replay behavior.
- The default target for “every command line flag/feature” is the supported public surface plus persona CLI and built-in plugin CLI contributions, not intentionally hidden internal flags as standalone user-facing commands.
- The bundled plugin roster currently enables `email_sender`, `push_data`, and `xmpp_daemon`; `playwright_browser` remains disabled by default. Browser flag coverage must therefore include both the disabled-path UX and an enabled-path dispatch simulation.
- If a newly added integration test reveals an existing bug in a supported CLI path, fixing that bug is in scope only when the change is minimal, behavior-preserving, and limited to the checkpoint’s allowed production files.
- If any new test reliably exceeds one second, mark it `@pytest.mark.slow` and note why in the devlog entry.
- If the baseline full suite remains red before implementation begins, stop and report the exact failure instead of continuing with partial checkpoint work.

## Final Checklist

- [x] Baseline full suite status was checked before edits and recorded.
- [x] Every required public CLI surface item from this handoff is present in the canonical manifest.
- [x] Every manifest item has at least one integration test owner.
- [x] No new dependency was added.
- [x] No root `AGENTS.md` edit was made.
- [x] Fake recorded replay lane passes.
- [x] Subprocess lane passes.
- [x] Real recorded replay passes when shared recorded helpers/conftest changed.
- [x] `uv run pytest -q` passes cleanly.
- [x] Runtime before/after was recorded and compared.
- [x] `tests/AGENTS.md` was updated if workflow expectations changed.
- [x] `docs/testing_recorded_cli.md` was updated if user-facing testing guidance changed.
- [x] `ARCHITECTURE.md` was updated only if a testing architecture statement became false.
- [x] `devlog/DEVLOG.md` was updated with summary, why, and follow-up notes.
- [x] No debug artifacts or temp files remain outside `temp/`.
