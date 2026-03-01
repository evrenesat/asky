# DEVLOG

For full detailed entries, see [DEVLOG_ARCHIVE.md](DEVLOG_ARCHIVE.md).

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
