# DEVLOG

For full detailed entries, see [DEVLOG_ARCHIVE.md](DEVLOG_ARCHIVE.md).

## 2026-03-13: CLI Help Discoverability Implementation

- **Summary**: Implemented CLI help discoverability with a production-side help catalog and comprehensive contract enforcement.
- **Changes**:
  - Created `src/asky/cli/help_catalog.py` with typed structures for help content,
    curated help pages, and discoverability contract definitions.
  - Refactored CLI help rendering in `main.py` to use the help catalog,
    removing large handwritten string blocks.
  - Fixed `--help-all` to include plugin public flags by removing it from
    `_INTERNAL_ONLY_FLAGS` so the plugin manager is bootstrapped for help
    invocations.
  - Updated `src/asky/cli/__init__.py` to bootstrap the plugin manager
    automatically for `--help-all` and plugin flag invocations, ensuring the
    `--help-all` contract holds for both the local CLI entrypoint and
    direct `parse_args()` callers.
  - Created `tests/asky/cli/test_help_discoverability.py` to enforce the
    discoverability contract, checking that every public CLI surface item
    appears in its assigned help surface.
  - Updated `ARCHITECTURE.md` to document the CLI help catalog,
    three help surfaces, and discoverability contract.
  - Updated `src/asky/cli/AGENTS.md` to reference the help catalog and
    discoverability contract.
- **Gotchas**:
  - The help catalog owns all curated help content; tests validate it but don't
    import from test manifests.
  - Plugin bootstrap is narrow (only for `--help-all` and plugin flags),
    not for every parse invocation.
- **Verification**:
  - `uv run pytest tests/asky/cli/test_help_discoverability.py -q -n0` -> `7 passed in 4.65s`
  - `uv run pytest tests/asky/cli/test_cli.py -q -n0` -> `102 passed in 8.98s`
  - Full suite: `uv run pytest -q` -> `1408 passed in 27.60s`

## 2026-03-13: Filtered PyMuPDF SWIG Deprecation Noise In Pytest

- **Summary**: Added narrow pytest warning filters for the three Python 3.13 `DeprecationWarning`s emitted by PyMuPDF's SWIG extension types during PDF-backed research tests.
- **Changes**:
  - Updated `pyproject.toml` `filterwarnings` so pytest ignores only:
    - `SwigPyPacked has no __module__ attribute`
    - `SwigPyObject has no __module__ attribute`
    - `swigvarlink has no __module__ attribute`
- **Gotchas**:
  - This is intentionally narrow. It does not suppress unrelated `DeprecationWarning`s.
  - The source is PyMuPDF import-time behavior on Python 3.13, not the feature-domain plugin or the test harness itself.
- **Verification**:
  - `uv run pytest -q` -> `1459 passed in 12.22s`
  - The previous default-suite PyMuPDF SWIG warnings no longer appear in pytest output.

## 2026-03-12: Restored Fast Research Coverage To Default Runs And Documented Test Lanes

- **Summary**: Fixed the temp test-home regression introduced by moving fake HOME sandboxes out of `tests/`, restored the fast recorded research coverage to the default pytest lane, narrowed dynamic research deselection to only the heavy real-provider research files, and added a dedicated test architecture document so the lane machinery is documented in one place.
- **Changes**:
  - Fixed the integration harness after the `temp/test_home` move:
    - `tests/integration/cli_recorded/conftest.py` and `tests/integration/cli_live/conftest.py` no longer append `worker_id` twice.
    - `tests/conftest.py` no longer applies the generic HOME patch to the live lane on top of its own fixture.
    - `tests/conftest.py` now uses `temp/test_home/<worker>/<pid>/...` so separate pytest processes do not delete each other's sandboxes.
  - Fixed config redirection for the harness by teaching `src/asky/config/loader.py` to honor `ASKY_HOME` directly, and added coverage in `tests/asky/config/test_config.py`.
  - Hardened `tests/integration/cli_recorded/helpers.py` so in-process CLI runs reset plugin runtime and reload more stateful modules before each invocation.
  - Restored default pytest addopts in `pyproject.toml` and changed the default marker filter to exclude only `subprocess_cli`, `real_recorded_cli`, and `live_research`.
  - Narrowed `[tool.asky.pytest_feature_domains]` so the `research` domain only deselects the heavy real-provider research files, not:
    - `tests/asky/research/**`
    - `tests/asky/evals/research_pipeline/**`
    - `tests/integration/cli_recorded/test_cli_research_local_recorded.py`
  - Rewrote `tests/AGENTS.md` and added `tests/ARCHITECTURE.md` to document:
    - lane taxonomy
    - static marker gating vs dynamic feature-domain gating
    - fake HOME/config/database isolation
    - recorded vs real-recorded vs subprocess vs live lanes
    - the explicit research quality gate
  - Relaxed the live research assertions in `tests/integration/cli_live/test_cli_research_live.py` so they focus more on the stable capability invariants and less on exact provider wording.
- **Gotchas**:
  - Explicit `live_research` runs remain provider-dependent. They are intentionally kept out of the default suite and were not used as the final acceptance gate for this change.
  - The default suite now includes the ordinary `recorded_cli` lane again. That is intentional because the fast recorded research path is cheap enough to keep in local feedback loops.
- **Verification**:
  - `uv run pytest tests/asky/config/test_config.py -q -n0` -> `7 passed in 0.07s`
  - `uv run pytest tests/asky/testing/test_feature_domains.py tests/scripts/test_run_research_quality_gate.py -q -n0` -> `9 passed in 1.05s`
  - `ASKY_PYTEST_CHANGED_PATHS=src/asky/core/engine.py uv run pytest tests/asky/research -q -n0` -> `295 passed in 2.65s`
  - `uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=none' -m "recorded_cli and not real_recorded_cli"` -> `50 passed, 9 deselected in 8.79s`
  - Final default full suite: `uv run pytest -q` -> `1459 passed in 12.97s`

## 2026-03-12: Moved Test HOME Sandboxes Out Of `tests/` And Added Session Cleanup

- **Summary**: Moved the generated fake-HOME test sandboxes from `tests/.test_home/` to `temp/test_home/`, cleaned them per worker at session start and teardown, and removed the top-level `tests/` collection slowdown caused by pytest traversing tens of thousands of generated directories.
- **Changes**:
  - Updated `tests/conftest.py` so each xdist worker uses `temp/test_home/<worker>/...` instead of `tests/.test_home/<worker>/...`.
  - The session-scoped `test_home_root` fixture now clears the current worker subtree before the run and removes it again after the suite finishes.
  - Updated `.gitignore` to ignore `temp/` instead of the old `tests/.test_home/` path.
  - Updated `tests/AGENTS.md` and `ARCHITECTURE.md` to document the new test-home location and why it exists.
- **Gotchas**:
  - Cleanup is worker-scoped on purpose. In xdist, each worker manages its own subtree so workers do not race each other by deleting a shared root during startup or teardown.
  - An interrupted run can still leave artifacts behind, but they now live under `temp/` and no longer poison `pytest tests/ --collect-only` by sitting inside the test tree.
- **Verification**:
  - Before cleanup on this checkout, `tests/.test_home/` contained roughly `41,053` directories and `2,859` files.
  - `uv run pytest tests/ --collect-only -q -n0` after moving the sandbox out of `tests/` runs without traversing the old generated tree.
  - Final full suite verification recorded below after the implementation changes.

## 2026-03-12: Added Git-Aware Pytest Feature-Domain Deselection

- **Summary**: Added a shared feature-domain matcher plus a root pytest plugin so normal `uv run pytest` runs can automatically deselect heavy research-owned suites when the current uncommitted worktree does not touch research-scoped files.
- **Changes**:
  - Added `src/asky/testing/feature_domains.py` and `src/asky/testing/pytest_feature_domains.py`.
  - The plugin now loads from `tests/conftest.py`, reads `[tool.asky.pytest_feature_domains]` from `pyproject.toml`, and deselects inactive domain tests at collection time.
  - Added the generic `feature_domain(name)` marker for future outlier modules, while keeping the initial shipped `research` domain path-first and limited to the heavier research lanes.
  - Refactored `scripts/run_research_quality_gate.sh` to reuse the shared Python domain matcher instead of keeping a private hardcoded scope regex.
  - Added coverage in `tests/asky/testing/test_feature_domains.py` and updated `tests/scripts/test_run_research_quality_gate.py` so the gate script exercises the shared matcher.
  - Updated `ARCHITECTURE.md` and `tests/AGENTS.md` to document the new default pytest behavior and override path.
- **Gotchas**:
  - The `ASKY_PYTEST_RUN_ALL_DOMAINS=1` override is intentionally inherited by nested pytest subprocesses, so the new `pytester` tests explicitly clear that env var before asserting deselection behavior.
  - The initial `research` domain is intentionally narrower than “all research-adjacent tests” to avoid pushing too much coverage into CI-only discovery. Fast research-related unit tests still run by default.
- **Verification**:
  - Baseline before changes: `uv run pytest` -> `1400 passed in 55.13s`
  - Focused plugin + gate tests: `uv run pytest tests/asky/testing/test_feature_domains.py tests/scripts/test_run_research_quality_gate.py -q -n0` -> `9 passed in 0.77s`
  - Non-research override broad run: `ASKY_PYTEST_CHANGED_PATHS=src/asky/core/engine.py uv run pytest tests/asky -q -n0` -> `1079 passed, 319 deselected in 9.03s`
  - Explicit research target bypass: `ASKY_PYTEST_CHANGED_PATHS=src/asky/core/engine.py uv run pytest tests/asky/research/test_research_cache.py -q -n0` -> `29 passed in 2.06s`
  - Force-all override: `ASKY_PYTEST_RUN_ALL_DOMAINS=1 ASKY_PYTEST_CHANGED_PATHS=src/asky/core/engine.py uv run pytest tests/asky -q -n0` -> `1398 passed in 8.70s`
  - Final full suite: `uv run pytest -q` -> `1408 passed in 27.60s`

## 2026-03-12: Tightened CLI Integration Assertions and Rehomed Misplaced Tests

