# DEVLOG

For full detailed entries, see [DEVLOG_ARCHIVE.md](DEVLOG_ARCHIVE.md).

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