- **Summary**: Cleaned up the integration suite by removing redundant non-CLI tests from `tests/integration/`, moving module-wiring coverage into owning component buckets, and replacing several `exit_code == 0` checks in the recorded CLI lane with assertions on persisted session state or explicit CLI output.
- **Changes**:
  - Deleted `tests/integration/test_integration.py` because it only exercised storage/helpers directly and duplicated CLI coverage already present in the recorded history/session suite.
  - Moved `tests/integration/test_mention_pipeline_integration.py` to `tests/asky/plugins/persona_manager/test_mention_pipeline.py`, and removed the duplicated `tests/asky/cli/test_mention_integration.py` file.
  - Split `tests/integration/test_plugin_integration.py` by ownership into:
    - `tests/asky/core/test_runtime_hook_wiring.py`
    - `tests/asky/plugins/test_plugin_dependency_issues.py`
    - `tests/asky/daemon/test_daemon_service.py`
    - additional tray-menu hook coverage in `tests/asky/daemon/test_daemon_menubar.py`
  - Strengthened recorded CLI tests so chat-control/session/history/memory assertions now verify persisted session defaults, shortlist and elephant-mode session state, prompt listing output, session-detach behavior, and continued-chat notices.
  - Updated `tests/AGENTS.md` to reserve `tests/integration/` for CLI input-to-output and subprocess realism coverage, while keeping non-CLI wiring tests in `tests/asky/`.
- **Gotchas**:
  - The old `\q` expectation in `test_session_end_aliases` was a bad test assumption, not a CLI regression. `\q` is not implemented anywhere in the codebase or documented CLI surface, so the test now covers the actual supported session-end commands.
- **Verification**:
  - Baseline before changes: `uv run pytest` -> `1409 passed in 51.15s`
  - Moved/split suites: `uv run pytest tests/asky/core/test_runtime_hook_wiring.py tests/asky/plugins/test_plugin_dependency_issues.py tests/asky/daemon/test_daemon_service.py tests/asky/daemon/test_daemon_menubar.py tests/asky/plugins/persona_manager/test_mention_pipeline.py -q` -> `42 passed in 4.23s`
  - Recorded CLI assertions: `uv run pytest tests/integration/cli_recorded/test_cli_chat_controls_recorded.py tests/integration/cli_recorded/test_cli_history_session_recorded.py tests/integration/cli_recorded/test_cli_memory_surface_recorded.py tests/integration/cli_recorded/test_cli_session_recorded.py -q -o addopts='-n0 --record-mode=none'` -> `29 passed in 6.46s`
  - Final full suite: `uv run pytest` -> `1400 passed in 44.17s`

## 2026-03-12: Removed Live Helper/Planner Latency from Unit Tests

- **Summary**: Cut avoidable test runtime by stopping disabled-shortlist preload from invoking the planner model, disabling the plain-query helper by default in unit-test harnesses, and moving non-Chroma vector-store tests onto a SQLite-only fixture path.
- **Changes**:
  - Updated `src/asky/api/preload.py` so `preload_shortlist=False` short-circuits before shortlist policy evaluation instead of still consulting `PreloadPolicyEngine`.
  - Changed `shortlist_enabled_for_request()` to resolve interface-model defaults at call time rather than freezing them as import-time defaults.
  - Added preload regression coverage in `tests/asky/api/test_api_preload.py` to prove the planner is not invoked when shortlist execution is disabled.
  - Added an autouse unit-test fixture in `tests/conftest.py` that disables the plain-query helper unless the test is explicitly exercising helper/planner behavior.
  - Updated `tests/asky/api/test_api_library.py` so the helper-notice regression test opts back into helper mode explicitly.
  - Patched `tests/asky/storage/test_sessions.py::test_deferred_auto_rename_triggers_on_first_query` to use a deterministic generated name instead of paying real summarization latency.
  - Marked the default vector-store fixtures in `tests/asky/research/test_research_vector_store.py` as SQLite-only by disabling Chroma for non-Chroma tests.
  - Added default CLI test-module fixture patches in `tests/asky/cli/test_cli.py` to keep unit tests off plugin-runtime startup and live-banner behavior unless a test explicitly overrides them.
- **Gotchas**:
  - The shared helper-disabling fixture will hide helper behavior unless a test opts back in. Any future helper/planner regression tests need to patch `INTERFACE_MODEL` and `INTERFACE_MODEL_PLAIN_QUERY_ENABLED` explicitly, or live under the existing helper-policy allowlist.
  - The preload fix is user-visible correctness too, not just a test optimization. A caller that disables shortlist should never spend time on planner resolution.
- **Verification**:
  - Baseline before changes: `/usr/bin/time -p uv run pytest -q` -> `1400 passed in 37.78s` (`real 38.28`)
  - Targeted preload regression: `uv run pytest tests/asky/api/test_api_preload.py -q -n0` -> `18 passed in 0.22s`
  - Targeted helper regression: `uv run pytest tests/asky/api/test_api_turn_resolution.py::test_memory_trigger_prefix_removal_unicode_safe -q -n0 --durations=5` -> `1 passed in 0.12s`
  - Targeted storage regression: `uv run pytest tests/asky/storage/test_sessions.py::test_deferred_auto_rename_triggers_on_first_query -q -n0 --durations=5` -> `1 passed in 0.20s`
  - Final full suite: `/usr/bin/time -p uv run pytest -q` -> `1401 passed in 26.22s` (`real 26.39`)

## 2026-03-10: Stabilized Recorded CLI Coverage and Runtime

- **Summary**: Finished the exhaustive CLI integration coverage follow-up by removing debug artifacts, restoring truthful matcher policy, minimizing the recorded plugin roster, and cutting the slow subprocess realism path down to a bounded single slow test.
- **Changes**:
  - Updated `tests/integration/cli_recorded/cli_surface.py` and `tests/integration/cli_recorded/test_cli_surface_manifest.py` so the manifest is authoritative, ownership is complete, and persona subcommand parity is checked in-process instead of shelling out.
  - Refactored `tests/integration/cli_recorded/conftest.py` to enable only per-test plugins, keep the real-provider transcriber tool surface, reuse the fake LLM port safely, and apply stricter request matching only where replay is deterministic.
  - Updated `tests/integration/cli_recorded/helpers.py` to reinitialize plugin runtime per isolated HOME and use a deterministic local session-name fallback instead of spending model turns on title generation during recorded replay.
  - Updated `tests/integration/cli_recorded/test_cli_plugin_surface_recorded.py`, `tests/integration/cli_recorded/test_cli_persona_recorded.py`, and related harness ownership so plugin-backed flags explicitly opt in to the plugins they require.
  - Refined `tests/integration/cli_recorded/test_cli_interactive_subprocess.py` so PTY runs stop after child exit, the fake-LLM subprocess smoke test disables unrelated tools/shortlisting, and the only intentionally slower subprocess case is marked `slow`.
  - Fixed `src/asky/cli/daemon_config.py` so password masking is only enabled on a real TTY, avoiding hangs in headless and piped subprocess integration runs.
  - Updated `docs/testing_recorded_cli.md` so the matcher policy, plugin isolation, and daemon/browser boundary patching notes describe the actual shipped harness.
- **Verification**:
  - `uv run pytest tests/integration/cli_recorded/test_cli_interactive_subprocess.py -q -o addopts='-n0 --record-mode=none' --durations=10` (`4 passed in 5.34s`; slowest single test `4.75s`)
  - `uv run pytest tests/integration/cli_recorded/test_cli_surface_manifest.py -q -o addopts='-n0 --record-mode=none' --durations=10` (`5 passed in 2.74s`)
  - `uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=none' --durations=20` (`54 passed, 5 skipped in 14.30s`)
  - `ASKY_CLI_REAL_PROVIDER=1 uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=none' -m real_recorded_cli` (`5 passed, 54 deselected in 2.85s`)
  - `/usr/bin/time -p uv run pytest -q` (`1409 passed in 77.83s`; `real 78.01`)

## 2026-03-09: Single HTML Report Per Session & Summarized Auto Session Titles

- **Summary**: Unified automatic session naming using an LLM short-title summarizer, changed session HTML reports to upsert by `session_id` instead of appending, and updated the sidebar index to render session reports as single entries with resume copy actions.
- **Changes**:
  - Replaced keyword-based session naming with a shared short-title summarization flow for both new auto-created sessions and history-to-session conversions.
  - Modified HTML report saving to upsert the session file by `session_id`, generating a new timestamped file and deleting the old one, while keeping a single archive entry.
  - Allowed history items promoted to sessions to absorb matching single-turn reports.
  - Updated sidebar JS to treat sessions as individual items without collapsing by name, providing `asky --resume-session <id>` copy actions for them.

## 2026-03-09: HTML Report Markdown Renderer Replacement

- **Summary**: Replaced the naive regex-based markdown renderer (`asky-report.js`) with the standard `marked` library to fix structural and table rendering in HTML reports.
- **Changes**:
  - Downloaded the UMD build `marked.min.js` to `src/asky/data/`.
  - Updated `rendering.py` to use `marked.min.js` instead of `asky-report.js`.
  - Modified `template.html` to load `marked.min.js` via a regular `<script>` tag and render content synchronously using `marked.parse()`.
  - Removed `asky-report.js`.
- **Gotchas**: Initially tried the ES module variant (`marked.esm.js`), but it failed due to browser CORS restrictions on `file://` protocols. Regular script tag inclusion is used instead.

## 2026-03-09: OpenRouter Reasoning Flag and Interface Tracing Refinements

- **Summary**: Added support for OpenRouter's `reasoning` flag and refined interface tracing/policy logic to improve transparency and control.
- **Changes**:
  - Added `reasoning` parameter to OpenRouter configuration and registered it as a boolean in the CLI.
  - Implemented automatic payload wrapping for the `reasoning` flag in the API client to match OpenRouter's `{ "enabled": boolean }` requirement.
  - Fixed interface policy engine to conditionally pass `trace_callback` only when double-verbose mode (`-vv`) is enabled, preventing unwanted trace leaks in standard verbose mode.
  - Refined the plain-query interface helper prompt in `prompts.toml` with stricter guidance for faster responses and smarter shortlisting (preferring `search_only` when enabled).
  - Cleaned up `InterfaceQueryPolicyEngine` test data to use consistent multi-line formatting for memory actions.
  - Added regression tests for `InterfaceQueryPolicyEngine` to verify correct `trace_callback` propagation.
- **Verification**:
  - `pytest tests/asky/api/test_interface_query_policy.py` passed (6 passed).
  - Verified `reasoning` parameter registration in `src/asky/cli/openrouter.py`.
  - Verified payload mapping in `src/asky/core/api_client.py`.

## 2026-03-09: Added Plain-Query Interface Helper

- **Summary**: Added a plain-query interface helper for standard turns and closed the follow-up gaps around activation, tool constraints, global-memory safety, and CLI notice delivery.
- **Changes**:
  - Introduced `InterfaceQueryPolicyEngine` and `InterfaceQueryPolicyDecision` for standard non-research turns.
  - Added `interface_model_plain_query_enabled` and `interface_model_plain_query_prompt_enrichment_enabled`, plus matching `AskyConfig` overrides and `PreloadResolution` helper metadata.
  - Wired the helper into standard-turn execution so it can shape shortlist behavior, gate `web_search`/`get_url_content`/`get_url_details`, and append prompt enrichment without replacing the original query.
  - Added helper-driven automatic global-memory capture before preload recall, with strict global-only validation and sanitization before `execute_save_memory()`.
  - Restored explicit activation semantics so an empty `interface_model` disables the helper instead of falling back to the default model.
  - Enforced hard constraints for `lean` turns and turn-scoped disabled tools so helper side effects do not bypass caller intent.
  - Fixed helper notice routing so prompt-enrichment and memory notices survive the early callback path and render in bold green after the final answer in the CLI.
  - Added API and CLI regression coverage for helper gating, memory payload validation, and the callback-to-post-answer notice lifecycle.
  - Updated architecture/configuration/memory docs and helper-related AGENTS guidance to match the shipped behavior.
- **Verification**:
  - Scoped helper tests were added and passed across API, config, memory, and CLI coverage.
  - Full suite remained green during feature integration and follow-up fixes.

## 2026-03-08: Added Tavily Search Provider Integration

- **Summary**: Integrated Tavily as a first-class search provider.
- **Changes**:
  - Added `TAVILY_API_URL` and `TAVILY_API_KEY_ENV` config defaults.
  - Implemented `_execute_tavily_search` using `requests` with standard mapping.
  - Updated `execute_web_search` to support `SEARCH_PROVIDER="tavily"`.
  - Added unit tests for Tavily search execution and dispatch logic.
- **Verification**: All 1342 tests pass.

## 2026-03-05: Corrected Research Lane Coverage and Gate Scope

- **Summary**: Corrected the new research testing strategy so real-provider replay and live research checks now use actual model-backed `-r` turns, and widened the quality gate scope to include pytest policy changes in `pyproject.toml`.
- **Changes**:
  - Reworked `tests/integration/cli_recorded/test_cli_real_model_recorded.py`:
    - kept the two non-research real-provider invariants,
    - replaced manual `--query-corpus` research checks with model-backed local-corpus prompts for UDHR, OAuth, and subject-awareness follow-up,
    - strengthened subject-awareness assertions to verify both Beta facts and absence of Alpha-topic bleed.
  - Reworked `tests/integration/cli_live/test_cli_research_live.py` to mirror the same model-backed research coverage instead of deterministic manual retrieval checks.
  - Extended `tests/integration/cli_recorded/helpers.py` with whitespace-insensitive fragment assertions used by the new invariant-style checks.
  - Added `tests/scripts/test_run_research_quality_gate.py` to prove `scripts/run_research_quality_gate.sh` triggers for `pyproject.toml` changes and skips unrelated diffs.
  - Updated `scripts/run_research_quality_gate.sh` so `pyproject.toml` is treated as research-scoped because marker registration and default lane exclusions live there.
  - Refreshed real-provider cassettes for `tests/integration/cli_recorded/test_cli_real_model_recorded.py`.
  - Updated `docs/testing_recorded_cli.md` to state that:
    - **Tool Isolation**: Web and research tools are disabled in the test config to prevent non-deterministic external calls.
    - **Internal Boundary Patching**: Dispatch tests for background services (like `--daemon` or `--browser`) patch at the `asky.cli.main` boundary. This ensures we verify that the CLI correctly calls the intended launcher without actually spawning long-lived background processes during integration runs.
    - real/live research lanes must use model-backed `-r` turns,
    - deterministic `--query-corpus` coverage belongs in the fake recorded lane,
    - `pyproject.toml` is part of research-gate scope.
  - Updated `docs/research_testing_strategy.md`, `tests/AGENTS.md`, and `ARCHITECTURE.md` to state that:
    - real/live research lanes must use model-backed `-r` turns,
    - deterministic `--query-corpus` coverage belongs in the fake recorded lane,
    - `pyproject.toml` is part of research-gate scope.
- **Verification**:
  - Session baseline before fix: `uv run pytest -q` -> `1383 passed in 17.96s`.
  - Gate regression test: `uv run pytest tests/scripts/test_run_research_quality_gate.py -q` -> `2 passed in 1.04s`.
  - Real recorded replay: `ASKY_CLI_REAL_PROVIDER=1 uv run pytest tests/integration/cli_recorded/test_cli_real_model_recorded.py -q -o addopts='-n0 --record-mode=none'` -> `5 passed in 3.19s`.
  - Live lane: `uv run pytest tests/integration/cli_live/test_cli_research_live.py -q -o addopts='-n0 -m live_research'` -> `4 passed in 20.95s`.
  - Final default full suite: `uv run pytest -q` -> `1385 passed in 19.78s`.

## 2026-03-05: Research Capability Test Strategy Upgrade (Fake + Real Recorded + Live Gate)

- **Summary**: Upgraded research integration testing from lightweight smoke checks to a three-lane capability strategy with realistic corpus fixtures, real-provider replay coverage, and a mandatory path-scoped quality gate.
- **Changes**:
  - Added committed realistic corpus fixtures under `tests/fixtures/research_corpus/` and a focused local subject-awareness corpus at `tests/fixtures/research_corpus/subject_awareness_v1/` (multi-file + PDF).
  - Reworked `tests/integration/cli_recorded/test_cli_research_local_recorded.py` to assert meaningful deterministic behavior:
    - persisted research session profile contracts,
    - follow-up profile continuity,
    - deterministic `corpus query` output semantics,
    - deterministic section listing and explicit-source error paths.
  - Extended recorded harness/config:
    - `tests/integration/cli_recorded/conftest.py` now supports fake and real-provider setup paths and exposes realistic source/fact fixtures aligned with `queries_answers.md`.
    - `tests/integration/cli_recorded/helpers.py` gained transient provider retry helper for live/real model instability handling.
  - Added real-provider recorded lane file:
    - `tests/integration/cli_recorded/test_cli_real_model_recorded.py`
    - Includes non-research real-model invariants plus deterministic research retrieval/subject-pivot checks based on realistic fixtures.
  - Added live slow lane:
    - `tests/integration/cli_live/conftest.py`
    - `tests/integration/cli_live/test_cli_research_live.py`
    - Includes live model healthcheck plus research retrieval/subject-pivot checks over realistic corpus data.
  - Added marker policy updates in `pyproject.toml`:
    - new markers: `real_recorded_cli`, `live_research`
    - default full suite now excludes `live_research` in addition to existing recorded/subprocess exclusions.
  - Upgraded cassette workflows:
    - `scripts/refresh_cli_cassettes.sh` now supports `fake|real|all` modes with clear key checks.
  - Added mandatory path-scoped gate:
    - `scripts/run_research_quality_gate.sh`
    - Runs fake replay, real replay, and live research checks when research-scoped paths changed.
  - Updated docs:
    - `docs/testing_recorded_cli.md`
    - `docs/research_testing_strategy.md`
    - `tests/AGENTS.md`
    - `ARCHITECTURE.md`
    - Clarified enforcement semantics: gate is explicit-run only, with concrete `pre-push` and CI required-check integration examples.
- **Verification**:
  - Baseline before change: `uv run pytest -q` -> `1383 passed in 13.69s`.
  - Local recorded file: `uv run pytest tests/integration/cli_recorded/test_cli_research_local_recorded.py -q -o addopts='-n0 --record-mode=none'` -> `5 passed`.
  - Real recorded replay: `ASKY_CLI_REAL_PROVIDER=1 uv run pytest tests/integration/cli_recorded/test_cli_real_model_recorded.py -q -o addopts='-n0 --record-mode=none'` -> `5 passed`.
  - Live lane: `uv run pytest tests/integration/cli_live -q -o addopts='-n0 -m live_research'` -> `4 passed in 39.07s`.
  - Quality gate: `./scripts/run_research_quality_gate.sh --base HEAD~1 --head HEAD` -> passed all three stages (fake replay, real replay, live checks).
  - Refresh scripts:
    - `./scripts/refresh_cli_cassettes.sh fake` -> passed.
    - `ASKY_CLI_REAL_PROVIDER=1 ./scripts/refresh_cli_cassettes.sh real` -> passed.
  - Default recorded replay lane: `uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=none'` -> `15 passed, 5 skipped`.
  - Final full suite: `uv run pytest -q` -> `1383 passed in 16.95s` (post-change rerun; earlier post-change run was `20.21s`).

## 2026-03-04: Recorded CLI Integration Framework

- **Summary**: Stabilized the recorded CLI integration framework, scoped network guards, fixed in-process/subprocess harnesses, and aligned default/full-suite behavior with explicit recorded-lane execution.
- **Changes**:
  - Added `pytest-recording` dev dependency.
  - Added/kept explicit markers: `recorded_cli`, `subprocess_cli`, `live_record`.
  - Scoped root network blocking and root HOME/DB isolation to avoid global side effects on non-recorded tests.
  - Recorded lane now uses isolated per-test config/home and canonical alias injection with deterministic fake endpoint behavior.
  - In-process helper now isolates shell lock path per test HOME and reloads core CLI/config/storage modules per invocation.
  - Subprocess harness now uses the real `asky` entrypoint and stable PTY read loop.
  - Refresh workflow script now bypasses default addopts marker deselection and records only `recorded_cli` tests.
  - Default full-suite addopts now exclude `recorded_cli`/`subprocess_cli`; recorded lane is run via explicit commands.
  - Updated docs (`docs/testing_recorded_cli.md`, `ARCHITECTURE.md`, `tests/AGENTS.md`) to match verified commands.
  - Unified test-home isolation across the entire suite: all tests now run with `HOME`/`ASKY_HOME`/`ASKY_DB_PATH` rooted under `tests/.test_home/` with per-test/per-worker subdirectories.
  - Updated recorded/subprocess fixtures to also use `tests/.test_home` roots.
  - Added repository ignore rule for `tests/.test_home/` temporary artifacts.
- **Verification**:
  - `ASKY_CLI_RECORD=1 uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=once' -m recorded_cli` (12 passed).
  - `uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=none'` (14 passed).
  - `uv run pytest -q` (1383 passed in 10.64s; real 10.85s).

## 2026-03-03: Reorganized Test Suite into Mirrored Component Structure

- **Summary**: Refactored `tests/` to mirror `src/asky/` for faster navigation, with explicit buckets for integration, performance, and script tests.
- **Changes**:
  - Moved component tests into `tests/asky/<package>/...` (api, cli, core, daemon, config, storage, memory, research, evals, plugins).
  - Split plugin tests into `tests/asky/plugins/<plugin_name>/...` (including `xmpp_daemon`, `persona_manager`, transcribers, GUI, and delivery plugins).
  - Moved cross-cutting suites into:
    - `tests/integration/`
    - `tests/performance/`
    - `tests/scripts/`
  - Updated path-sensitive tests to locate repository root by searching for `pyproject.toml`:
    - `tests/performance/test_startup_performance.py`
    - `tests/scripts/test_devlog_weekly_archiver.py`
  - Updated `tests/AGENTS.md` and `ARCHITECTURE.md` to document the new structure.
- **Verification**:
  - Pre-refactor baseline: `uv run pytest -q` (`1383 passed in 9.48s`, `real 9.67s`).
  - Post-refactor: `uv run pytest -q` and targeted directory runs to confirm path updates and collection behavior.

## 2026-03-03: Configurable Local-Ingestion Security Gates

- **Summary**: Implemented configurable security gates for local-source ingestion to mitigate data exfiltration risks from prompt injections.
- **Changes**:
  - Added `allow_absolute_paths_outside_roots` to `research.toml` (default `false`). When `true`, absolute paths can be ingested even if outside `local_document_roots`.
  - Added `allowed_ingestion_extensions` to `research.toml` (default `[]`). When non-empty, restricts ingestion surface to the configured global allowlist.
  - Enforced extension allowlist globally across built-in readers, plugin handlers, and XMPP URL ingestion.
  - CLI `-r` and local adapters now enforce absolute-path configuration checks.
  - Updated `ARCHITECTURE.md`, `research_mode.md`, `troubleshooting.md`, and relevant `AGENTS.md` files to reflect new policies.
- **Verification**:
  - Wrote new tests in `test_research_corpus_resolution.py`, `test_research_adapters.py`, `test_local_source_handler_plugins.py`, and `test_xmpp_document_ingestion.py`.
  - `uv run pytest tests/test_local_ingestion_flow.py -q` passes.
  - `time uv run pytest -q` runtime baseline holds with pre-existing unrelated failures preserved.

## 2026-03-03: Weekly DEVLOG Archiver Script with Lean-Mode Intro Generation

- **Summary**: Added a dedicated script to archive old DEVLOG entries by ISO week with flexible batching and generate a managed weekly intro using installed `asky` in lean mode.
- **Changes**:
  - Added `scripts/devlog_weekly_archiver.py`:
    - Parses dated entries from markdown headings (`## YYYY-MM-DD ...`) and preserves preamble.
    - Applies a split gate only when source size exceeds `75 * 1024` bytes.
    - Separates current ISO-week entries from older entries.
    - Buckets older entries by contiguous ISO week and merges buckets until each archive batch reaches at least `750` lines when possible.
    - Writes archives to `devlog/archive/` with creation-date naming (`YYYY.MM.DD.md`) and collision-safe suffixes.
    - Runs `asky -L -r <archive>` to generate a summary intro and injects/replaces a managed intro block in the source file.
    - Supports optional positional source-file argument; defaults to `devlog/DEVLOG.md`.
  - Added `tests/test_devlog_weekly_archiver.py`:
    - Covers heading parsing variants, batch merging threshold, collision-safe filenames, size-gate no-op behavior, full archive+rewrite flow, and non-zero exit on summary failure.
- **Verification**:
  - `uv run pytest tests/test_devlog_weekly_archiver.py -q` (6 passed)
  - `uv run pytest -q` (1378 passed in 9.60s; `real 9.78s`, baseline `real 11.64s`)

## 2026-03-03: Fix Per-Session Inline Hint Persistence for Newly Created Sessions

- **Summary**: Fixed inline-help cadence so `per_session` hints shown before session creation are persisted once the session ID becomes available after the first turn.
- **Root Cause**: Pre-dispatch hint rendering can run before a new session exists, so `session_id` was `None` and `__inline_help_seen` could not be updated. This caused the same `per_session` hint to reappear on the next invocation in that same session.
- **Changes**:
  - Updated `src/asky/cli/inline_help.py`:
    - `render_inline_hints(...)` now returns rendered `CLIHint` items.
    - Added `mark_hints_seen_for_session(session_id, hints)` to persist only `frequency="per_session"` hints once a session ID is known.
  - Updated `src/asky/cli/main.py`:
    - Captures pre-dispatch rendered hints on parsed args (`_pre_dispatch_rendered_hints`) for later persistence.
  - Updated `src/asky/cli/chat.py`:
    - After turn completion, persists pre-dispatch `per_session` hints when `turn_result.session_id` exists.
  - Updated tests:
    - Added regression test in `tests/test_inline_help.py` for:
      - pre-dispatch render with `session_id=None`,
      - late persistence after session resolution,
      - suppression on next invocation in same session.
- **Verification**:
  - `uv run pytest tests/test_inline_help.py tests/test_cli.py -q` (107 passed)
  - `uv run pytest -q` (1372 passed)

## 2026-03-02: Added Generic CLI Inline Help Framework

- **Summary**: Implemented an extensible CLI-wide inline help framework to print concise one-line operational guidance.
- **Changes**:
  - Added `asky.cli.inline_help` to handle deduplication, frequency capping (`per_session` vs `per_invocation`), and CLI rendering.
  - Implemented the first built-in provider: research source-mode reminders (`local_only`, `mixed`, `web_only`) alerting users how to switch modes based on their pointer.
  - Added `CLIHintContext` and `CLIHint` contracts to `asky.plugins.base.AskyPlugin`.
  - Added `get_cli_hint_contributions` classmethod hook for static (pre-dispatch) plugin hint contributions based on parsed args.
  - Added `CLI_INLINE_HINTS_BUILD` hook for runtime (post-turn) contextual hints during active chat sessions.
  - Wired hint emissions to the main parser path, persona parser path, and post-turn chat path while skipping internal daemon/spawn paths.
- **Verification**: Tests passing.

## 2026-03-02: Documented Shortlist Behavior Across Research Pipelines

- **Summary**: Clarified shortlist behavior and rationale across standard, research `web_only`, research `local_only`, research `mixed`, and deterministic corpus-command pipelines.
- **Changes**:
  - Updated user docs:
    - `docs/research_mode.md`
    - `docs/document_qa.md`
  - Updated internal docs:
    - `ARCHITECTURE.md`
    - `src/asky/api/AGENTS.md`
    - `src/asky/research/AGENTS.md`
    - `src/asky/cli/AGENTS.md`
  - Added explicit notes that `local_only` is a hard shortlist-disable path by design, including rationale and how users can switch to `mixed` (`-r "...,web"`) or `web_only` profiles.
  - Added user phrasing guidance for triggering shortlist in eligible modes and for requesting deeper page-level verification beyond search snippets.
- **Verification**:
  - `uv run pytest` (1366 passed)

## 2026-03-10: Exhaustive Integration Test Coverage for CLI Surface

- **Summary**: Implemented exhaustive integration coverage for the entire asky CLI surface, covering core chat controls, history/session management, manual research commands, user memory, personas, and plugin-contributed flags.
- **Why**: To provide a deterministic, fast, and robust quality gate that prevents regressions in CLI parsing, orchestration, and rendering without requiring live LLM access.
- **Key Changes**:
  - Added `tests/integration/cli_recorded/test_cli_session_recorded.py` (history/session management).
  - Added `tests/integration/cli_recorded/test_cli_history_session_recorded.py` (message history).
  - Added `tests/integration/cli_recorded/test_cli_chat_controls_recorded.py` (model aliases, turns, lean mode, etc.).
  - Added `tests/integration/cli_recorded/test_cli_memory_surface_recorded.py` (memory list/delete/clear).
  - Added `tests/integration/cli_recorded/test_cli_persona_recorded.py` (persona lifecycle and @mentions).
  - Added `tests/integration/cli_recorded/test_cli_plugin_surface_recorded.py` (email, push, browser, daemon).
  - Enhanced `tests/integration/cli_recorded/test_cli_interactive_subprocess.py` with `model add` and `daemon edit` flows.
  - Fixed bug in `SQLiteHistoryRepository.delete_sessions` to support session names.
  - Improved `conftest.py` with stable worker-specific ports for the fake LLM server and enforced isolation.
  - Updated VCR configuration to match on request bodies for turn-level determinism.
- **Verification**:
  - `uv run pytest tests/integration/cli_recorded` (43 passed, 5 skipped) - all green in `none` record mode.

## 2026-03-02: Prevent Silent Completion on Empty Graceful-Exit Final Answer

- **Root Cause**: In the max-turn graceful-exit path, if the forced final model call returned empty content, `ConversationEngine` could return an empty `final_answer` without raising, which allowed CLI flows to end without any visible assistant output.
- **Summary**: Added deterministic recovery in graceful-exit so users always receive a terminal response.
- **Changes**:
  - Updated `src/asky/core/engine.py`:
    - Added one retry for empty graceful-exit final-answer responses.
    - Added a deterministic fallback message when graceful-exit responses remain empty after retry.
  - Updated docs:
    - `ARCHITECTURE.md`
    - `src/asky/core/AGENTS.md`
- **Tests Added**:
  - `tests/test_llm.py::test_graceful_exit_empty_response_retries_once`
  - `tests/test_llm.py::test_graceful_exit_empty_response_falls_back`
- **Verification**:
  - `uv run pytest tests/test_llm.py -q` (25 passed)
  - `uv run pytest` (1366 passed)

## 2026-03-02: Split Architecture Diagram into Focused Views

- **Summary**: Replaced the single dense Mermaid graph in `ARCHITECTURE.md` with smaller, task-oriented diagrams that are easier to read on normal and wide screens.
- **Changes**:
  - Added a high-level **System Context** diagram showing entrypoints, runtime core, plugin surface, data/config, and external systems.
  - Added a **Package Dependency Shape** diagram showing the dominant top-down dependency flow.
  - Added two **Runtime Sequence** diagrams (CLI turn and XMPP daemon turn) to document execution behavior without forcing all relationships into one graph.
  - Removed the previous all-in-one Mermaid graph from the overview section.
- **Verification**:
  - `uv run pytest` (1364 passed).

## 2026-03-02: Sync Mermaid Diagram with Current XMPP Plugin Structure

- **Summary**: Updated the architecture Mermaid graph to reflect the current daemon/XMPP module ownership and active XMPP service wiring.
- **Changes**:
  - Moved `interface_planner.py` representation from the `plugins/xmpp_daemon` subgraph to the `daemon` subgraph.
  - Removed obsolete in-plugin transcriber nodes (`voice_transcriber.py`, `image_transcriber.py`) from the XMPP subgraph.
  - Added active XMPP modules to the graph: `adhoc_commands.py`, `file_upload.py`, and `xmpp_formatting.py`.
  - Added corresponding wiring edges from `XMPPService` to the newly represented modules.
- **Verification**:
  - `uv run pytest` (1364 passed).

## 2026-03-02: Make Follow-Up Questions Reuse Ingested Corpus Reliably

- **Root Cause**: `PreloadResolution.is_corpus_preloaded` previously evaluated to false on cached local corpus follow-ups because it strictly checked for `indexed_chunks > 0`. This prevented deterministic bootstrap retrieval and caused the model to lose grounded context on subsequent turns.
- **Summary**: Modified `is_corpus_preloaded` to signify "usable corpus is available", checking both `ingested` handles and `preloaded_source_urls`. This ensures corpus context and appropriate tool configurations remain active for the duration of the research session.
- **Changes**:
  - `src/asky/api/types.py`: Updated `PreloadResolution.is_corpus_preloaded` logic to check `ingested` length and `preloaded_source_urls`.
  - `ARCHITECTURE.md` / `src/asky/api/AGENTS.md`: Documented the new trigger contract for bootstrap retrieval on follow-ups.
- **Tests Added/Updated**:
  - `tests/test_api_library.py`: Assert `is_corpus_preloaded=True` handles `indexed_chunks=0` properly.
  - `tests/test_api_library.py`: Added explicit test for `_build_bootstrap_retrieval_context` injection on cached follow-ups.

## 2026-03-02: Graceful Exit on Unconfigured Model

- **Summary**: Addressed an edge case where running `asky` for the first time without any configuration would crash with `KeyError: ''`. The CLI now gracefully exits and instructs the user to configure a model.
- **Changes**:
  - Added a check in `src/asky/cli/chat.py` to intercept empty or missing models before accessing the `MODELS` dictionary.
  - Provided a clear error message suggesting the user run `asky config`.
- **Verification**:
  - Tested locally with empty model strings (`--model ""`).
  - `uv run pytest` (1363 tests passed).

## 2026-03-02: Clarified Section Query vs Section ID Documentation

- **Summary**: Updated docs to explain why positional `section-001` fails under `--summarize-section` / `corpus summarize` and how to use deterministic ID selection correctly.
- **Changes**:
  - Updated user docs:
    - `docs/research_mode.md`
    - `docs/document_qa.md`
    - `docs/configuration.md`
  - Updated internal docs:
    - `ARCHITECTURE.md`
    - `src/asky/cli/AGENTS.md`
    - `src/asky/research/AGENTS.md`
  - Added explicit contract notes:
    - positional `--summarize-section <value>` is always `SECTION_QUERY` (strict title/query matching),
    - `corpus summarize <value>` maps to the same `SECTION_QUERY` path,
    - exact section IDs must use `--section-id`.
  - Added explicit pitfall + fix examples (failing positional `section-001` vs correct `--section-id section-001` and title-query usage).
- **Verification**:
  - `rg -n "SECTION_QUERY|section-id|Common Pitfall|strict section match|corpus summarize" docs ARCHITECTURE.md src/asky/cli/AGENTS.md src/asky/research/AGENTS.md DEVLOG.md`
  - `uv run pytest`

## 2026-03-02: Follow-up Fixes for Implicit Session-Delete Research Cleanup

- **Summary**: Addressed remaining robustness and documentation issues after introducing implicit research cleanup on `session delete`.
- **Changes**:
  - Updated `src/asky/storage/sqlite.py`:
    - Changed `_cleanup_research_state()` to isolate failures per session ID during batch cleanup.
    - If one session's vector-store cleanup fails, remaining session IDs still attempt cleanup.
    - Added explicit initialization-failure logging for vector-store bootstrap path.
  - Updated `tests/test_storage.py`:
    - Stabilized `test_delete_sessions_real_research_cleanup` by creating the session first and inserting findings with `session_id=str(sid)`.
    - Removed brittle assumption that the session ID is always `1`.
  - Updated top-level help text in `src/asky/cli/main.py`:
    - `session clean-research` description now matches real behavior (session findings/vectors and session corpus links/paths), avoiding misleading "research cache data" wording.
- **Verification**:
  - `uv run pytest tests/test_storage.py -q`
  - `uv run pytest tests/test_cli.py -q`
  - `uv run pytest`

## 2026-03-01: Fixed False Positive Section Detection for Statistical Notation

- **Summary**: `_looks_like_heading` was misidentifying statistical terms and citation strings as section headings in PDF documents. Strings like "ΔAICc", "AR(1)", "AR(2)", and "(SC): SEDAR; 2016." scored above the detection threshold because they have high uppercase/titlecase ratios and appear surrounded by blank lines in extracted PDF text.
- **Changes**:
  - Added `STAT_NOTATION_PATTERN` constant to `sections.py`.
  - Added three early-return filters in `_looks_like_heading`:
    - Lines containing ";" are rejected (citations, not headings).
    - Lines matching `\b[A-Za-z]+\(\d` with ≤ 3 words are rejected (statistical model notation: AR(1), F(2,30), etc.).
    - Single-token non-ASCII lines not in the document TOC are rejected (math symbols like ΔAICc, R²).
  - Added 6 new tests in `test_research_sections.py`.
- **Verification**: 1361 passed.
- **Gotchas**: The "all of them" follow-up failure was a cascade — garbage sections have trivial content so `summarize_section` returned "too small" errors. Fixing detection resolves that flow.

## 2026-03-01: Implicit Research Cleanup on Session Deletion

- **Summary**: Implemented implicit research cleanup for all session deletion paths. Deleting a session now automatically removes its associated research findings, embeddings, and document upload links.
- **Changes**:
  - Modified `SQLiteHistoryRepository.delete_sessions` in `src/asky/storage/sqlite.py`:
    - Added `_cleanup_research_state()` internal helper.
    - Helper reordered to call `VectorStore.delete_findings_by_session()` **before** local SQLite writes (fixing SQLite lock conflicts/OperationalError).
    - Helper uses `call_attr` (lazy loading) to invoke vector cleanup.
    - Helper also clears matching rows from the `session_uploaded_documents` table in the main database.
  - Added missing `import logging` and `logger` to `src/asky/storage/sqlite.py`.
  - Updated CLI help text in `src/asky/cli/main.py` (both top-level and grouped sub-help) for `session delete` and the `--delete-sessions` flag to reflect research data cleanup.
- **Documentation**:
  - Updated `ARCHITECTURE.md` to reflect that session deletion includes research cleanup.
  - Updated `src/asky/storage/AGENTS.md` and `src/asky/cli/AGENTS.md` with the new behavior details.
- **Verification**:
  - Added `test_delete_sessions_implicit_research_cleanup`, `test_delete_sessions_implicit_research_cleanup_failure_resilience`, and `test_delete_sessions_real_research_cleanup` to `tests/test_storage.py`.
  - `test_delete_sessions_real_research_cleanup` specifically verifies that SQLite lock ordering is correct and findings are actually deleted from the common DB file.
  - Verified with `uv run pytest tests/test_storage.py -q`.
  - Verified full suite passes.

## 2026-03-01: Auto Chunk Target for Hierarchical Summarization

- **Summary**: Added sentinel-based auto sizing for hierarchical summarization chunk targets.
- **Changes**:
  - Updated `src/asky/data/config/general.toml` default:
    - `summarizer.hierarchical_chunk_target_chars = 0`
  - Updated `src/asky/config/__init__.py` to treat `hierarchical_chunk_target_chars`
    as an int-safe value with `0` as the default sentinel.
  - Updated `src/asky/summarization.py`:
    - Added runtime resolution for effective chunk target.
    - If configured value is `> 0`, uses it directly.
    - If configured value is `0`, auto-resolves to `SUMMARIZATION_INPUT_LIMIT`.
    - If configured value is negative, logs a warning and falls back to
      `SUMMARIZATION_INPUT_LIMIT`.
  - Added tests in `tests/test_summarization.py` to cover:
    - `0` sentinel auto-resolution path
    - explicit non-zero preservation path
    - negative-value fallback path
- **Documentation**:
  - Updated `src/asky/config/AGENTS.md` with sentinel behavior.
  - Updated `ARCHITECTURE.md` summarization section with auto-resolution note.
- **Verification**:
  - `uv run pytest tests/test_summarization.py -q`
  - `uv run pytest tests/test_config.py -q`
  - `uv run pytest`

## 2026-03-01: Fixed Transcriber ToolRegistry Registration Contract

- **Summary**: Fixed runtime transcriber tool registration failures caused by an outdated `ToolRegistry.register(...)` call shape.
- **Changes**:
  - Updated `voice_transcriber` and `image_transcriber` `TOOL_REGISTRY_BUILD` hooks to use `register(name, schema, executor)`.
  - Added dict-argument adapter executors so `ToolRegistry.dispatch()` can invoke transcriber tools correctly from model tool calls.
  - Added regression coverage in `tests/test_transcriber_tools.py` to validate real `ToolRegistry.dispatch()` behavior for both transcriber tools.
- **Verification**:
  - Targeted: `uv run pytest tests/test_transcriber_tools.py tests/test_voice_transcription.py tests/test_image_transcription.py -q`
  - Full suite: `uv run pytest` (1350 passed).

## 2026-03-01: Removed Background Summarization, Added On-Demand Summaries, and Fixed Shell Lock Persistence

- **Summary**: Implemented a set of performance and reliability fixes for research mode and session management.
- **Changes**:
  - **Removed Background Document Summarization**: Stopped all background "warm-up" document summarization in `ResearchCache` to save tokens and reduce background noise.
  - **On-Demand Synchronous Summaries**: Updated `get_link_summaries` tool to perform synchronous, on-demand summarization if a summary is missing or stale.
  - **Fixed Local Directory Ingestion**: Stopped creating and counting a pseudo-document for directories during local ingestion. Only discovered files are now counted.
  - **Fixed Shell Lock Persistence**: Removed the `atexit` registration that cleared the shell session ID on process exit. Sticky session locks now persist in the same shell until explicit detach or cleanup.
  - **CLI Refinements**: Removed the end-of-turn background-summary drain in `chat.py`.
- **Verification**:
  - Targeted tests: `uv run pytest tests/test_research_adapters.py tests/test_local_ingestion_flow.py tests/test_research_cache.py tests/test_research_tools.py tests/test_cli.py tests/test_safety_and_resilience_guards.py -q`
  - Full suite: `uv run pytest`
- **Gotchas**:
  - `get_link_summaries` may now take longer if it needs to generate a summary synchronously during the tool call.
  - `wait_for_background_summaries` and `shutdown` methods were removed from `ResearchCache`.
- **Status**: All targeted tests passed.

## 2026-03-01: Router/Transcriber Boundary Decoupling Fix

- **Summary**: Removed direct compile-time dependency from `xmpp_daemon.router` to transcriber plugin internals.
- **Changes**:
  - `router.py` now enqueues plain job payload dictionaries through a worker interface (`enabled` + `enqueue`) instead of importing transcriber job classes.
  - `voice_transcriber` and `image_transcriber` worker `enqueue()` paths now accept either native job dataclasses or dict payloads and normalize internally.
  - Updated `src/asky/plugins/xmpp_daemon/AGENTS.md` to document the boundary contract.
- **Verification**:
  - Targeted: `uv run pytest tests/test_xmpp_router.py tests/test_voice_transcription.py tests/test_image_transcription.py tests/test_xmpp_daemon.py -q`
  - Full suite: `uv run pytest` (1351 passed).

## 2026-03-01: Extraction of Media Transcribers into Capability Plugins

- **Summary**: Extracted XMPP-owned voice and image transcribers into standalone plugins (`voice_transcriber`, `image_transcriber`). Introduced `PLUGIN_CAPABILITY_REGISTER` hook for service sharing and `LOCAL_SOURCE_HANDLER_REGISTER` for extensible corpus ingestion.
- **Changes**:
  - Created `voice_transcriber` and `image_transcriber` plugins with dedicated services and workers.
  - Added `transcribe_audio_url` and `transcribe_image_url` tools (HTTPS-only) to standard and research registries.
  - Updated `research/adapters.py` to support plugin-provided file handlers via hooks.
  - XMPP daemon now resolves transcriber capabilities via hooks and depends on the new plugins.
  - Migrated media configuration from `xmpp.toml` to `voice_transcriber.toml` and `image_transcriber.toml` (hard cutover).
  - Removed legacy `XMPP_VOICE_*` and `XMPP_IMAGE_*` constants.
- **Gotchas**:
  - XMPP startup will now fail if `voice_transcriber` or `image_transcriber` plugins are disabled, as they are mandatory dependencies.
  - Security policy enforced: Model-callable tools only accept `https://` URLs.
  - Media URLs in XMPP chat remain transcription-only (no auto-ingest), but the same file types can now be ingested into research corpus via standard ingestion flows.
- **Follow-up**: Implement additional voice strategies for Linux/Windows to replace the `UnsupportedOSStrategy`.

## 2026-03-01 - Policy Constraint Compliance + Docs Alignment

- Replaced broad `except Exception` in `src/asky/api/preload_policy.py` with narrow transport-error handling (`requests.exceptions.RequestException`) and explicit invalid-response/config fail-safe branches.
- Updated `tests/test_preload_policy.py` to assert transport-error fallback reason.
- Updated required docs for parity plan compliance:
  - `ARCHITECTURE.md` now documents the shared adaptive shortlist policy stage.
  - `docs/xmpp_daemon.md` planner contract now includes `action_type=chat` and updated fallback text.
  - `src/asky/api/AGENTS.md` now documents adaptive shortlist precedence and provenance policy fields.
  - `src/asky/plugins/AGENTS.md` now states CLI/XMPP shortlist parity via shared API preload path.
- Status: 1344 tests passed.

## 2026-03-01 - Interface Model Parity & XMPP Plugin Migration

- **Feature**: Shared adaptive preload policy engine.
  - Implemented `src/asky/api/preload_policy.py` to provide a deterministic-first pre-handover policy layer.
  - Shortlist behavior is now consistent between CLI and XMPP: local-corpus turns are automatically prioritized, while ambiguous cases fall back to an interface model.
  - Shortlist is now disabled by default for non-local-corpus turns without clear web intent, saving LLM tokens and reducing latency.
  - Added `shortlist_policy_system` prompt in `src/asky/config/prompts.toml`.
- **Infrastructure**: Legacy XMPP daemon module migration.
  - Reconciled `src/asky/daemon/interface_planner.py` scope drift by moving it back to `src/asky/daemon/` to match architectural ownership.
  - Migrated all other XMPP logic to `asky.plugins.xmpp_daemon.*`.
  - Updated imports and tests to use the new plugin paths.
- **Traceability**: Enhanced preload results.
  - `PreloadResolution` now captures `shortlist_policy_source`, `shortlist_policy_intent`, and `shortlist_policy_diagnostics`.
  - Preload provenance in CLI verbose mode now includes these policy fields for easier debugging of shortlist decisions.
- **Docs**:
  - Restored true status of doc updates.
  - Created `src/asky/plugins/xmpp_daemon/AGENTS.md`.
  - Cleaned up `src/asky/daemon/AGENTS.md`.
- **Tests**:
  - Added `tests/test_preload_policy.py` for the new engine.
  - Updated 8 test files to reflect the XMPP plugin migration.
- **Status**: 1343 tests passed.

## 2026-03-01: Final XMPP Plugin Migration & Test Resolution

Resolved regressions and test failures introduced during the XMPP daemon migration and interface model refinements.

- **Test Fixes:**
  - Updated `tests/test_api_preload.py` and `tests/test_cli.py` to handle the expanded 5-value return from `shortlist_enabled_for_request`.
  - Fixed `test_xmpp_commands.py` failures by correctly mocking `print_session_command` and updating `CommandExecutor` to correctly route grouped commands.
  - Resolved `RuntimeWarning` in `test_xmpp_file_upload.py` by properly closing mocked coroutines.
- **XMPP Daemon Refinements:**
  - Added `GROUPED_DOMAIN_ACTIONS` to `CommandExecutor` to allow strict routing of grouped commands (`session`, `history`, etc.) without requiring a slash prefix in XMPP.
  - Fixed function name mismatches in `CommandExecutor` calling `history` module functions (added `_command` suffixes).
  - Genericized naked command normalization to let grouped domain actions pass through to the standard CLI parser logic.
- **Interface Model:**
  - Fixed P1 issue by removing broad `except Exception:` block in `PreloadPolicyEngine` to let failures propagate naturally.
  - Fixed P2 issue by evaluating the adaptive policy engine _before_ checking model override and global toggles in `src/asky/api/preload.py`, making local-corpus overrides work correctly.
  - Verified and tested the retry mechanism for empty LLM responses in `ConversationEngine`.
  - Ensured shortlist policy transparency by passing through all 5 enablement resolution variables in `AskyTurnResult`.

All 1344 tests passed (added 1 test for local_only precedence).

## 2026-03-01 - Policy Logic Refinement & Fail-Safe Implementation

Refined the preload policy engine and shortlist enablement precedence to ensure absolute adherence to local-only modes and graceful degradation on interface model failures.

- **Policy Engine Fail-Safe**: Re-introduced a targeted safety net in `PreloadPolicyEngine.decide`. If the interface model (LLM) call fails due to API issues or parsing errors, the turn now degrades gracefully to "shortlist disabled" instead of crashing the entire request.
- **Shortlist Precedence Fix**: Correctly prioritized `research_source_mode == "local_only"` over the `--shortlist on` override in `src/asky/api/preload.py`. Local-only research turns now always skip the web shortlist, even if an explicit "on" override is present.
- **Improved Traceability**: Updated CLI verbose output (`preload_provenance`) to consistently include all policy fields (`shortlist_policy_source`, `shortlist_policy_intent`, etc.) for easier debugging of automated shortlist decisions.
- **Tests**:
  - Updated `test_preload_policy_engine_interface_model_crash_fallback` to verify safe degradation.
  - Added `test_shortlist_enabled_resolution_local_only_overrides_on` to enforce precedence rules.
  - Extended `test_run_turn_emits_preload_provenance_event` to cover new policy fields.

Total tests: 1344 passed.

## 2026-03-01 - Strict Grouped Command Routing + Session Visibility

- **Issue**: Grouped domain commands like `session`, `history`, `memory`, `corpus`, and `prompts` could degrade into query execution when subcommands were missing/invalid, creating confusing behavior (including session-related ambiguity).
- **CLI fix**:
  - Added strict grouped-command validation in `src/asky/cli/main.py` before query fallback.
  - `session` (no action) now prints session grouped help and active shell-session status.
  - `session show` with no selector now resolves to current shell session (or prints no-active-session status).
  - Added argument-shape validation for grouped actions (for example `history show` selector format and no-extra-arg guards like `memory list extra`).
- **Session visibility fix**:
  - Added active-session helpers in `src/asky/cli/sessions.py`:
    - stale shell-lock cleanup detection,
    - `print_active_session_status()`,
    - `print_current_session_or_status()`.
- **Daemon/XMPP parity**:
  - Added grouped-command strict handling in:
    - `src/asky/daemon/command_executor.py`
    - `src/asky/plugins/xmpp_daemon/command_executor.py`
  - Known grouped domains now return usage/error instead of falling through to query execution.
  - `session show` without selector in remote command execution now prints current conversation session transcript.
- **Tests**:
  - Expanded `tests/test_cli.py` coverage for:
    - strict grouped command errors,
    - `session` no-action status/help,
    - `session show` no-selector behavior,
    - stale lock and no-active-session outputs,
    - follow-up query shell-session attachment (`run_chat` request includes shell session id).
  - Expanded `tests/test_xmpp_commands.py` for grouped command strict handling and `session show` no-selector behavior.
- **Docs updated**:
  - `ARCHITECTURE.md`
  - `src/asky/cli/AGENTS.md`
  - `src/asky/daemon/AGENTS.md`
  - `src/asky/plugins/AGENTS.md`
- **Status**: 1336 tests passed.

## 2026-03-01 - Handle Empty Model Responses

- **Issue**: Models intermittently returned empty strings (no content, no tool calls), causing the turn loop in `ConversationEngine` to exit abruptly without a final answer.
- **Fix**: Implemented a retry mechanism in `src/asky/core/engine.py`.
  - Added `empty_response_count` tracking.
  - If a response is empty, the engine now appends a corrective system prompt and retries (consuming another turn).
  - If the model fails twice consecutively, it aborts with a graceful apology message instead of an empty result.
- **Tests**: Added `test_empty_response_retry_success` and `test_empty_response_abort_after_retries` to `tests/test_llm.py`.
- **Status**: 1325 tests passed.

## 2026-03-01 - One-Shot Mode: Logic & Integration Fixes

- **Regex Improvement**: Relaxed `summarize` regex in `query_classifier.py` to match variations like "summarized", "summarization", and "summarizing". Updated unit tests to verify.
- **Prompt Composition Fix**: Refactored `append_research_guidance` in `prompts.py` to prevent early returns. This ensures that `local_kb_hint_enabled` and `section_tools_enabled` instructions are correctly appended even when one-shot mode guidance is active.
- **Integrated Verification**: Updated `test_one_shot_integration.py` to assert correct prompt composition with multiple guidance flags enabled.
- **Suite**: 1322 → 1323 passed.

- **Issue**: LLM (google/gemini-2.5-flash-lite) was ignoring the one-shot summarization guidance in the system prompt and asking clarifying questions despite being instructed not to.
- **Root Cause**: The original guidance text was too polite/suggestive ("Provide a direct, comprehensive summary without asking clarifying questions"). The LLM treated it as optional guidance rather than a hard requirement.
- **Fix**: Rewrote `append_one_shot_summarization_guidance()` in `src/asky/core/prompts.py` to use more forceful, directive language:
  - Changed header to "CRITICAL INSTRUCTION - One-Shot Summarization Mode"
  - Used imperative commands: "You MUST provide...", "DO NOT ask clarifying questions"
  - Added explicit "FORBIDDEN" section listing prohibited behaviors
  - Structured as numbered "Required Actions" for clarity
- **Testing**: Updated test assertion in `tests/test_one_shot_integration.py` to match new wording. All 1322 tests pass.
- **Impact**: The classification and prompt modification logic was already working correctly. This change only affects the wording of the guidance text sent to the LLM, making it more likely to follow instructions.
- **Follow-up**: User should test with real query to verify LLM now provides direct summaries. If issue persists, may need to try different LLM model or implement pre-calling `get_relevant_content` before LLM sees the query.

## 2026-03-01 - One-Shot Document Summarization

- **Feature**: Added intelligent query classification to detect one-shot summarization requests and provide direct answers for small document sets without clarifying questions.
- **Implementation**: Created `src/asky/research/query_classifier.py` with 6-step decision tree analyzing query keywords, corpus size, and vagueness. Classification runs during preload pipeline after local ingestion and adjusts system prompt guidance.
- **Configuration**: Added `[query_classification]` section to `research.toml` with configurable thresholds (default: 10 documents), aggressive mode (20 documents), and force_research_mode override.
- **Performance**: Classification adds <0.004ms overhead with ~383 bytes memory footprint. Deterministic results for same inputs.
- **Documentation**: Updated `docs/research_mode.md`, `docs/configuration.md`, `ARCHITECTURE.md`, and `src/asky/research/AGENTS.md` with one-shot mode examples and configuration details.
- **Spec location**: `.kiro/specs/one-shot-document-summarization-improvement/`
- **Gotchas**: Feature is enabled by default. Users can disable via `query_classification.enabled = false` or force research mode via `force_research_mode = true`. Classification only runs in research mode when `QUERY_CLASSIFICATION_ENABLED=true`.
- **Follow-up**: Manual testing requires user validation with real LLM calls (test guide in `temp/MANUAL_TESTING_GUIDE.md`).

## 2026-03-01 - Code Review Phase 6: Playwright Browser Plugin Fixes

- **F1/F6 fix (P3)**: Removed dead code `_session_path` and `_save_session` in `PlaywrightBrowserManager`. Persistence is correctly handled by Playwright's `launch_persistent_context`. Updated `AGENTS.md` to reflect actual profile directory storage.
- **F2 fix (P3)**: Added URL-pattern challenge detection to `_detect_challenge` to catch redirects to Cloudflare/hCaptcha challenge pages.
- **F3 fix (P2)**: Renamed internal `playwright_login` destination to `browser_login` for consistency with the `--browser` flag. Fixed stale `--playwright-login` references in documentation.
- **F4 fix (P3)**: Unified `intercept` default list in `playwright_browser.md` with the shipped code defaults (adding `shortlist` and `default`).
- **F5 fix (P4)**: Added `is_interactive()` guard to `open_login_session` to prevent blocking the event loop in daemon/non-interactive contexts.
- **F7 fix (P3)**: Made the 2-second post-load sleep configurable via `post_load_delay_ms` in plugin config.
- **Tests**: Added 3 new tests: `test_detect_challenge_url`, `test_open_login_session_daemon_guard`, and `test_post_load_delay_usage`.
- Suite: 1275 → 1278 passed.

## 2026-03-01 - Code Review Phase 5: XMPP Daemon & Routing

- **F5.1 fix (P1)**: Added `shutdown()` method to `VoiceTranscriber` and `ImageTranscriber` using None poison-pill sentinel + thread joining. Updated `XMPPService.stop()` to call both `shutdown()` methods before stopping the XMPP client. Previously, worker threads were daemon threads with blocking `queue.get()` and no shutdown mechanism — in-flight jobs would be abandoned on daemon stop.
- **F5.2 fix (P2)**: Updated `daemon/AGENTS.md` — was incorrectly stating `DaemonUserError` is raised for 0 transports; actual behavior allows 0 (sidecar-only mode).
- **F5.11 noted (P2)**: `voice_transcriber.py` and `image_transcriber.py` are duplicated in `daemon/` and `plugins/xmpp_daemon/`; tests import from old `daemon/` path. Flagged for cleanup.
- **F5.3/F5.5 tests**: Added shutdown lifecycle tests (4 tests) and remote policy gate test via `execute_command_text` path (1 test). Updated existing stop test to verify transcriber shutdown calls.
- **Verified**: Remote policy gate applied after preset expansion (correct), singleton lock cleanup on SIGKILL (POSIX-safe), room auto-rejoin handles non-existent rooms gracefully, TOML upload cannot inject blocked flags, XEP-0308 correction fallback works correctly, interface planner unification complete (no plugin fork).
- Suite: 1270 → 1275 passed.

## 2026-03-01 - Code Review Phase 4: User Memory & Elephant Mode

- **F4-1 fix**: Added `Optional` to `typing` imports in `memory/auto_extract.py` — was missing despite use in function signature (safe at runtime due to `from __future__ import annotations`, but would break `get_type_hints()`).
- **F4-2/F4-3 tests**: Added `TestElephantModeSessionGuard` (2 tests for guard logic) and `TestAutoExtractionThreadDispatch` (3 tests: daemon-thread invariant, lean suppression, extraction trigger conditions).
- **F4-4 documented**: `memory list` only shows global memories; session-scoped (elephant-mode) memories require session_id filter not exposed via CLI. No code change — left for future work.
- Suite: 1265 → 1270 passed.

## 2026-03-01 - XEP-0363 HTTP File Upload + Code Review Phase 3

- **XEP-0363 file upload**: Added `FileUploadService` for async file upload via XEP-0363 + OOB delivery via XEP-0066; registered `xep_0363` plugin in `xmpp_client.py`; singleton `get_file_upload_service()` for cross-plugin access.
- **Session compaction bug fix**: `compact_session()` now deletes pre-compaction messages after storing the summary. Previously, `build_context_messages()` included both the summary and all old messages, making compaction a no-op.
- **Evidence extraction heuristic**: Replaced magic number `>= 3` with `RESEARCH_EVIDENCE_SKIP_SHORTLIST_THRESHOLD` constant; replaced `print()` with `logger.warning()` in local ingestion flow.
- **ARCHITECTURE.md cleanup**: Removed `POST_TURN_RENDER` from deferred hooks list (already functional); added lean mode memory recall suppression test.
- Suite: 1258-1265 passed.

## 2026-02-28 - XMPP Polish + Logging + History Unification

- **Dev tooling**: Created `scripts/watch_daemon.sh` (entr-based auto-reload) and `docs/development.md`.
- **ChromaDB telemetry**: Disabled anonymized telemetry in both vector store clients.
- **Log improvements**: Conditional log archiving (DEBUG-only); configurable message truncation (`truncate_messages_in_logs`); fixed XMPP log leakage into `asky.log` via `propagate=False`.
- **History unification**: `history list/show/delete` now includes session-bound messages; session-agnostic ID expansion.
- **Lean mode fix**: `filename_hint` crash in `POST_TURN_RENDER` when HTML reports are skipped.
- **Corpus titles**: `_clean_document_title()` strips extensions, underscores, author suffixes; fixes useless search queries from raw filenames.
- **Gemini thinking leakage**: Extended `strip_think_tags()` to catch all `assistantcommentary` variants.
- **XMPP XHTML**: Inline markdown-to-XHTML conversion for bold/italic/code; plain fallback normalization aligned with XHTML payload.
- **Slashless commands**: Native slashless command support in `CommandExecutor` (fixes "session clear" treated as query).
- **Model selection fix**: Retry loop when OpenRouter search returns no results in `--config model add`.
- **Research parrot fix**: New `chat` action type in `InterfacePlanner` for non-research inputs; `execute_chat_text` overrides session research mode with `lean=True`.
- Suite: 1235-1258 passed.

## 2026-02-27 - XMPP Features + CLI Polish + Plugin Boundaries

- **Corpus-aware shortlisting**: `CorpusContext` carries document metadata into shortlist pipeline; YAKE-based query enrichment from corpus titles/keyphrases; zero LLM calls.
- **XMPP XHTML-IM**: XEP-0071 header rendering (setext/ATX to bold); XEP-0308 correction stanzas for progress updates; immutable `StatusMessageHandle`.
- **Query progress**: Reusable `QueryProgressAdapter` + `QueryStatusPublisher` with throttled status message updates (~2s).
- **Ad-hoc commands (XEP-0050)**: 13 commands (status, sessions, history, tools, memories, query, prompts, presets, transcripts); two-step actionable flows for prompts/presets; authorization with full-JID + bare fallback + session caching; XML-level fallbacks for stanza interface gaps.
- **Document upload**: XMPP document ingestion pipeline (HTTPS-only, extension/MIME validation, content-hash dedup, session corpus linking); auto-enables `local_only` research mode.
- **Plugin boundaries**: One-way dependency rule enforced; dynamic CLI contributions via `CLIContribution` system; `email_sender` and `push_data` moved to plugin packages.
- **CLI polish**: Dynamic grouped help from plugin contributions; roster sync for new bundled plugins; `answer_title` in `PostTurnRenderContext`.
- **Parallel flake fixes**: Preset config reads at call time; shared `clear_memories_non_interactive()`; document URL redaction ordering.
- Suite: 1175-1232 passed.

## 2026-02-26 - CLI Redesign + Session Config + Playwright

- **Unified CLI surface**: Grouped commands (`history`, `session`, `memory`, `corpus`, `prompts`); `asky --config model add/edit`, `asky --config daemon edit`; legacy flags fail fast with migration guidance.
- **Session-bound query defaults**: Persisted per-session model/tools/system-prompt/research/lean/summarize defaults; deferred auto-rename for unnamed sessions.
- **Session-bound shortlist**: `--shortlist on/off/reset/auto` with DB persistence; precedence: lean > request > session > model > general > mode.
- **Global shortlist config**: `general.shortlist_enabled` overrides mode-specific settings.
- **Playwright browser plugin**: `FETCH_URL_OVERRIDE` hook; CAPTCHA detection; persistent browser contexts; `keep_browser_open` config; DOM content-loaded wait strategy.
- **ChromaDB dimension fix**: Test fixtures now use isolated Chroma directories (was polluting production with dim=3).
- **Pytest parallel**: `pytest-xdist` default with `-n auto`; behavior-based test renaming.
- Suite: 1091-1115 passed.

## 2026-02-25 - Plugin System + Persona + Tray Refactor

- **XMPP daemon extracted to plugin**: `DaemonService` is transport-agnostic; `DAEMON_TRANSPORT_REGISTER` hook; all XMPP logic in `plugins/xmpp_daemon/`.
- **Tray refactor**: `TrayController` (platform-agnostic); `TRAY_MENU_REGISTER` hook for plugin-contributed entries; dynamic menu from `TrayPluginEntry` items; `LaunchContext` enum gates interactive prompts.
- **Persona plugin**: Complete CLI-driven persona management (`create/load/unload/list/alias/import/export`); `@mention` syntax; session-scoped binding; hook integration (SESSION_RESOLVED, SYSTEM_PROMPT_EXTEND, PRE_PRELOAD); 209 new tests.
- **Plugin runtime v1**: Manifest schema, deterministic hook registry, plugin manager with dependency ordering/cycle detection/failure isolation; turn lifecycle hooks throughout API/core layers.
- **XMPP formatting**: XEP-0393 message styling; ASCII table rendering with Unicode-aware column widths; hypothesis property-based tests.
- **Plugin extraction**: `POST_TURN_RENDER` promoted to supported hook; `PushDataPlugin` and `EmailSenderPlugin` as built-in plugins.
- **Portal-aware extraction**: Automatic detection of listing/portal pages; structured markdown link listing by section.
- Suite: 1047-1074 passed.

## 2026-02-24 - macOS Integration + Plugin Docs + Session Fixes

- **macOS app bundle**: `~/Applications/AskyDaemon.app` with `Info.plist`, shell launcher sourcing `~/.zshrc`; Spotlight integration; version-gated rebuild.
- **Plugin runtime bootstrap**: Process-level singleton; config-copy for `plugins.toml`; default built-in plugins enabled.
- **Session bug fix**: Numeric session ID lookup no longer matches partial names; `/session clear` with two-step confirmation.
- **XMPP fixes**: Help command routing bypass for interface planner; audio transcription reply as generator (immediate transcription + deferred model answer).
- **Menubar UX**: Singleton guard with file lock; state-aware action labels; icon preference to mono; crash fix for missing icon; removed credential editor (CLI-only via `--edit-daemon`).
- **Documentation**: Comprehensive `daemon/AGENTS.md`; plugin user docs; ARCHITECTURE.md corrections.
- Suite: 787-834 passed.

## 2026-02-23 - XMPP Daemon + Voice + Groups + Security

- **XMPP daemon mode**: Foreground XMPP runtime; per-JID serialized workers; command presets; hybrid routing with interface planner; remote safety policy.
- **Voice transcription**: Async MLX-Whisper pipeline; transcript persistence with session-scoped IDs; confirmation UX; auto-yes without interface model.
- **Image transcription**: Base64 multimodal requests; model-level `image_support`; session-scoped media pointers (`#iN`, `#itN`, `#aN`, `#atN`).
- **Group sessions**: Room binding via trusted invites; session switching; session-scoped TOML config overrides (last-write-wins); inline TOML and URL-TOML apply.
- **Query alias parity**: XMPP queries now have CLI-equivalent recursive slash expansion.
- **Cross-platform daemon**: `--edit-daemon` interactive editor; macOS menubar runtime with `rumps`; startup-at-login (LaunchAgent/systemd/Startup-folder).
- **slixmpp compatibility**: Runtime API detection (`process` vs `asyncio loop`); connect-call compatibility; OOB XML-direct parsing; bare JID allowlist matching; threadsafe outbound send.
- **Security fixes (P1 review)**: ReDoS bounded regex; path traversal guard; download deadline tracking; scoped transcript confirmations; atomic session lock files; thread-safe embedding init; concurrent SQLite guard; session name uniqueness index; background thread exception logging. (15 high-severity fixes, 13 regression tests)
- **Canonical section refs**: Alias collapsing; safety thresholds; corpus reference parsing (`corpus://cache/<id>#section=<section-id>`).
- Suite: 667-774 passed.

## 2026-02-22 - API Migration + Research Pipeline + Observability

- **Full API orchestration**: `AskyClient.run_turn()` as stable programmatic entrypoint; context/session/preload/model/persist flow; `ContextOverflowError` replaces interactive recovery.
- **Session-owned research**: Persisted research mode/source-mode/corpus-paths per session; `-r` promotes existing sessions; follow-up turns reuse stored profile.
- **Seed URL preload**: Standard-mode pre-model content delivery with budget cap (80% context); per-URL delivery status labels; `seed_url_direct_answer_ready` tool gating.
- **Double-verbose (`-vv`)**: Full main-model I/O live streaming; transport metadata panels; preload provenance trace; tool schema/guideline tables.
- **Smart `-r` flag**: Unified research flag with corpus pointer resolution; deprecated `-lc`.
- **Session idle timeout**: Configurable inactivity prompt (Continue/New Session/One-off); `last_used_at` tracking.
- **On-demand summarization**: Replaces truncation in smart compaction; DB-persisted summaries prevent re-summarization.
- **HTML archive improvements**: External CSS/JS assets; JSON-based sidebar index; smart grouping with longest common prefix; copy-to-clipboard icons; version-aware asset management.
- **Configurable prompts**: User-overridable research guidance and tool prompt text via config.
- Suite: 562-606 passed.

## 2026-02-17 to 2026-02-21 - Memory + Lean Mode + Banner Fixes

- **User memory system**: `save_memory` LLM tool with cosine dedup (>=0.90); per-turn recall injected into system prompt; session-scoped by default with global triggers ("remember globally:"); auto-extraction via `--elephant-mode`; CLI management (`--list-memories`, `--delete-memory`, `--clear-memories`).
- **Lean mode enhancements**: Disables all tools; suppresses system prompt updates, banners, HTML reports; bypasses summarization and background extraction.
- **Banner fixes**: Separated main/summarizer token tracking; fixed shallow copy mutation; fixed frozen summarization tokens via final `update_banner` before `stop_live()`.
- Suite: ~540-560 passed.

## 2026-02-14 - Tool Management + System Prompt + Evidence Extraction

- **Tool management**: `--list-tools`; `--tool-off all`; shell autocompletion for tool names; per-tool `system_prompt_guideline` metadata; runtime tool exclusion.
- **System prompt override**: `--system-prompt` / `-sp` flag and API `system_prompt_override`.
- **Session research cleanup**: `--clean-session-research` for surgical research-only wipe.
- **Evidence extraction**: Post-retrieval LLM fact extraction step; per-stage tool exposure (acquisition vs retrieval); `corpus_preloaded` dynamic registry filtering.
- **Query expansion**: YAKE deterministic + optional LLM-assisted decomposition; multi-query shortlist scoring.
- Suite: 471-478 passed.

## 2026-02-09 to 2026-02-13 - Local Corpus + Guardrails + Eval Harness

- **Local corpus ingestion**: `-lc` / `--local-corpus` flag; `local_document_roots` guardrails; root-relative path resolution; model-visible path redaction; built-in local source adapter (text/PDF/EPUB via PyMuPDF).
- **Local filesystem guardrails**: Generic URL tools reject `local://`, `file://`, and path-like targets.
- **Research eval harness**: Dataset/matrix YAML/TOML schema; `prepare`/`run`/`report` commands; per-run DB/Chroma isolation; `contains`/`regex` assertions; timing instrumentation; role-based token usage; tool-call breakdown; live progress output.
- **Maintainability refactors (Phase 1-5)**: Shared `url_utils.py` and `lazy_imports.py`; extracted `shortlist_flow.py`, `tool_registry_factory.py`, `shortlist_types/collect/score.py`, `vector_store_common/chunk_link_ops/finding_ops.py`.
- Suite: 402-471 passed.

## 2026-02-08 - Foundation

- **Codebase documentation**: Package-level `AGENTS.md` files; slimmed `ARCHITECTURE.md`; maintainability report.
- **CLI & UX**: `argcomplete` shell completion; word-based selector tokens; `-sfm` message-to-session; `--reply` quick continue; live banner progress; verbose trace tables.
- **Performance**: Lazy imports; startup short-circuiting; background cleanup; `test_startup_performance.py` guardrails.
- **Research & retrieval**: Unified URL retrieval in `retrieval.py`; hierarchical summarization; shared shortlist pipeline; seed-link expansion; cache-first embeddings with fallback model.
- **Reliability**: Graceful max-turns exit; XML tool call parsing; non-streaming LLM requests; summarization latency reduction (bounded map + single reduce).
- Suite: ~402 passed.
