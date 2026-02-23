# DEVLOG

## 2026-02-23 - Critical Hardware/Storage Bug Fixes (C-01, C-02)

Fixed two P0 bugs related to fragile string slicing with case-insensitive triggers and incorrect boolean type checking for persisted session settings.

- **Changed**:
  - `src/asky/api/client.py`:
    - Refactored `run_turn` to use a robust, Unicode-safe original prefix mapping for memory trigger removal (`REMEMBER GLOBALLY:`, etc.). This handles cases where casefolding/lowercasing changes string character length (e.g. 'ẞ' -> 'ss').
    - Hardened `research_mode` resolution to use explicit identity checks (`is True or is False`) instead of `isinstance(..., bool)`. This ensures that integer values (0/1) retrieved from SQLite (which are sometimes un-cast in raw fields) do not cause silent fallbacks to default config settings when they should have enabled research mode.
  - `src/asky/cli/chat.py`, `src/asky/api/preload.py`, `src/asky/cli/local_ingestion_flow.py`:
    - Updated `isinstance(..., bool)` checks to identity checks (`is True or is False`) for consistency and robustness against un-cast integer values from storage.
- **Why**:
  - `isinstance(value, bool)` returns `False` for `0` and `1`, which are the common representations of booleans in SQLite. This caused persisted session research mode to be ignored if the value wasn't explicitly cast to `bool` at exactly the right layer.
  - Case-insensitive string slicing using `len(trigger)` is fragile when combined with `lower()` if the character length changes, leading to corrupted query text or failed prefix removal.
- **Validation**:
  - Created `tests/test_api_client_bugs.py` with targeted regression tests for:
    - Case-insensitive trigger removal.
    - Unicode-safe trigger removal (verified with 'ẞ').
    - Boolean resolution robustness for session research mode.
    - Invalid type fallback behavior.
  - Full suite: `uv run pytest` -> `715 passed`.

## 2026-02-23 - XMPP Group Sessions + Session-Scoped TOML Overrides

Implemented persistent group-chat session support in daemon mode, including trusted-invite room binding, session switching commands, and session-scoped TOML config overrides with last-write-wins semantics.

- **Changed**:
  - `src/asky/storage/interface.py`, `src/asky/storage/sqlite.py`, `src/asky/storage/__init__.py`:
    - Added persistent daemon tables/APIs:
      - `room_session_bindings` (room bare JID -> active session),
      - `session_override_files` (session-scoped override snapshots keyed by filename).
    - Added repository methods for binding lookup/upsert and override file save/list/get/copy.
  - `src/asky/daemon/session_profile_manager.py` (new):
    - Added daemon profile manager for:
      - direct and room session resolution,
      - room binding create/switch flows,
      - `/session` command backing behaviors (`new`, `child`, switch),
      - override-file validation/sanitization for `general.toml` + `user.toml`,
      - effective runtime profile assembly (default model, summarization model, prompt map).
    - Enforced supported-key filtering:
      - `general.default_model`, `general.summarization_model` (must reference existing model aliases),
      - `[user_prompts]` string entries.
    - Unsupported keys are ignored with warning surface; unsupported filenames are rejected.
  - `src/asky/daemon/transcript_manager.py`:
    - Delegated session lifecycle responsibilities to `SessionProfileManager`.
    - Added room binding helper methods used by router/service.
  - `src/asky/daemon/command_executor.py`:
    - Added daemon session control command surface:
      - `/session`, `/session new`, `/session child`, `/session <id|name>`.
    - Added inline TOML and URL-TOML apply paths for current conversation session.
    - Added conversation-scoped runtime profile usage for:
      - default model selection,
      - summarization model override (context-managed),
      - prompt alias expansion/listing.
  - `src/asky/cli/utils.py`:
    - Added optional `prompt_map` argument to `load_custom_prompts(...)` and `expand_query_text(...)` for session-scoped prompt expansion without global mutation.
  - `src/asky/daemon/xmpp_client.py`:
    - Added groupchat payload metadata extraction:
      - `room_jid`, `sender_nick`, `sender_jid`,
      - room invite extraction from MUC user extension,
      - all OOB URLs collection.
    - Added room join helper (`join_room`) and group-send helper (`send_group_message`).
    - Added optional session-start callback hook.
  - `src/asky/daemon/router.py`:
    - Added `groupchat` handling path:
      - messages are processed only for bound rooms,
      - trusted invite bind helper (`handle_room_invite`),
      - room-aware query/command routing and transcript confirmation keys.
    - Added TOML URL apply routing and inline TOML apply handling.
  - `src/asky/daemon/service.py`:
    - Switched daemon serialization from strict per-sender JID to per-conversation key (room for groupchat).
    - Added trusted invite auto-join flow and startup auto-rejoin for persisted bound rooms.
    - Added room-aware reply targeting (`chat` vs `groupchat`) and TOML URL ingestion pass before normal text routing.
  - Tests:
    - Added `tests/test_xmpp_group_sessions.py`.
    - Updated:
      - `tests/test_storage.py`,
      - `tests/test_xmpp_commands.py`,
      - `tests/test_xmpp_router.py`,
      - `tests/test_xmpp_client.py`,
      - `tests/test_xmpp_daemon.py`.
  - Docs:
    - Updated `ARCHITECTURE.md` daemon flow and component map for group sessions + session overrides.
    - Updated `src/asky/storage/AGENTS.md` and `tests/AGENTS.md`.
- **Why**:
  - Enable permanent per-group behavior and runtime-simple configuration changes via uploaded TOML while keeping scope constrained and avoiding broad runtime-global config refactors.
  - Keep configuration ownership on sessions so groups can switch sessions and child sessions can inherit overrides.
- **Validation**:
  - Targeted:
    - `uv run pytest tests/test_storage.py tests/test_file_prompts.py tests/test_xmpp_commands.py tests/test_xmpp_router.py tests/test_xmpp_client.py tests/test_xmpp_daemon.py tests/test_xmpp_group_sessions.py` -> passed.
  - Full suite:
    - `uv run pytest` -> `711 passed`.

## 2026-02-23 - XMPP Query Alias Expansion Parity with CLI

Added CLI-equivalent query alias/slash expansion to daemon query execution so XMPP queries now process user prompts recursively before model execution.

- **Changed**:
  - `src/asky/daemon/command_executor.py`:
    - Added shared query-preparation path used by both:
      - direct XMPP query ingress (`execute_query_text`),
      - command-mode query execution (`_execute_asky_tokens`).
    - Query prep now:
      - loads custom prompt files when query contains `/`,
      - recursively expands slash aliases via `expand_query_text(...)` (including `/cp`),
      - applies CLI-equivalent unresolved slash behavior:
        - `/` -> list all configured prompts,
        - unknown `/prefix` -> filtered prompt list output.
    - `transcript use <id>` inherits the same behavior through `execute_query_text`.
  - `tests/test_xmpp_commands.py`:
    - Added coverage for:
      - recursive alias expansion before `AskyClient.run_turn()`,
      - slash-only prompt listing short-circuit (no model call),
      - unknown slash-prefix filtered prompt listing short-circuit (no model call),
      - shared command-path query preparation,
      - transcript-use query preparation inheritance.
  - `ARCHITECTURE.md`:
    - Updated XMPP daemon flow notes to document shared CLI-equivalent slash expansion behavior and ingress scope.
  - `tests/AGENTS.md`:
    - Updated `test_xmpp_commands.py` coverage description to include XMPP query alias/slash expansion behavior.
- **Why**:
  - XMPP queries previously bypassed prompt alias expansion that CLI queries already applied recursively, causing inconsistent behavior across interfaces.
- **Validation**:
  - `uv run pytest tests/test_xmpp_commands.py` -> passed.
  - `uv run pytest tests/test_xmpp_router.py` -> passed.
  - `uv run pytest` -> passed.

## 2026-02-23 - README Clarity for XMPP Daemon + Voice

Clarified the top-level README so new users immediately understand what XMPP daemon mode is and why it matters.

- **Changed**:
  - `README.md`:
    - Updated project summary line to mention optional XMPP remote-chat mode.
    - Added XMPP daemon and voice transcription/voice command bullets to **Key Features**.
    - Added new section: **What XMPP Daemon Mode Means** with concrete behavior:
      - foreground XMPP client daemon (not an XMPP server),
      - allowlist-only direct-message handling,
      - command/query + preset usage over chat,
      - optional voice transcription flow.
- **Why**:
  - Prior wording was too vague for first-time readers and did not surface one of the strongest practical features.
- **Validation**:
  - `uv run pytest` -> passed.

## 2026-02-23 - Model Editor Action for Interface Role

Added interface-model role assignment to interactive model management.

- **Changed**:
  - `src/asky/cli/models.py`:
    - Added new edit action:
      - `i` -> set selected model as `general.interface_model`.
    - Updated model-role display to include interface role in:
      - existing model overview header,
      - selected model current-role tags.
    - Added optional prompt in add-model flow:
      - "Set as interface model?" after save.
  - `tests/test_models_cli.py`:
    - Added coverage for `i` action to ensure it updates `interface_model`.
  - `src/asky/cli/AGENTS.md`, `tests/AGENTS.md`:
    - Updated CLI/tests package docs to mention interface-role action coverage.
- **Why**:
  - `asky -me` should support setting all model roles from the same menu, including the interface planner model.
- **Validation**:
  - `uv run pytest tests/test_models_cli.py` -> passed.
  - `uv run pytest` -> passed.

## 2026-02-23 - XMPP Runtime Compatibility Fix (`process` vs asyncio loop)

Fixed daemon startup failure on environments where `slixmpp.ClientXMPP` no longer exposes `.process(...)`.

- **Changed**:
  - `src/asky/daemon/xmpp_client.py`:
    - Added runtime compatibility path:
      - prefer `client.process(forever=True)` when available
      - fallback to `client.loop.run_forever()` when `process` is missing
      - fallback to `client.disconnected.wait()` when loop runner is unavailable
    - Added connect-call compatibility for host overrides across slixmpp variants:
      - uses `connect(host=..., port=...)` when supported
      - falls back to legacy address-style connect otherwise
    - Updated connection outcome handling:
      - daemon now treats only explicit `False` as immediate connection failure
      - async `connect()` coroutines are scheduled on the slixmpp loop before foreground processing
      - task/future-like awaitables returned by `connect()` are now treated as already scheduled and are not re-wrapped with `create_task()`
    - Added awaitable connect-result normalization for async connect variants.
    - Reworked OOB URL parsing to inspect message XML directly (no stanza-interface lookup), avoiding noisy `Unknown stanza interface: oob` warnings while preserving audio attachment URL extraction.
    - Relaxed allowlist matching:
      - bare JID entries (`user@domain`) now authorize any resource
      - full JID entries (`user@domain/resource`) remain exact-match
    - Fixed outbound send dispatch from daemon worker threads:
      - responses are now posted onto the slixmpp loop via `call_soon_threadsafe(...)`
      - prevents delayed delivery where replies appeared only after subsequent inbound activity woke the loop
    - Improved voice MIME validation for attachment downloads:
      - `application/octet-stream` now falls back to extension-based MIME inference (`.m4a`, `.mp4`, `.webm`, `.flac`, etc.)
      - common platform MIME aliases (`audio/mp4a-latm`, `video/mp4`, `video/webm`, `audio/x-flac`, etc.) are normalized to allowed audio MIME values
    - Prevented accidental model calls for audio-share URLs:
      - when a message includes an audio OOB URL, URL-only text bodies are ignored in daemon routing
      - keeps the flow in transcript-only mode until explicit confirmation/command
    - Clarified transcript confirmation UX:
      - ready notification now explicitly states `yes` runs transcript as query, `no` keeps it for later
    - Added Hugging Face token configuration for voice models:
      - new `xmpp.toml` keys: `voice_hf_token_env`, `voice_hf_token`
      - daemon now exports token to `HF_TOKEN` and `HUGGING_FACE_HUB_TOKEN` before `mlx-whisper` transcription calls
    - Added `voice_auto_yes_without_interface_model` (default `true`):
      - when interface model is not configured, completed voice transcripts are auto-run as queries without waiting for manual `yes`
      - when interface model is configured, confirmation flow remains manual (`yes`/`no` or `transcript use <id>`)
- **Why**:
  - Real run failed with:
    - `AttributeError: 'ClientXMPP' object has no attribute 'process'`
  - Daemon must support both classic and asyncio-driven slixmpp runtime APIs.
- **Tests Added**:
  - `tests/test_xmpp_client.py`:
    - `process` path coverage
    - loop fallback coverage
    - connect failure error path
- **Validation**:
  - `uv run pytest tests/test_xmpp_client.py tests/test_xmpp_daemon.py tests/test_xmpp_router.py tests/test_xmpp_commands.py` -> passed.

## 2026-02-23 - Research Docs Clarification Pass (Section Contracts)

Clarified research documentation to match finalized local-corpus section behavior.

- **Changed**:
  - `docs/research_mode.md`:
    - Added explicit notes for canonical alias auto-promotion and tiny-section refusal.
    - Added recommended model tool-call sequence for section workflows.
    - Added section-scoped retrieval examples for preferred `section_ref` and legacy compatibility form.
  - `docs/library_usage.md`:
    - Added API contract notes for resolved section metadata (`requested_section_id`, `resolved_section_id`, `auto_promoted`).
    - Added tiny-section structured-error behavior notes for `summarize_section`.
- **Why**:
  - Ensure users can reliably reason about section references and retrieval behavior.
  - Reduce ambiguity between preferred section references and compatibility parsing.

## 2026-02-23 - XMPP Daemon Mode + Voice Transcription + Interface Planner + Command Presets

Implemented the final daemon feature set: optional XMPP foreground runtime, command presets, background voice transcription, interface-model routing, and transcript persistence/commands.

- **Changed**:
  - `pyproject.toml`:
    - Added optional dependency extras:
      - `xmpp` (`slixmpp`)
      - `voice` (`mlx-whisper`)
      - `daemon` (combined)
  - `src/asky/config/loader.py`, `src/asky/config/__init__.py`, `src/asky/data/config/general.toml`, `src/asky/data/config/xmpp.toml`, `src/asky/data/config/user.toml`:
    - Added `xmpp.toml` loading and exported daemon/voice constants (`XMPP_*`, `XMPP_VOICE_*`).
    - Added `general.interface_model`.
    - Added `[command_presets]` config section support.
  - `src/asky/cli/presets.py`, `src/asky/cli/__init__.py`, `src/asky/cli/main.py`:
    - Added first-token backslash preset expansion/listing (`\\name`, `\\presets`) for local CLI.
    - Added `--xmpp-daemon` flag and foreground service bootstrap path.
  - `src/asky/storage/interface.py`, `src/asky/storage/sqlite.py`, `src/asky/storage/__init__.py`:
    - Added transcript persistence model and repository methods:
      - `create_transcript`, `update_transcript`, `list_transcripts`, `get_transcript`, `prune_transcripts`.
    - Added `transcripts` SQLite table with session-scoped numeric transcript IDs.
  - `src/asky/daemon/*` (new package):
    - `service.py`: daemon lifecycle, per-JID serialized workers, chunked outbound responses.
    - `xmpp_client.py`: slixmpp transport wrapper and OOB URL extraction.
    - `router.py`: allowlist/direct-chat gate, hybrid routing, preset handling, confirmation shortcuts.
    - `command_executor.py`: command/query execution bridge plus remote policy enforcement.
    - `interface_planner.py`: strict JSON action planning using configured interface model.
    - `voice_transcriber.py`: async transcription queue, streamed downloads, macOS gate.
    - `transcript_manager.py`: transcript lifecycle, retention pruning, artifact cleanup.
    - `chunking.py`: deterministic message chunking.
- **Behavior**:
  - Unauthorized senders and non-chat stanza types are ignored silently.
  - Per-JID message processing is serialized.
  - Hybrid routing supports interface-model and non-interface-model modes.
  - Voice transcription is async and does not block text handling.
  - Transcript workflow supports list/show/use/clear and yes/no shortcuts.
  - Remote safety policy blocks unsafe flags even after preset/planner expansion.
- **Tests Added/Updated**:
  - Added:
    - `tests/test_presets.py`
    - `tests/test_xmpp_daemon.py`
    - `tests/test_xmpp_router.py`
    - `tests/test_xmpp_commands.py`
    - `tests/test_voice_transcription.py`
  - Updated:
    - `tests/test_cli.py`
    - `tests/test_config.py`
    - `tests/test_storage.py`
- **Validation**:
  - Full suite:
    - `uv run pytest` -> `667 passed in 7.04s`

## 2026-02-23 - Canonical Section Refs + Section-Scoped Retrieval Compatibility

Hardened local-corpus section workflows after observed failures where models selected tiny TOC aliases and malformed section-scoped corpus URLs.

- **Changed**:
  - `src/asky/research/sections.py`:
    - Added canonical section model with alias collapsing:
      - canonical body sections (`canonical_sections`) and alias map (`alias_map`)
      - section metadata (`is_toc`, `is_body`, `canonical_id`)
      - helper APIs: `get_listable_sections(...)`, `resolve_section_alias(...)`, `get_section_by_id(...)`
    - Added safety thresholds:
      - `MIN_CANONICAL_BODY_CHARS`
      - `MIN_SUMMARIZE_SECTION_CHARS`
    - `slice_section_content(...)` now resolves aliases to canonical IDs by default and reports
      `requested_section_id`, `resolved_section_id`, `auto_promoted`.
  - `src/asky/research/tools.py`:
    - Added canonical corpus reference parsing for:
      - `corpus://cache/<id>`
      - `corpus://cache/<id>#section=<section-id>`
      - compatibility legacy `corpus://cache/<id>/<section-id>`
    - `list_sections` now:
      - defaults to canonical body-only rows,
      - supports `include_toc`,
      - returns `section_ref` per row,
      - returns both `section_count` and `all_section_count`.
    - `summarize_section` now:
      - resolves section scope in order `section_ref` -> `section_id` -> strict `section_query`,
      - accepts compatibility legacy source suffixes,
      - promotes aliases to canonical sections,
      - refuses tiny sections with actionable structured errors.
    - `get_relevant_content` / `get_full_content` now:
      - accept optional `section_id` / `section_ref`,
      - accept legacy section-suffixed corpus sources,
      - apply section-bounded slicing before retrieval/full return.
  - `src/asky/cli/main.py`, `src/asky/cli/section_commands.py`:
    - Added CLI flags:
      - `--section-id`
      - `--section-include-toc`
    - Manual section listing now defaults to canonical body sections and prints `section_ref`.
    - Manual section summary path now supports deterministic `--section-id` and tiny-section refusal.
  - `src/asky/core/prompts.py`:
    - Updated guidance to prefer `section_ref` / `section_id` and avoid section path suffix hacks.
- **Why**:
  - Real runs showed models choosing duplicate tiny TOC headings and generating low-quality summaries.
  - Model attempts to call retrieval with `corpus://cache/<id>/<section-id>` failed previously.
  - The new contract keeps section references explicit and compatible while preserving existing flows.
- **Tests Added/Updated**:
  - `tests/test_research_sections.py`
  - `tests/test_section_commands.py`
  - `tests/test_research_tools.py`
  - `tests/test_cli.py`
- **Validation**:
  - Targeted:
    - `uv run pytest tests/test_research_sections.py tests/test_section_commands.py tests/test_research_tools.py tests/test_cli.py tests/test_tools.py tests/test_api_library.py tests/test_llm.py` -> passed.
  - Full:
    - `uv run pytest` -> passed.

## 2026-02-22 - Local-Only Section Summarization + Research Tool Gating

Added deterministic local-corpus section workflows for both CLI and research tool execution, aimed at reliable deep section summaries without relying on model guesswork.

- **Changed**:
  - `src/asky/research/sections.py` (new):
    - Added deterministic section primitives:
      - `build_section_index(...)` (TOC-aware + heading-aware parsing with stable IDs)
      - `match_section_strict(...)` (strict confidence + suggestion candidates)
      - `slice_section_content(...)` (section-bounded extraction + optional chunk-limit slicing)
  - `src/asky/cli/section_commands.py` (new):
    - Added no-main-model section command flow:
      - `--summarize-section` with no value lists sections.
      - `--summarize-section "<query>"` runs strict section match + deep summary.
      - Added source disambiguation and actionable errors for ambiguous sources/sections.
    - Uses existing hierarchical summarizer (`_summarize_content`) with detail profiles:
      `compact|balanced|max` (default `balanced`).
  - `src/asky/cli/main.py`:
    - Added CLI flags:
      - `--summarize-section [SECTION_QUERY]`
      - `--section-source SOURCE`
      - `--section-detail balanced|max|compact`
      - `--section-max-chunks N`
    - Added command routing to `section_commands.run_summarize_section_command(...)`.
  - `src/asky/research/tools.py`:
    - Added research tools:
      - `list_sections`
      - `summarize_section`
    - Enforced local-only behavior:
      - Web URL inputs rejected explicitly.
      - Mixed-mode enforcement for handle-only local inputs.
  - `src/asky/core/tool_registry_factory.py`, `src/asky/api/client.py`, `src/asky/core/prompts.py`, `src/asky/core/engine.py`:
    - Added `research_source_mode` propagation to research registry creation.
    - Registry now hides section tools in `web_only` mode.
    - Registry injects source-mode context into section tool executors.
    - Prompt guidance now includes a local section flow (`list_sections` -> `summarize_section`) when local-capable modes are active.
- **Why**:
  - Retrieval-only prompting often produced shallow section answers or dead-ended when section titles were not matched exactly.
  - Users needed deterministic introspection and section-level control to validate retrieval behavior and force comprehensive section summaries.
- **Tests Added/Updated**:
  - Added:
    - `tests/test_research_sections.py`
    - `tests/test_section_commands.py`
  - Updated:
    - `tests/test_research_tools.py`
    - `tests/test_tools.py`
    - `tests/test_cli.py`
    - `tests/test_api_library.py`
- **Validation**:
  - Targeted:
    - `uv run pytest tests/test_research_sections.py tests/test_section_commands.py tests/test_research_tools.py tests/test_tools.py tests/test_cli.py tests/test_api_library.py`
  - Full suite:
    - `uv run pytest` (passed after this change set).

## 2026-02-22 - Local Corpus Retrieval Bootstrap + Manual `--query-corpus`

Improved local-corpus research reliability when memory is empty and added a no-LLM corpus query command for debugging retrieval quality.

- **Changed**:
  - `src/asky/research/tools.py`, `src/asky/research/cache.py`:
    - Added support for safe corpus handles (`corpus://cache/<id>`) in `get_relevant_content` and `get_full_content`.
    - Retrieval tools now accept internal `corpus_urls` fallback input in addition to `urls`.
    - Added cache helpers:
      - `get_cached_by_id(cache_id)`
      - `list_cached_sources(limit)`
    - Local filesystem URL guardrails remain in place for raw local targets.
  - `src/asky/api/preload.py`, `src/asky/api/client.py`, `src/asky/core/tool_registry_factory.py`:
    - Preload now tracks safe source identifiers and handle mappings for local corpus documents.
    - Research registry now injects preloaded corpus identifiers when retrieval tools are called without `urls`.
    - Added deterministic pre-model retrieval bootstrap in research mode:
      retrieved evidence snippets are appended to preloaded context before first model call.
  - `src/asky/core/prompts.py`:
    - Local-KB guidance now instructs model to call `get_relevant_content` immediately when `query_research_memory` is empty.
  - `src/asky/cli/main.py`, `src/asky/cli/research_commands.py`:
    - Added manual corpus query interface:
      - `--query-corpus "..."` (no model call)
      - `--query-corpus-max-sources`
      - `--query-corpus-max-chunks`
    - Command can ingest explicit `-r` corpus targets first, then run deterministic retrieval over cached corpus handles.
- **Why**:
  - Ingested local corpus could still fail to answer if model stopped after empty `query_research_memory` and never called retrieval tools.
  - Users needed a direct way to test retrieval query quality without LLM/tool-loop behavior.
- **Tests Added/Updated**:
  - `tests/test_api_library.py`: bootstrap retrieval context included in first user message; updated registry call expectations.
  - `tests/test_api_preload.py`: handle-based preloaded source URL/handle mapping coverage.
  - `tests/test_research_tools.py`: corpus-handle retrieval/full-content support + malformed-handle behavior.
  - `tests/test_tools.py`: research registry corpus URL fallback injection coverage.
  - `tests/test_cli.py`: parser coverage for `--query-corpus*` and main-command dispatch.
  - `tests/test_research_commands.py`: no-LLM manual corpus query command coverage.

## 2026-02-22 - Session-Owned Research Mode + Local Corpus Reliability

Implemented session-owned research behavior so resumed sessions carry research mode and corpus profile without repeating `-r`.

- **Changed**:
  - `src/asky/storage/interface.py`, `src/asky/storage/sqlite.py`, `src/asky/storage/__init__.py`, `src/asky/core/session_manager.py`:
    - Added persisted session research profile fields:
      - `research_mode`
      - `research_source_mode` (`web_only|local_only|mixed`)
      - `research_local_corpus_paths` (JSON list)
    - Added backward-compatible SQLite migrations and read/write helpers (`update_session_research_profile`).
  - `src/asky/api/session.py`, `src/asky/api/types.py`, `src/asky/api/client.py`:
    - `resolve_session_for_turn()` now returns effective session-owned research profile.
    - `-r` semantics now promote existing non-research sessions and persist profile.
    - Stored corpus settings are reused on follow-up turns; explicit `-r` corpus pointers replace stored pointers.
    - Turn execution now uses effective research mode/profile (prompt/tool/preload routing no longer keys only off config flag).
    - Added local-corpus fail-fast for `local_only`/`mixed` profiles when zero local docs ingest.
  - `src/asky/api/preload.py`, `src/asky/cli/main.py`, `src/asky/cli/chat.py`:
    - Added `--shortlist auto|on|off` CLI override with precedence:
      `lean > request override > model override > global`.
    - `-r` corpus parsing now returns source-mode intent and replacement semantics.
    - Added explicit `web` token support in pointer lists for mixed/web-only profile requests.
  - `src/asky/research/adapters.py`, `src/asky/research/tools.py`, `src/asky/config/__init__.py`, `src/asky/data/config/research.toml`:
    - Removed custom source-adapter routing capability.
    - Kept built-in local loader only (local/file targets).
    - URL-oriented research tools remain guarded against local filesystem targets.
    - Fixed absolute-path ingestion by correctly handling absolute paths inside configured roots.
- **Why**:
  - Follow-up turns on resumed research sessions were dropping research/corpus context unless users repeated flags.
  - Local corpus absolute paths resolved by CLI could fail during ingestion due path-normalization mismatch.
  - Dormant custom adapter capability added complexity without active use.
- **Tests Added/Updated**:
  - `tests/test_sessions.py`: session-owned research profile reuse, promotion, replacement semantics.
  - `tests/test_storage.py`: research profile round-trip persistence.
  - `tests/test_research_corpus_resolution.py`: new corpus/source-mode parsing behavior (`web` token, replace semantics, absolute-root enforcement).
  - `tests/test_local_ingestion_flow.py`: absolute-path ingestion success under configured roots.
  - `tests/test_research_adapters.py`: replaced adapter-routing coverage with built-in local-loader coverage.
  - `tests/test_api_library.py`: effective research-mode expectations + local-only fail-fast.
  - `tests/test_api_preload.py`, `tests/test_cli.py`: shortlist request override coverage.
- **Validation**:
  - Targeted: `uv run pytest tests/test_storage.py tests/test_sessions.py tests/test_research_corpus_resolution.py tests/test_local_ingestion_flow.py tests/test_research_adapters.py tests/test_api_preload.py tests/test_api_library.py tests/test_cli.py` -> passed.
  - Full suite: `uv run pytest` -> `606 passed in 6.00s`.

## 2026-02-22 - Fix: Session Idle Timeout UI Conflict

Fixed a UI conflict where the session idle timeout prompt was hidden by the live banner and caused display corruption.

- **Changed**:
  - `src/asky/cli/chat.py`:
    - Moved session resolution (`sticky_session_name`, `resume_session_term`, `shell_session_id`) and `_check_idle_session_timeout()` call to before the `try` block that starts the live banner.
    - Moved `elephant_mode` session validation before the banner start to ensure warnings are visible.
- **Why**:
  - `renderer.start_live()` captures the console and hides standard `console.print()` output behind the banner. Moving the interactive check before the banner ensures the user can see and respond to the prompt correctly.
- **Validation**:
  - Verified that `tests/test_idle_timeout.py` and the full test suite pass.
  - Corrected the ordering so banner content accurately reflects the chosen session action.

## 2026-02-22 - `-vv` Follow-up: Preload/Shortlist Trace Coverage + Main-Model Panel Consolidation

Refined the prior `-vv` redesign to address trace usability issues surfaced in real CLI runs.

- **Changed**:
  - `src/asky/core/engine.py`:
    - `llm_request_messages` now includes structured `tool_schemas` and `tool_guidelines` metadata for the exact main-model call.
  - `src/asky/api/preload.py` and `src/asky/api/client.py`:
    - Added optional preload-stage trace propagation into shortlist execution.
    - Added structured `preload_provenance` verbose event emitted before main-model execution.
  - `src/asky/research/source_shortlist.py` and `src/asky/research/shortlist_types.py`:
    - Added optional `trace_callback` support for shortlist search/fetch/seed-link stages.
    - Default shortlist fetch now forwards retrieval transport metadata with `source=shortlist`.
    - Seed-link extractor now emits transport request/response/error metadata.
    - Trace callback forwarding now supports both explicit `trace_callback` signatures and `**kwargs` executors.
  - `src/asky/cli/chat.py`:
    - Added `Preloaded Context Sent To Main Model` panel (seed-doc statuses, selected shortlist URLs, warnings, context sizes).
    - Consolidated main-model transport metadata into main outbound/inbound panels.
    - Suppressed standalone transport panels for `source=main_model` to reduce duplication.
    - Added structured enabled-tool schema table and tool-guideline panel to outbound main-model traces.
- **Tests**:
  - `tests/test_cli.py`: added coverage for merged main-model transport rendering and preload provenance panel.
  - `tests/test_llm.py`: added coverage for tool schema/guideline fields in request trace payload.
  - `tests/test_source_shortlist.py`: added trace-callback propagation and shortlist fetch transport-error coverage.
  - `tests/test_api_preload.py`: added trace-callback forwarding coverage in preload pipeline.
  - `tests/test_api_library.py`: added preload provenance event emission coverage.
- **Validation**:
  - Targeted: `uv run pytest tests/test_cli.py tests/test_llm.py tests/test_source_shortlist.py tests/test_api_preload.py tests/test_api_library.py tests/test_tools.py tests/test_api_client_status.py` -> passed.

## 2026-02-22 - Smart Research Flag (`-r`) + Deprecated `-lc`

Refactored the research mode flag to be more intelligent and handle local corpus pointers directly, eliminating the need for the separate `-lc` flag and fixing broken in-query path referencing.

- **Changed**:
  - `src/asky/cli/main.py`:
    - Changed `-r`/`--research` to `nargs="?"` to accept an optional corpus pointer.
    - Removed `-lc`/`--local-corpus` flag entirely.
    - Implemented `_resolve_research_corpus()` to resolve pointers against `local_document_roots`.
    - Integrated resolution into `main()`, with fallback logic to treat non-pointer tokens as query starts.
  - `docs/research_mode.md`:
    - Removed all `-lc` references and syntax examples.
    - Removed in-query implicit path referencing documentation.
    - Added examples for the new `-r corpus_pointer query` syntax.
- **Tests**:
  - Added `tests/test_research_corpus_resolution.py` for comprehensive resolution logic verification.
  - Updated `tests/test_cli.py` for new flag parsing and mock namespace parity.
  - Full suite: `uv run pytest` -> passed.
- **Why**:
  - The `-lc` flag was redundant and its implementation was greedily consuming query tokens.
  - In-query path referencing (`/path`) was fragile and conflicted with shell aliases.
  - A unified `-r` flag with smart resolution provides a cleaner, more predictable UX.

## 2026-02-22 - `-vv` Redesign: Full Main-Model I/O + Live Streaming + Transport Metadata

Aligned double-verbose behavior with CLI expectations: show complete main-model communication live, and keep tool/summarizer internals metadata-only.

- **Changed**:
  - `src/asky/core/engine.py`:
    - Added inbound response payload emissions in double-verbose mode (`kind="llm_response_message"`).
    - Main-loop and graceful-exit LLM calls now forward trace callback context (`turn`, `phase`, `source`).
  - `src/asky/core/api_client.py`:
    - Added optional `trace_callback` + `trace_context` to `get_llm_msg()`.
    - Emits structured transport events for each request lifecycle:
      `transport_request`, `transport_response`, `transport_error`.
    - Transport response includes status, content-type, response bytes, elapsed time, and a logical response type (`text`/`tool_calls`/`structured`).
  - `src/asky/tools.py` and `src/asky/retrieval.py`:
    - Added optional trace callback plumbing for search and URL fetch calls.
    - Emits tool/retrieval transport metadata (endpoint, method, status, response type/size, elapsed ms, error details when present).
  - `src/asky/core/tool_registry_factory.py`:
    - Added optional `tool_trace_callback` propagation into default and research registries.
    - `get_url_content` summarization path now forwards trace metadata through `get_llm_msg(trace_callback=...)` with summarization context.
  - `src/asky/api/client.py`:
    - Passes verbose callback as `tool_trace_callback` for tool/summarization transport traces.
  - `src/asky/cli/chat.py`:
    - Removed deferred `-vv` queueing while Live is active.
    - Main-model traces now render immediately in Live console.
    - Added explicit request/response transport direction panels:
      - `Main Model Outbound Request`
      - `Main Model Inbound Response`
    - Replaced per-message hardcoded outbound labeling with role-origin metadata in request summaries.
    - Added transport metadata panel rendering for tool/summarizer/LLM transport events.
- **Tests**:
  - Updated `tests/test_cli.py` to validate live streaming via live console and new request/response panel titles.
  - Updated `tests/test_llm.py` to validate both request and response payload emissions, including graceful-exit response tracing.
  - Added transport trace callback coverage in `tests/test_api_client_status.py`.
  - Added tool transport metadata coverage in `tests/test_tools.py`.
  - Updated call-signature expectations in `tests/test_api_library.py` and `tests/test_lean_mode.py` for `tool_trace_callback`.
- **Docs**:
  - Updated `ARCHITECTURE.md`, `src/asky/cli/AGENTS.md`, `src/asky/core/AGENTS.md`, and `src/asky/api/AGENTS.md` to document live `-vv` streaming, full main-model I/O tracing, and metadata-only tool/summarizer internals.
- **Validation**:
  - Targeted: `uv run pytest tests/test_cli.py::test_run_chat_double_verbose_payload_streams_via_live_console tests/test_llm.py::test_conversation_engine_double_verbose_emits_main_model_messages tests/test_llm.py::test_conversation_engine_double_verbose_emits_graceful_exit_response tests/test_api_client_status.py tests/test_tools.py tests/test_api_library.py::test_asky_client_run_messages_uses_research_registry tests/test_lean_mode.py::TestLeanModeAPI::test_run_messages_propagates_lean_and_disabled_tools` -> passed.
  - Full suite: `uv run pytest` -> `581 passed in 6.27s`.

## 2026-02-22 - Fix: save_html_report() TypeError Regression

Fixed a regression where `save_html_report()` was missing `message_id` and `session_id` parameters, causing a crash during archive generation. This was a mismatch between `chat.py` call site and `rendering.py` signature.

## 2026-02-22 - Standard-Mode Seed URL Content Preload Before First Tool Call

Improved standard-mode URL summarization flow so URL content from the user prompt
is proactively delivered to the model before the first tool loop.

- **Changed**:
  - `src/asky/research/shortlist_types.py`: Extended `CandidateRecord` with
    fetch metadata fields (`requested_url`, `fetched_content`, `fetch_warning`,
    `fetch_error`, `final_url`) for deterministic seed-document output.
  - `src/asky/research/shortlist_collect.py`: Preserve `requested_url` on seed,
    seed-link, and search candidates.
  - `src/asky/research/source_shortlist.py`:
    - Added `seed_url_documents` payload output aligned to prompt seed URL order.
    - Ensured prompt seed URLs are fetched even when beyond the shortlist scoring
      cap (`max_fetch_urls`) so preload can include them.
    - Added bare-domain prompt URL extraction (e.g., `example.com/path`) so
      un-schemed URLs are treated as seed URLs and normalized to `https://...`.
    - Updated shortlist context formatting to always include explicitly mentioned
      prompt URLs even if they rank below the normal top-k context cutoff.
    - Added `fetched_count` to payload for preload-state checks.
  - `src/asky/api/preload.py`:
    - Added standard-mode seed URL context formatter.
    - Implemented combined budget cap at 80% of model context size
      (`context_size * 4 chars/token * 0.8`).
    - Added per-URL delivery status labels:
      `full_content`, `summarized_due_budget`,
      `summary_truncated_due_budget`, `fetch_error`.
    - Seed URL context is now inserted before shortlist context in
      `combined_context`.
    - Added `seed_url_direct_answer_ready` resolution to flag when preloaded
      seed content is complete enough to answer directly without refetch.
  - `src/asky/api/client.py`:
    - Message assembly now conditionally replaces the generic
      "verify with tools" suffix with strict direct-answer guidance when
      `seed_url_direct_answer_ready=True`, explicitly telling the model not to
      call `get_url_content`/`get_url_details` for the same seed URL unless
      freshness/completeness checks are needed.
    - Added centralized run-turn tool gating policy for maintainability:
      when `seed_url_direct_answer_ready=True` in standard mode, the turn
      auto-disables `web_search`, `get_url_content`, and `get_url_details` to
      deterministically avoid unnecessary retrieval tool loops.
  - `src/asky/api/types.py`: Added `seed_url_context` to `PreloadResolution`.
  - `src/asky/api/types.py`: Added `seed_url_direct_answer_ready` to
    `PreloadResolution`.
  - Tests:
    - `tests/test_source_shortlist.py`: added seed-document capture/failure and
      seed-fetch-beyond-cap coverage, plus bare-domain extraction and explicit
      URL inclusion-beyond-top-k coverage.
    - `tests/test_api_preload.py`: added coverage for budget behavior,
      summarization/truncation labeling, fetch-error labeling, and standard-mode
      ordering in combined preload context.
    - `tests/test_api_library.py`: added seed URL context presence assertion in
      message construction, plus run-turn assertions for direct-answer tool
      disablement in standard mode and no-disable behavior in research mode.
  - Docs:
    - `src/asky/api/AGENTS.md`, `ARCHITECTURE.md` updated for new preload flow.

- **Why**:
  - Previous behavior fetched seed URLs during shortlist ranking but only passed
    shortlist snippets to the model, which often forced an extra tool call to
    refetch the same URL content.
  - Preloading seed URL content lowers redundant tool turns and gives the model
    immediate context for URL summarization requests.

- **Validation**:
  - `uv run pytest tests/test_source_shortlist.py tests/test_api_preload.py tests/test_api_library.py` -> passed.

## 2026-02-22 - Version 0.2.0: Copy Icons for Archive Sidebar

Bumped minor version to 0.2.0 and added copy-to-clipboard functionality to the HTML archive sidebar.

- **New Feature**:
  - Added copy icons next to messages and groups in the sidebar.
  - Clicking a message icon copies `asky --continue <id>`.
  - Clicking a session group icon copies `asky --resume-session <id>`.
  - Clicking a prefix group icon copies `asky --continue <id1>,<id2>,...`.
- **Changed**:
  - `src/asky/storage`: Added `reserve_interaction` to get IDs before rendering. Fixed `save_message` to return IDs.
  - `src/asky/api/client.py`: Threaded message/session IDs and added `FinalizeResult`.
  - `src/asky/rendering.py`: Persisted `message_id` and `session_id` in `asky-sidebar.js`.
  - `src/asky/data/asky-sidebar.js/css`: Implemented the copy logic and modern UI styles.
- **Improved**:
  - Version bump to **0.2.0** reflects major architectural refinement for history tracking.

## 2026-02-22 - Fix `-vv` Live Banner Corruption + Terminal-Context Session Name Leak

Addressed two regressions reported during real CLI usage:

- Fixed `-vv` output interaction with Rich Live banner:
  - `src/asky/cli/chat.py` now defers `kind="llm_request_messages"` payload rendering while Live is active.
  - Deferred payloads are flushed after Live stops, preserving readable boxed payload output without repeated stale banner snapshots or redraw drift.
- Fixed session names incorrectly becoming `"Terminal Context (Last N lines)..."`:
  - `src/asky/core/session_manager.py`: `generate_session_name()` now strips terminal-context wrapper prefixes before keyword extraction.
  - `src/asky/storage/sqlite.py`: `convert_history_to_session()` now derives names from extracted query text (and no longer uses the broken `split("\\n")` path), with wrapper-aware parsing.
- Added regression tests:
  - `tests/test_cli.py`: verifies double-verbose payloads are not printed through live console and are printed after live stop.
  - `tests/test_sessions.py`: verifies `generate_session_name()` ignores terminal-context wrapper.
  - `tests/test_feature_reply.py`: verifies history-to-session conversion names strip terminal-context wrapper.
- Validation:
  - Targeted: `uv run pytest tests/test_cli.py tests/test_feature_reply.py tests/test_sessions.py` -> passed.
  - Full suite: `uv run pytest` -> 562 passed.

## 2026-02-22 - Title-Based Grouping Algorithm Fix

Improved the grouping and naming logic for HTML archive reports in the sidebar.

- **Changed**:
  - `src/asky/rendering.py`: Derived `prefix` for grouping from the first 3 words of the **display title** (lowercased) instead of the filename slug. This prevents filtering of numbers (like "A16z") and improves prefix reliability.
  - `src/asky/data/asky-sidebar.js`: Added `longestCommonTitlePrefix` algorithm to the sidebar. The UI now dynamically computes the longest common word-prefix among items in a group to use as the displayed group name.
  - `tests/test_html_report.py`: Updated unit tests to reflect title-based prefix derivation.
- **Why**:
  - The previous slug-based derivation often dropped important context (numbers, stopwords), leading to mismatched or confusing group names.
  - Using the longest common prefix ensures that identical titles produce a group named exactly after that title, and slightly diverging titles (e.g., "Part 1" vs "Part 2") produce an intuitive common header.
- **Validation**:
  - Successfully ran `uv run pytest tests/test_html_report.py` and the full test suite (45 tests passed).

## 2026-02-22 - Double-Verbose Outbound Main-Model Payload Trace (`-vv`)

Added a second verbosity level for targeted prompt/debug inspection without digging through noisy log files.

- Added `-v` level parsing via count mode in `src/asky/cli/main.py`:
  - `-v` keeps existing verbose behavior.
  - `-vv` enables new double-verbose mode.
  - Normalized parsed args to `args.verbose` (bool), `args.double_verbose` (bool), and `args.verbose_level` (int) for backward compatibility.
- Added `double_verbose` to `AskyConfig` (`src/asky/api/types.py`) and propagated it through:
  - `src/asky/cli/chat.py` (CLI config construction),
  - `src/asky/api/client.py` (engine construction),
  - `src/asky/core/engine.py` (runtime behavior).
- `ConversationEngine` now emits full outbound main-model request payload events (`kind="llm_request_messages"`) in double-verbose mode before each main-loop LLM call and graceful-exit LLM call.
- CLI verbose renderer now recognizes and prints those payloads as readable boxed output (Rich panels + summary table + per-message panels), including all system/user/tool messages passed to the main model.
- Kept existing verbose tool-call rendering intact and made payload kinds explicit (`kind="tool_call"`).
- Added/updated tests:
  - `tests/test_cli.py`: parser coverage for `-v` vs `-vv` level normalization.
  - `tests/test_llm.py`: engine coverage for double-verbose outbound payload emission.
  - `tests/test_lean_mode.py`: updated engine-constructor expectation for the new `double_verbose` argument.
- Validation:
  - Targeted run: `uv run pytest tests/test_cli.py tests/test_llm.py tests/test_lean_mode.py` -> passed.

## 2026-02-22 - Session Idle Timeout Prompt

Added a configurable inactivity timeout for shell sessions.

- Added `last_used_at` to `sessions` table in SQLite.
- Added `idle_timeout_minutes` setting (default 5).
- Implemented interactive CLI prompt (Continue / New Session / One-off) when resuming a stale session.
- Cleaned up unused legacy columns `is_active` and `ended_at` from sessions table DDL.
- Verified with unit tests in `tests/test_idle_timeout.py`.

For older logs, see [DEVLOG_ARCHIVE.md](DEVLOG_ARCHIVE.md).

## 2026-02-22

### --edit-model Upfront Role Assignment Prompt

**Summary**: Moved main/summarization model assignment to the start of the `--edit-model` flow so the most common operations (change which model is main or summarization) no longer require going through the full parameter edit wizard.

- **Changed**:
  - `src/asky/cli/models.py`: After the user selects a model to edit, a new action prompt appears immediately with three choices: `m` (set as main model and exit), `s` (set as summarization model and exit), or `e` (enter the full parameter edit flow). The post-save "Set as default main model?" / "Set as summarization model?" prompts that previously appeared after saving are removed.
  - `tests/test_models_cli.py`: Added `test_edit_model_action_m_sets_main_model`, `test_edit_model_action_s_sets_summarization_model`, and `test_edit_model_action_e_saves_changes` covering all three action paths.
- **Why**:
  - Most users open `--edit-model` to change which model is used for main chat or summarization. Before this change, they had to step through the entire parameter edit wizard first, with role assignment only appearing at the very end after a save confirmation.
- **Gotchas**:
  - Choosing `m` or `s` updates `general.toml` only - model parameters are not modified. To both change parameters and reassign a role, run `--edit-model` twice (once with `e`, once with `m` or `s`).

### Continue Flag Improvements (No-ID Default + Auto-Session Conversion)

**Summary**: Improved the `-c`/`--continue-chat` flag to default to the last message when used without an ID, and to automatically convert history-based continuations into active sessions.

- **Added**:
  - `tests/test_cli_continue.py`: New unit tests for sentinel resolution and auto-conversion.
- **Changed**:
  - `src/asky/cli/main.py`:
    - Updated `-c` to use `nargs="?"` with a `__last__` sentinel.
    - Added logic to resolve the sentinel to `"~1"`.
    - Implemented automatic session conversion via `convert_history_to_session` when continuing from history without an active session.
    - Switched `get_shell_session_id` to a direct import for simplified logic.
- **Why**:
  - Users wanted a faster way to continue the last conversation without looking up IDs.
  - Converting to sessions ensures that follow-up turns are stored together and the conversation remains resumable.
- **Gotchas**:
  - Because `-c` now takes an optional value, queries must be placed before the flag if the flag is used at the end of the command line, or use `--` to disambiguate.

### Banner Totals Fix (Non-Session Runs) + Clearer Totals Label

**Summary**: Fixed banner session totals showing `0` outside active sessions and renamed the totals row label from `Session` to `Conversation` for clarity.

- **Changed**:
  - `src/asky/storage/__init__.py`: Added `get_total_session_count()` wrapper for DB-wide session totals.
  - `src/asky/cli/display.py`: Banner state now fetches total session count directly from storage regardless of active session manager state.
  - `src/asky/cli/main.py`: Initial banner (`show_banner`) now includes the real total session count instead of hardcoded `0`.
  - `src/asky/banner.py`: Renamed the full-banner totals row label from `Session    :` to `Conversation:`.
  - `tests/test_banner_embedding.py`: Added regression coverage to assert total sessions are populated when no session is active.
  - `tests/test_banner_compact.py`: Added coverage for the full-banner `Conversation` label.
  - `src/asky/cli/AGENTS.md`: Documented that banner totals are DB-wide, even without an active session.
- **Why**:
  - Users need reliable global counts even in single-turn/non-session runs.
  - The previous row label suggested a single active session, while the row actually mixes global totals plus optional current-session details.
- **Gotchas**:
  - `Messages` remains the non-session history message count (`session_id IS NULL`), while `Sessions` is total rows in `sessions`.

### Report HTML and Sidebar Refinements

**Summary**: Full externalization of CSS and JS assets for archive files and sidebar index.

- **Externalized Report Assets**: Extracted styles to `asky-report.css` and logic to `asky-report.js`.
- **Externalized Sidebar Assets**: Extracted sidebar styles to `asky-sidebar.css` and logic to `asky-sidebar.js`.
- **Single-Copy Asset Management**: A new `_ensure_archive_assets()` helper copies all shared assets (JS, CSS, and Favicon) to the archive directory on first use. Assets are never overwritten, ensuring the archive directory is self-contained and efficient.
- **Favicon**: Added `asky-icon.png` to the sidebar index.
- **Correct HTML title**: individual report files now use their display title in the `<title>` tag.
- **Archive Directory Restructure**: Organized generated reports into a more structured layout:
  - `index.html`: The main entry point (renamed from `sidebar_index.html`).
  - `results/`: Contains all individual report HTML files.
  - `assets/` and `results/assets/`: Shared CSS/JS/Icons are organized into logical asset folders.
- **Smart Asset Versioning**:
  - JS files now include a version suffix (e.g., `asky-report_v0.1.7.js`).
  - When the installed Asky version changes, stale versioned assets are automatically replaced.
  - Unversioned assets (CSS, icons) are never overwritten, allowing for user customization.
- **Improved Sidebar Defaults**: Grouping is now enabled by default. Multiple reports from the same session or with similar names are collapsed into groups automatically, while solo reports are rendered flat.
- **Improved Maintainability**: The HTML templates are now clean and focused solely on structure and data injection, with all presentation and behavior logic living in external files.

### API Library Test Hardening: Remove `mini` Alias Usage + Assert Mocked Turn Path

**Summary**: Hardened `tests/test_api_library.py` so the suspected tests cannot accidentally be interpreted as `mini` model usage and now explicitly assert mocked execution for `run_turn`.

- **Changed**:
  - `tests/test_api_library.py`:
    - Updated retrieval-guidance `build_messages` tests to use `model_alias="gf"` instead of `model_alias="mini"`.
    - Updated two `run_turn` tests to return `"Final"` from mocked `AskyClient.run_messages` and assert `run_messages` was called, guaranteeing the mocked path was used.
    - Added an assertion on returned `final_answer` in the explicit-path hint test to verify mocked return propagation.
- **Why**:
  - Remove residual `mini` alias references from these unit tests to eliminate confusion about local model activity attribution.
  - Make mock usage explicit so these tests fail immediately if they ever stop using the mocked `run_messages` path.
- **Gotchas**:
  - These tests are message-construction/orchestration checks; they do not exercise real LLM calls by design.

### Configurable Built-In Prompt Text Overrides (Research Guidance + Tool Descriptions)

**Summary**: Made built-in research guidance and built-in tool prompt text user-overridable via config, and added commented template examples so users can tune behavior without forking.

- **Changed**:
  - `src/asky/config/__init__.py`: Added `RESEARCH_RETRIEVAL_ONLY_GUIDANCE_PROMPT` and `TOOL_PROMPT_OVERRIDES` constants sourced from `[prompts]`.
  - `src/asky/core/prompts.py`: `append_research_guidance()` now reads retrieval-only guidance from config instead of hardcoded text.
  - `src/asky/core/tool_registry_factory.py`: Added `_apply_tool_prompt_overrides(...)` and applied it to built-in default/research tool schemas (`description` and `system_prompt_guideline`), including `save_memory`.
  - `src/asky/data/config/prompts.toml`: Added default `research_retrieval_only_guidance` prompt key.
  - `src/asky/data/config/user.toml`: Added commented examples for prompt and per-tool override knobs (`prompts.tool_overrides.<tool_name>...`).
  - `docs/configuration.md`: Added section documenting prompt/tool text override keys.
  - `ARCHITECTURE.md`: Updated standard query flow to note config-driven built-in tool prompt override application.
  - `tests/test_api_library.py`: Added coverage for retrieval-guidance override in system prompt assembly.
  - `tests/test_tools.py`: Added coverage for default and research registry tool prompt override behavior.
- **Why**:
  - Users should be able to tune operational prompt behavior (including built-in tool guidance text) from config files, rather than editing source.
  - This enables model-specific prompt tuning, especially for smaller models that need tighter procedural guidance.
- **Gotchas**:
  - These overrides change prompt/tool text only; they do not alter tool execution semantics or availability rules.
  - Preload shortlist can still perform web retrieval unless separately disabled by existing shortlist settings.

### Standard vs Research Documentation Clarification + Research-Memory Prompt Tightening

**Summary**: Added a direct, non-marketing comparison of standard mode vs research mode in docs, and tightened research prompt guidance so models are explicitly steered to use `save_finding`/`query_research_memory` more reliably.

- **Changed**:
  - `docs/research_mode.md`: Added a side-by-side mode comparison table, explicit "when research mode helps vs hurts" guidance, documented session-scoped research-memory behavior vs `save_memory`, and added a candid section on current workflow gaps (including weaker-model underuse of research memory tools).
  - `src/asky/core/prompts.py`: Expanded retrieval-only guidance to explicitly distinguish `save_finding` vs `save_memory`, and added a pre-final-answer `query_research_memory` loop.
  - `src/asky/data/config/prompts.toml`: Updated default research system prompt workflow with a dedicated "VERIFY MEMORY LOOP" step before synthesis and clarified memory tool intent boundaries.
- **Why**:
  - Users needed a realistic explanation of the two modes and their tradeoffs, especially around latency/quality balance and model-dependent behavior.
  - Smaller models can skip research-memory tool calls unless the workflow instructions are explicit and operational.
- **Gotchas**:
  - Prompt changes increase guidance pressure but do not guarantee tool usage; actual behavior remains model-dependent.
  - This update changes default prompt behavior only; no retrieval/storage architecture was altered.

### Sidebar Index UX Improvements: Sorting and Smart Grouping

**Summary**: Upgraded the `sidebar_index.html` navigation app with client-side sorting (Date/A-Z), smart grouping (Session/Prefix), and JSON-based index storage.

- **Changed**:
  - `src/asky/rendering.py`:
    - Reworked `sidebar_index.html` generation to use a JSON-in-HTML storage model (`ENTRIES` JSON array).
    - Implemented client-side sorting (Date, Alphabetical) and smart grouping (Session Name or 3-word Slug Prefix) in the sidebar app.
    - Updated `save_html_report` and `_save_to_archive` to accept and persist `session_name`.
  - `src/asky/cli/chat.py`: Updated `save_html_report` call site to pass the active session name for improved metadata.
  - `tests/test_html_report.py`: Enhanced unit tests to cover JSON storage, prefix logic, and grouping.
- **Why**:
  - The previous sidebar was a static list that grew uncontrollably. Users needed a way to organize reports by session or topic and sort them for easier retrieval.
- **Gotchas**:
  - The grouping logic uses exact prefix/session matching; it does not perform fuzzy clustering.
  - The index file is fully rewritten on each save to maintain the integrity of the JSON and JS app logic.

### Final-Answer-First Banner Fix + Research Summary Drain

**Summary**: Restored final-answer-first CLI behavior and fixed the stale final banner snapshot by draining pending `ResearchCache` background summaries before the last live-banner stop.

- **Changed**:
  - `src/asky/research/cache.py`: Added pending-future tracking for background summarization jobs and introduced `wait_for_background_summaries(timeout=None)` to synchronously wait for all currently queued summary work without shutting down the executor.
  - `src/asky/cli/chat.py`: Added a post-answer research-mode drain step (`_drain_research_background_summaries`) during deferred history finalization while Live is active, with explicit banner status messaging and a final refresh before stop.
  - `tests/test_research_cache.py`: Added coverage that `wait_for_background_summaries()` reports incomplete work under tight timeout and completes after background summarization is released.
  - `tests/test_cli.py`: Added coverage asserting final answer rendering happens before deferred history finalization and that research background summary drain is invoked.
- **Why**:
  - The previous banner lifecycle could stop Live before fire-and-forget research summarizers finished, freezing the final snapshot with stale summarizer token counts.
  - A regression in finalization ordering made it possible for users to feel blocked by post-answer summarization tasks before seeing the final answer clearly.
- **Gotchas**:
  - The drain step is scoped to research-mode CLI post-answer finalization; non-research turns skip it.
  - `wait_for_background_summaries()` waits only on futures known at call time, which matches CLI teardown expectations after tool execution has finished.

## 2026-02-21

### On-Demand Summarization Replacing Truncation in Smart Compaction

**Summary**: When `_compact_tool_message` has no cached summary for a URL and the content exceeds 500 chars, it now generates a summary on the spot via the LLM instead of brutally truncating.

- **Changed**:
  - `src/asky/core/engine.py`: Extracted `_summarize_and_cache(url, content)`. Calls `_summarize_content` (same prompt and caps used by the background cache summarizer). If the URL already exists in the research cache DB, saves the generated summary back so future compactions find it immediately. Falls back to truncation only if summarization itself raises an exception. Both the dict-value and string-value fallback branches in `_compact_tool_message` now call this helper.
  - `tests/test_llm.py`: Updated `test_conversation_engine_compacts_large_tool_payloads_before_append` to mock `_summarize_and_cache` returning a stub and assert `[COMPACTED]` prefix instead of `[TRUNCATED]`.
- **Why**:
  - Truncation discards context permanently. The model then reasons over a broken `... [TRUNCATED]` stub which often causes it to re-fetch the same URL. Summarization preserves semantic content, and the DB write prevents re-summarizing the same URL on subsequent compactions.
- **Gotchas**:
  - `_save_summary` is a "protected" method on `ResearchCache`. If the URL is not in the research cache (e.g. tool returned content without going through the cache), the summary is generated but not persisted - the engine logs this at DEBUG level and continues normally.

### Max Turns CLI Override

**Summary**: Implemented the `-t`/`--turns` command-line flag to override and persist the maximum turn count for conversation sessions.

- **Added**:
  - `src/asky/cli/main.py`: Added `-t`/`--turns` argument and passed it to `AskyTurnRequest`.
- **Changed**:
  - `src/asky/api/types.py`: Added `max_turns` field to `AskyTurnRequest` and `SessionResolution`.
  - `src/asky/api/session.py`: `resolve_session_for_turn` now propagates `max_turns` to session creation or updates it on session resumption.
  - `src/asky/api/client.py`: Propagated `max_turns` through the turn execution flow and calculated effective turn limits.
  - `src/asky/core/engine.py`: `ConversationEngine` now respects dynamically set `max_turns` instead of a hardcoded constant.
  - `src/asky/core/session_manager.py`: `create_session` now accepts and persists `max_turns`.
  - `src/asky/storage/sqlite.py`: Added `max_turns` column to `sessions` table and implemented related CRUD operations.
  - `src/asky/cli/display.py`: `InterfaceRenderer` now displays the effective turn limit in the live banner.
  - `src/asky/cli/chat.py`: Injected `max_turns` from CLI arguments into the API request layer.
- **Fixed**:
  - `src/asky/cli/main.py`: Fixed a `NameError` for `parse_session_selector_token` discovered during end-to-end testing.
- **Why**:
  - Users needed a way to control the longevity of complex multi-turn research or coding sessions without modifying global configuration files. Persisting this per-session ensures resumption respects the user's intent.

### Sidebar Index App and Pure-Content Reports

**Summary**: Redesigned the sidebar navigation to decouple individual reports from the navigation chrome. Reports are now pure HTML files, while `sidebar_index.html` acts as a navigation app that loads reports within an iframe.

- **Added**:
  - `src/asky/rendering.py`: `_update_sidebar_index` now generates a sophisticated two-pane HTML application with JavaScript hash-based navigation and active link highlighting.
- **Changed**:
  - `src/asky/template.html`: Reverted to a simple, centered, pure-content layout (no more embedded sidebar iframe).
  - `src/asky/rendering.py`: `save_html_report` now returns a tuple containing both the direct file path and a sidebar-wrapped URL (using a hash fragment).
  - `src/asky/cli/chat.py`: Updated to display two links after each generation: one for the clean report and one for the indexed view.
- **Why**:
  - Embedding navigation in every file was redundant and made generated files harder to share as standalone documents. By making `sidebar_index.html` a standalone "app", we preserve the navigation history while keeping individual reports clean and portable.

### Tool Usage Initialization Configuration

**Summary**: Initialized the tracking for all available tools at the beginning of executions with a defaults of 0 so they're immediately visible in the banner.

- **Changed**:
  - `src/asky/core/api_client.py`: Added `init_tools(tool_names)` to `UsageTracker` that pre-populates the dictionary with zeroes.
  - `src/asky/core/engine.py`: Extracted the tool names from `ToolRegistry` right after schemas are generated, and passed them to `init_tools()` during `ConversationEngine.run()` initialization.
- **Why**:
  - Previously tools only appeared in the live UI banner after they were explicitly used, which prevented the user from easily seeing the capabilities granted to the model for a specific turn config setting.

### Banner Integration and Background Summarization Tracking

**Summary**: Fixed a set of bugs where the background `ResearchCache` summarizer wouldn't attribute token usage to the live UI banner, and corrected the "Sessions" and "Messages" counts displaying zeros when initialized.

- **Changed**:
  - `src/asky/research/cache.py` & `tools.py`: Plumbed `summarization_tracker` (extracted from tool arguments via the tool registry factory) straight into `cache_url` and its internal thread pool. This guarantees LLM text summarization triggers update the main application's metrics correctly.
  - `src/asky/cli/display.py` & `banner.py`: Reworked `BannerState` formatting to accurately query `get_db_record_count()` and specifically query the `SessionManager`'s SQLite repository for total past sessions.
  - `src/asky/api/client.py`: Injected a `session_resolved_callback` directly into `run_turn` logic. This ensures the CLI renderer is attached to the valid `SessionManager` state well before rendering pauses.
- **Why**:
  - The live tracking UI was showing `0 tokens` on the summarizer because `get_link_summaries` spun up independent jobs bypassing the global `UsageTracker`. Likewise, the UI rendered `0` session/messages since the session resolution happened too late for the rendering object to consume it.

### Markdown Rendering List Indentation Fix

**Summary**: Fixed a bug in the `casual-markdown` parser used for HTML archives that caused nested lists to render with extreme indentation due to improperly joined `<ul>` and `<ol>` tags.

- **Changed**:
  - `src/asky/template.html`: Expanded the list tag joining regex (`/<\/[ou]l\>\n<[ou]l\>/g`) into a `do...while` loop consisting of explicit matches for `<ul>`, `<ol>`, and nested `<ul><ul>` tag groupings. This guarantees consecutive lists correctly merge.
- **Why**:
  - The previous regex logic had two fatal flaws:
    1. It only replaced the first level of adjacent tags per pass. Deeply nested or consecutive lists caused the regular expression to leave unbalanced `<ul>` tags.
    2. Because it targeted `[ou]l`, it erroneously merged lists of different formats (e.g., merging an `</ol>` closing tag with a `<ul>` opening tag). This wiped out closing tags for adjacent blocks and caused the browser to exponentially indent list content.

### Token Usage Tracking Fix

**Summary**: Fixed a bug where token usage statistics were merged together when the main model and the summarization model shared the same alias, and resolved a shallow copy mutation issue that compounded usage statistics improperly.

- **Changed**:
  - `src/asky/cli/display.py`: `_get_combined_token_usage()` now separates summarizer token counts by appending ` (Summary)` to identical model aliases. Additionally, implemented a deep copy when combining usages to prevent token figures from compounding exponentially during live banner updates.
- **Why**:
  - When the same model was configured for both main chat and summarization operations, their input and output tokens were summed up blindly. This prevented users from tracking cost or context overhead from summaries separately.
  - Due to a shared reference, token counts were repeatedly added to themselves on every UI refresh.

## 2026-02-20

### Lean Mode Speed Optimizations

**Summary**: Optimized the execution path for lean mode by bypassing summarization and background extraction.

- **Changed**:
  - `src/asky/api/client.py`: Disabled memory auto-extraction, global trigger checks, and dialogue summarizations (`generate_summaries`) when `--lean` is active.
  - `src/asky/cli/chat.py`: Skipped HTML report generation when `--lean` is enabled to save I/O and markdown generation time.
  - `tests/test_cli.py`: Fixed a missing import error (`run_chat`) in `test_run_chat_passes_system_prompt_override`.
- **Key Behavior**:
  - Lean mode now skips non-essential processing steps entirely to provide the fastest response possible. This reduces CPU and I/O overhead significantly.

## 2026-02-20

### Extensive Documentation Migration

**Summary**: Migrated extensive detailed documentation from `README.md` into dedicated markdown files within a new `docs/` directory.

- **Added**:
  - `docs/research_mode.md`: Detailed explanation of Deep Research Mode, caching, vectors, evidence extraction, etc.
  - `docs/elephant_mode.md`: Explanation of global and session-scoped User Memory triggers and mechanics.
  - `docs/custom_tools.md`: Notes on extending the LLM's capabilities via custom local shell commands.
  - `docs/configuration.md`: Notes on TOML configs, API Keys, Sessions, and Web Search configurations. Highly expanded to detail Limits, Timeouts, Session Compaction, and deeply explain the post-query Summarization Step (and why it temporarily blocks the shell prompt).
- **Changed**:
  - `README.md`: Completely rewritten to act as a focused entry point. Added a "Mindset / Philosophy" section illustrating the core single-command UNIX-tool approach of the project, followed by a succinct CLI feature overview and a Documentation Index linking to the extended `docs/*.md` files.
- **Why**:
  - The README was becoming too long and crowded, making it difficult for new users to quickly grasp the core feature set without scrolling through deep implementation details.

## 2026-02-19

### User Memory Refactor: Session Scoping & Global Triggers

**Summary**: Refactored the user memory system to be **session-scoped by default**. Added a "Universal Global Trigger" feature to explicitly save global memories.

- **Changed**:
  - `src/asky/storage/sqlite.py`: Added `session_id` column to `user_memories`.
  - `src/asky/memory/store.py` & `vector_ops.py`: Updated storage and retrieval to respect session ID.
  - `src/asky/api/client.py`: Implemented global trigger interception (default: "remember globally:", "global memory:").
  - `README.md`: Documented new scoping behavior and triggers.
- **Key Behavior**:
  - **Session Isolation**: Memories saved during a session (e.g., `asky -ss "Work"`) are only recalled in that session.
  - **Global Fallback**: Global memories (saved with no session) are available to **all** sessions.
  - **Global Triggers**: Starting a query with "remember globally:" strips the trigger, runs the turn, and extracts facts into the _global_ scope.

## 2026-02-18

### User Memory Feature

**Summary**: Implemented a persistent cross-session user memory system. The LLM can save user facts via a `save_memory` tool, memories are recalled automatically each turn (injected into system prompt), deduplicated via cosine similarity, and can be auto-extracted per-session via `--elephant-mode`.

- **Added**:
  - `src/asky/memory/` — new package:
    - `store.py` — SQLite CRUD for `user_memories` table.
    - `vector_ops.py` — embedding store/search via Chroma (`asky_user_memories` collection) with SQLite BLOB fallback.
    - `recall.py` — per-turn recall pipeline injecting `## User Memory` into system prompt.
    - `tools.py` — `save_memory` LLM tool with dedup (cosine ≥ 0.90 threshold).
    - `auto_extract.py` — background LLM extraction of facts from conversation turns.
    - `AGENTS.md` — package documentation.
  - `src/asky/data/config/memory.toml` — configurable memory defaults.
  - `src/asky/cli/memory_commands.py` — `--list-memories`, `--delete-memory`, `--clear-memories` handlers.
  - `tests/test_user_memory.py` — 28 test cases covering store, recall, tools, CLI flags, session persistence, auto-extraction, and system prompt injection.
- **Changed**:
  - `src/asky/config/__init__.py` — added `USER_MEMORY_*` constants.
  - `src/asky/config/loader.py` — loads `memory.toml`.
  - `src/asky/storage/interface.py` — `Session` dataclass gains `memory_auto_extract` field; added abstract `set_session_memory_auto_extract`.
  - `src/asky/storage/sqlite.py` — `user_memories` table init + migration, `memory_auto_extract` column, session CRUD updated.
  - `src/asky/api/types.py` — `elephant_mode` on `AskyTurnRequest`, `memory_auto_extract` on `SessionResolution`, `memory_context` on `PreloadResolution`.
  - `src/asky/api/preload.py` — memory recall as first step in `run_preload_pipeline`.
  - `src/asky/api/client.py` — injects `memory_context` into system prompt; launches auto-extraction daemon thread when `memory_auto_extract` is set.
  - `src/asky/api/session.py` — `resolve_session_for_turn` propagates `elephant_mode` to session creation/resumption.
  - `src/asky/core/session_manager.py` — `create_session` accepts `memory_auto_extract`.
  - `src/asky/core/tool_registry_factory.py` — `save_memory` registered in default and research registries.
  - `src/asky/cli/main.py` — added `--list-memories`, `--delete-memory`, `--clear-memories`, `--elephant-mode`/`-em` flags; fixed `list_tools` early-exit to use `getattr` (resolves pre-existing test breakage from `8d233f6`).
  - `src/asky/cli/chat.py` — passes `elephant_mode` to `AskyTurnRequest` with guard warning when no session is active.
  - `tests/test_startup_cleanup.py` — fixed mock_args fixture to include `list_tools`/memory flags so MagicMock doesn't return truthy for them.
  - `ARCHITECTURE.md` — added `memory/` package, User Memory Flow, Decision 17.
- **Gotchas**:
  - Memory is always **global** (not session-scoped); contrast with research findings which are session-scoped.
  - `--elephant-mode` without `-ss`/`-rs` is silently ignored (with a printed warning).
  - `has_any_memories()` checks for `embedding IS NOT NULL` to avoid running the embedding pipeline when the table is empty.
  - Auto-extraction runs in a daemon thread; no result is awaited.

## 2026-02-17

### Lean Mode Enhancements (Tool Disabling + Clean System Prompt)

**Summary**: Enhanced `--lean` mode to automatically disable all tools, suppress per-turn "Turns Remaining" system prompt updates, and silence informational CLI output (banners, labels, save messages) for a distraction-free experience.

- **Changed**:
  - `src/asky/cli/chat.py`:
    - `run_chat` now disabled tools when `lean=True`.
    - suppresses banner, "Assistant:" label, and informational messages ("Saving...", "Open in browser...") in lean mode.
  - `src/asky/core/engine.py`: `ConversationEngine` now accepts a `lean` flag and suppresses `[SYSTEM UPDATE]` messages when enabled.
  - `src/asky/api/client.py`: Propagated `lean` flag and `disabled_tools` overrides through `run_turn`, `run_messages`, and `chat` methods.
- **Added**:
  - `tests/test_lean_mode.py`: New comprehensive tests for lean mode behavior across CLI, API, and Engine layers, including output suppression.
- **Why**:
  - Users wanted a true "lean" mode that relies solely on the model's internal knowledge without tool overhead, nagging system updates, or CLI noise.

## 2026-02-14

### Tool Management Improvements (Autocomplete, List, Disable-All)

**Summary**: Enhanced the CLI and core tool registration to improve tool discoverability and management. Added shell autocompletion for tool names, a command to list available tools, and a convenient way to disable all tools at once.

- **Added**:
  - `src/asky/core/tool_registry_factory.py`: `get_all_available_tool_names()` helper to discover all registered tools (default, research, custom, push-data).
  - `src/asky/cli/completion.py`: `complete_tool_names()` provider for argcomplete.
  - **CLI**:
    - `--list-tools`: New flag to print available LLM tools and exit.
    - `--tool-off all`: New keyword to disable all tools in a single command.
- **Changed**:
  - `src/asky/cli/main.py`: Integrated the new flag and registered the autocompleter.
  - `src/asky/cli/chat.py`: Updated `_parse_disabled_tools` to handle the `all` keyword.
- **Tests**:
  - Added `tests/test_tool_management.py` covering tool discovery, completion, and wildcard disabling.
- **Why**:
  - Improved UX for users who want to know what tools are available or want to quickly run a "clean" LLM pass without tool overhead.
  - Addresses the difficulty of manually entering long tool names without shell completion.

## 2026-02-14

### System Prompt Override Flag and API Capability

**Summary**: Added support for overriding the default system prompt via CLI and API. This allows users to customize the model's behavior/persona without modifying configuration files.

- **Added**:
  - CLI: `--system-prompt` / `-sp` flag in `src/asky/cli/main.py`.
  - API: `system_prompt_override` field to `AskyConfig` in `src/asky/api/types.py`.
- **Changed**:
  - `src/asky/api/client.py`: `build_messages` uses the override if provided.
  - `src/asky/cli/chat.py`: Propagates CLI flag to API config and updated signature of CLI-layer `build_messages`.
- **Tests**:
  - Added coverage for override logic in `tests/test_api_library.py` and argument parsing in `tests/test_cli.py`.
- **Why**:
  - Provides a quick way to switch model personas or experiment with system instructions on the fly.
  - Useful for specialized research tasks or specific model instruction requirements.

### Session-Scoped Research Data Cleanup

**Summary**: Added CLI and API support for selective cleanup of research findings and vector embeddings while preserving conversation history. This allows users to "forget" research context for a specific session without losing the chat log.

- **Added**:
  - `src/asky/research/cache.py`: `delete_findings_by_session()` method.
  - `src/asky/research/vector_store_finding_ops.py`: `delete_findings_by_session()` function (SQLite + Chroma).
  - `tests/test_session_research_cleanup.py`: Comprehensive tests for session isolation and multi-layer cleanup.
- **Changed**:
  - **CLI**:
    - `src/asky/cli/main.py`: Added `--clean-session-research SESSION_SELECTOR` flag.
    - `src/asky/cli/sessions.py`: Implemented `handle_clean_session_research_command` with session resolution.
  - **API**:
    - `src/asky/api/client.py`: Added `cleanup_session_research_data()` orchestration method.
  - **Tests**:
    - `tests/test_startup_cleanup.py`: Fixed regression where truthy MagicMocks for new flag caused early exit.
- **Why**:
  - Complements `--delete-sessions` (full wipe) with a surgical research-only cleanup option. Useful when research data becomes stale or irrelevant but the conversation summary is still valuable.

### Evidence-Focused Extraction Pipeline Step

**Summary**: Added a post-retrieval evidence extraction step that processes retrieved chunks with a focused LLM prompt to extract structured facts. This improves synthesis quality, especially for smaller models.

- **Added**:
  - `src/asky/research/evidence_extraction.py`: New module for fact extraction and context formatting.
  - `tests/test_evidence_extraction.py`: Unit tests for extraction logic and edge cases.
- **Changed**:
  - **Pipeline Integration**:
    - `src/asky/api/preload.py`: `run_preload_pipeline` now optionally runs `extract_evidence_from_chunks` if enabled.
    - `src/asky/api/types.py`: `PreloadResolution` updated with `evidence_context` and `evidence_payload` fields.
  - **Configuration**:
    - `src/asky/data/config/research.toml`: Added `evidence_extraction_enabled` (default false) and `evidence_extraction_max_chunks` (default 10).
    - `src/asky/config/__init__.py`: Exported new research constants.
  - **Documentation**:
    - `src/asky/research/AGENTS.md`: Documented new module.
    - `ARCHITECTURE.md`: Added Design Decision #16 and updated retrieval flow diagram.
- **Why**:
  - Raw chunks can be noisy or contain irrelevant info; pre-extracting focused facts makes the final synthesis step more reliable and efficient.

**Post-Review Fixes (Round 1)**:

- Fixed `is_corpus_preloaded` to remove circular dependency: evidence extraction only runs when corpus is already preloaded, so `evidence_found` check was dead code.
- Simplified dataclass serialization in preload.py: removed fragile `hasattr` check and duplicate fallback logic.
- Restored Decision 15 (Query Expansion) to ARCHITECTURE.md that was accidentally removed.
- Added missing `asdict` import in preload.py.

**Post-Review Fixes (Round 2)**:

- **client.py**: Removed confusing leftover comment block and simplified return shape to `{"deleted": int}`.
- **cache.py**: Removed `delete_findings_by_session()` method (dead code — `vector_store_finding_ops` already handles both SQLite + Chroma cleanup).
- **vector_store_finding_ops.py**: Removed ownership-confusion comment explaining cache vs vector_store split.
- **sessions.py**: Updated CLI output to use `results['deleted']` instead of `results['findings_deleted']`.
- **preload.py**: Added guard for empty `sub_queries` in evidence extraction block to short-circuit gracefully.
- **tests/test_session_research_cleanup.py**: Removed obsolete `test_cache_delete_findings_by_session`, updated orchestration and CLI tests to use new return shape.

### Per-Stage Research Tool Exposure + Simplified Retrieval Guidance

**Summary**: Refactored research tools into Acquisition and Retrieval sets. The system now dynamically excludes acquisition tools (caching/browsing) when a corpus is pre-loaded (web shortlist or local ingestion), forcing the model to focus on retrieval and synthesis. Added a streamlined "retrieval-only" system prompt guidance for these scenarios.

- **Changed**:
  - **Tool Grouping**:
    - `src/asky/research/tools.py`: Defined `ACQUISITION_TOOL_NAMES` and `RETRIEVAL_TOOL_NAMES`.
  - **Dynamic Registry**:
    - `src/asky/core/tool_registry_factory.py`: `create_research_tool_registry` now accepts `corpus_preloaded` and excludes acquisition tools when true.
  - **Prompt Guidance**:
    - `src/asky/core/prompts.py`: Added `RESEARCH_RETRIEVAL_ONLY_GUIDANCE` constant.
    - `src/asky/api/client.py` & `src/asky/cli/chat.py`: Injected retrieval-only guidance in `build_messages` when `corpus_preloaded=True`.
  - **Orchestration**:
    - `AskyClient.run_turn` now calculates `corpus_preloaded` based on preload stats and propagates it through the message building and tool registry creation phases.
- **Added Tests**:
  - `tests/test_tools.py`: Verified tool set coverage and conditional registry exclusion.
  - `tests/test_api_library.py`: Verified prompt guidance injection and orchestration state propagation.
  - `tests/test_cli.py`: Verified CLI message building parity.
- **Documentation**:
  - `ARCHITECTURE.md`: Added Design Decision #14 (Corpus-Aware Tool Exposure).
  - `src/asky/research/AGENTS.md`: Documented tool set split.
  - `src/asky/core/AGENTS.md`: Documented `corpus_preloaded` registry behavior.

- **Why**:
  - Prevents LLMs from wasting turns on redundant URL discovery/caching when data is already available in the preloaded corpus.
  - Simplifies the tool surface for smaller models in retrieval-heavy stages.

- **Result**: 478 tests pass (471 baseline + 7 new tests/updates).

**Post-Review Fixes**:

- Fixed type annotation: `messages` local variable now correctly typed as `List[Dict[str, Any]]` instead of `List[Dict[str, str]]` in `client.py`.
- Removed backward compatibility shim from `AskyClient.chat()` — now directly uses `PreloadResolution` parameter (no external users to break).
- Fixed DEVLOG.md archive link from absolute `file:///` URL to relative markdown link.
- Removed dead `PreloadResolution` import from `test_cli.py`.
- Removed unused `import sys` from `cli/chat.py`.

### Query Expansion

**Summary**: Added pre-retrieval query expansion to improve recall for complex multi-part questions. The system now decomposes queries into 2-4 focused sub-queries before search and scoring.

- **Implementation**:
  - Created `src/asky/research/query_expansion.py` with two modes:
    - **Deterministic**: Uses YAKE keyphrase extraction to form sub-queries
    - **LLM-assisted** (optional): Single structured-output call to decompose the question
  - Integrated into `src/asky/api/preload.py` before shortlist/local ingestion
  - Updated shortlist pipeline to accept and use multiple queries:
    - `source_shortlist.py`: Multi-query search and max-similarity scoring
    - `shortlist_collect.py`: Weighted budget allocation (50% to original, 50% split across sub-queries)
    - `shortlist_score.py`: Max similarity across all sub-query embeddings
  - Added `search_queries` list to shortlist payload alongside legacy `search_query` key
  - Config: `research.toml` controls enabled/mode/max_sub_queries
- **Added Tests**: 6 tests in `tests/test_query_expansion.py` covering both modes and fallback behavior
- **Documentation**: Updated `ARCHITECTURE.md` (Decision #15) and `src/asky/research/AGENTS.md`

**Post-Review Fixes**:

- Fixed AGENTS.md table corruption (restored ChromaDB collection entries, removed file descriptions)
- Removed unused `sub_queries` parameter from `preload_local_research_sources()` signature
- Fixed kwarg forwarding in `expand_query()` proxy to match target function signatures
- Added `search_queries` list to all shortlist payload return points (preserves full query context)
- Improved search budget allocation: original query gets 50%, sub-queries split remainder evenly

## 2026-02-14

### Fix Broken Tests After Local-Corpus Feature

**Summary**: Fixed 5 failing tests caused by stale mock targets after the local-corpus refactoring.

- **Root Causes**:
  - `test_run_chat_local_corpus_implies_research_mode`: Patched `asky.api.AskyClient` instead of `asky.cli.chat.AskyClient` (module-level import). Also missing `MODELS` and `LIVE_BANNER` patches, causing the real client to run and hang indefinitely.
  - `test_asky_client_run_turn_*`: Patched non-existent `AskyClient._save_interaction` and `AskyClient._run_messages` (methods renamed to module-level `save_interaction` and `run_messages`).
  - `test_parse_args_local_corpus`: `-lc` with `nargs="+"` greedily consumed the positional `query` arg. Fixed by adding `--` separator.
  - `test_main_flow*`: Missing `get_shell_session_id` mock caused real session resumption, injecting extra messages into the expected call.
- **Changed**:
  - `tests/test_cli.py`: Rewrote `test_run_chat_local_corpus_implies_research_mode` with correct mock targets. Added `get_shell_session_id` patches to `test_main_flow`, `test_main_flow_verbose`, `test_main_flow_default_no_context`.
  - `tests/test_api_library.py`: Fixed mock targets for `save_interaction` and `run_messages`. Added `research_mode=True` to hint test.
  - `pyproject.toml`: Excluded `temp` dirs from pytest collection to avoid `PermissionError` on runtime artifacts.
- **Result**: 471 tests pass in ~5s.

## 2026-02-13

### CLI Local-Corpus Selective Ingestion (-lc / --local-corpus)

**Summary**: Added a new CLI flag to explicitly provide local file or directory paths for research ingestion, bypassing prompt-based heuristics.

- **Changed**:
  - Updated:
    - `src/asky/cli/main.py`: added `-lc` / `--local-corpus` flag.
    - `src/asky/api/types.py`: added `local_corpus_paths` field to `AskyTurnRequest`.
    - `src/asky/cli/chat.py`: mapped CLI arg to request and forced `research_mode=True` when present.
    - `src/asky/api/preload.py`: updated `run_preload_pipeline` to accept and propagate `local_corpus_paths`.
    - `src/asky/cli/local_ingestion_flow.py`: updated `preload_local_research_sources` to support `explicit_targets` and bypass prompt extraction.
    - `src/asky/api/client.py`: passed `local_corpus_paths` through to preload pipeline.
  - Added tests:
    - `tests/test_cli.py`: parsing and research mode implication.
    - `tests/test_local_ingestion_flow.py`: explicit target bypass coverage.
    - `tests/test_api_library.py`: API flow propagation (fixed hang by mocking LLM calls).
  - Updated docs:
    - `README.md`, `ARCHITECTURE.md`, `src/asky/cli/AGENTS.md`.

- **Why**:
  - Prompt-based local source extraction was unintuitive and fragile.
  - Users needed a way to explicitly define the research corpus for a query.

- **Gotchas / Follow-up**:
  - Explicit paths are still subject to `research.local_document_roots` validation.
  - Automated tests added but execution currently blocked by environment permission issues.

## 2026-02-12

### CLI Help Placeholder Cleanup (Typed Metavars)

**Summary**: Replaced argparse default placeholder names in `--help` output with explicit typed metavars so value expectations are clearer and less repetitive.

- **Changed**:
  - Updated:
    - `/Users/evren/code/asky/src/asky/cli/main.py`
      - added explicit `metavar` values for value-taking flags that previously relied on default destination-name placeholders.
      - applied consistent typed placeholders including:
        - `HISTORY_IDS`
        - `MESSAGE_SELECTOR`
        - `SESSION_SELECTOR`
        - `COUNT`
        - `RECIPIENTS`
        - `EMAIL_SUBJECT`
        - `ENDPOINT`
        - `SESSION_NAME`
        - `MODEL_ALIAS`
        - `HISTORY_ID`
        - `LINE_COUNT`
  - Added tests:
    - `/Users/evren/code/asky/tests/test_cli.py`
      - added `--help` regression test to assert representative typed placeholders are present.
      - added assertions that previous lazy placeholders (`TERMINAL_LINES`, `PRINT_SESSION`, `SESSION_HISTORY`) are no longer shown.
  - Updated docs:
    - `/Users/evren/code/asky/src/asky/cli/AGENTS.md`
      - documented that CLI help metavars are intentionally explicit and user-oriented.

- **Why**:
  - Default argparse metavars mirrored internal arg destinations and made help text look noisy and repetitive.
  - Typed placeholders improve readability and clarify expected value shapes without changing runtime behavior.

- **Gotchas / Follow-up**:
  - This is a user-facing help-text change only; parsing behavior and command semantics are unchanged.

## 2026-02-11

### README Research Mode Documentation Refresh (Web + Local Corpus)

**Summary**: Expanded README guidance for research mode usage/configuration across web-only, local-corpus, and mixed workflows.

- **Changed**:
  - Updated:
    - `/Users/evren/code/asky/README.md`
      - added concrete `--research` usage examples for:
        - web-based research,
        - local-corpus research,
        - mixed web + local runs.
      - documented `research.local_document_roots` configuration with practical `research.toml` examples.
      - clarified local-target behavior:
        - corpus-root gating,
        - root-relative resolution semantics,
        - supported local target forms,
        - guardrail that generic URL/content tools reject local filesystem targets.

- **Why**:
  - Users needed a single, practical entry point for running research mode in both web and local-document scenarios.
  - New local corpus guardrails required explicit documentation to avoid confusion about path handling and required config.

- **Gotchas / Follow-up**:
  - README examples intentionally show absolute-like targets (e.g. `/policy/...`) to match root-relative resolution behavior under configured corpus roots.

### Local Corpus Root Guardrails + Model Path Redaction

**Summary**: Restricted builtin local-source ingestion to configured corpus roots, made local-target resolution root-relative (even for absolute-looking inputs), and removed local path leakage from model-visible prompts.

- **Changed**:
  - Updated configuration:
    - `/Users/evren/code/asky/src/asky/data/config/research.toml`
      - added `research.local_document_roots` (list of allowed corpus roots for builtin local loading).
    - `/Users/evren/code/asky/src/asky/config/__init__.py`
      - exported `RESEARCH_LOCAL_DOCUMENT_ROOTS`.
  - Updated local adapter behavior:
    - `/Users/evren/code/asky/src/asky/research/adapters.py`
      - local fallback now requires configured corpus roots.
      - local targets now resolve as corpus-relative paths under configured roots.
      - added query redaction helper for stripping local target tokens from model-visible user text.
      - absolute-looking local targets are normalized and still resolved under roots.
  - Updated pre-LLM local ingestion context:
    - `/Users/evren/code/asky/src/asky/cli/local_ingestion_flow.py`
      - local preload context is now path-redacted aggregate metadata (document/chunk/char totals), no file names/paths.
      - cache key selection now prefers adapter-provided canonical target when available.
  - Updated model prompt assembly:
    - `/Users/evren/code/asky/src/asky/api/client.py`
      - `run_turn(...)` now redacts local target tokens from model-visible query text when local targets are detected.
      - adds conditional research system guidance to use `query_research_memory` for local knowledge-base retrieval.
    - `/Users/evren/code/asky/src/asky/cli/chat.py`
      - kept CLI `build_messages(...)` parity with optional local knowledge-base guidance block.
  - Added/updated tests:
    - `/Users/evren/code/asky/tests/test_research_adapters.py`
      - coverage for root-required local loading, root-relative absolute target resolution, and query redaction helper.
    - `/Users/evren/code/asky/tests/test_local_ingestion_flow.py`
      - updated expectations for path-redacted local preload context.
    - `/Users/evren/code/asky/tests/test_api_library.py`
      - coverage for local-KB system guidance and run-turn query redaction behavior.
    - `/Users/evren/code/asky/tests/test_cli.py`
      - coverage for CLI message builder local-KB guidance parity.
  - Updated docs:
    - `/Users/evren/code/asky/ARCHITECTURE.md`
    - `/Users/evren/code/asky/src/asky/config/AGENTS.md`
    - `/Users/evren/code/asky/src/asky/research/AGENTS.md`
    - `/Users/evren/code/asky/src/asky/api/AGENTS.md`
    - `/Users/evren/code/asky/src/asky/cli/AGENTS.md`

- **Why**:
  - Prevents unrestricted local-file traversal from prompt-provided targets.
  - Keeps model reasoning focused on sanitized user intent and knowledge-base retrieval instead of filesystem path details.
  - Supports configurable corpus-root policy without adding new dependencies.

- **Gotchas / Follow-up**:
  - Builtin local-source preload is effectively disabled until `research.local_document_roots` is configured by the user.
  - Path token detection still follows current local-target heuristics; bare filenames without path markers may not be detected for preload/redaction.

## 2026-02-09

### Local Filesystem Target Guardrails for Generic Tools

**Summary**: Blocked implicit local-file access in generic URL/content tools so `local://`, `file://`, and path-like targets are no longer accepted there.

- **Changed**:
  - Updated:
    - `/Users/evren/code/asky/src/asky/url_utils.py`
      - added shared target classifiers:
        - `is_http_url(...)`
        - `is_local_filesystem_target(...)`
    - `/Users/evren/code/asky/src/asky/tools.py`
      - `get_url_content`/`fetch_single_url` now reject local targets and non-HTTP(S) schemes with explicit per-URL errors.
      - `get_url_details` now rejects local targets and non-HTTP(S) schemes with explicit errors.
    - `/Users/evren/code/asky/src/asky/research/tools.py`
      - `extract_links`, `get_link_summaries`, `get_relevant_content`, and `get_full_content` now reject local filesystem targets with explicit errors.
  - Added/updated tests:
    - `/Users/evren/code/asky/tests/test_tools.py`
      - coverage for local-target and non-HTTP target rejection in standard URL tools.
    - `/Users/evren/code/asky/tests/test_research_tools.py`
      - coverage for local-target rejection across research content tools.
    - `/Users/evren/code/asky/tests/test_research_adapters.py`
      - updated expectations so research content tools reject `local://...` targets directly.
  - Updated docs:
    - `/Users/evren/code/asky/src/asky/research/AGENTS.md`
    - `/Users/evren/code/asky/docs/research_eval.md`
    - `/Users/evren/code/asky/ARCHITECTURE.md`

- **Why**:
  - Prevents broad URL-oriented tools from becoming implicit local-file readers.
  - Keeps local-source access explicit and intentional through dedicated local-source workflows.

- **Gotchas / Follow-up**:
  - Local-snapshot eval prompts can still include local paths; these tools now return guardrail errors for those targets.
  - If local-source evaluation is still desired through tool calls, introduce dedicated explicit local-source tools and point matrix profiles to those tools.

### RFC/NIST Dataset Expectation Tuning (Wording-Robust Pass Conditions)

**Summary**: Relaxed brittle sentence-exact assertions in `rfc_http_nist_v1` to keyword/number-focused regex checks so semantically-correct paraphrases pass.

- **Changed**:
  - Updated:
    - `/Users/evren/code/asky/evals/research_pipeline/datasets/rfc_http_nist_v1.yaml`
      - converted multiple `contains` checks to robust `regex` patterns with lookaheads:
        - `tls13-legacy-renegotiation-serverhello`
        - `http-obsoletes`
        - `http-safe-idempotent`
        - `nist-aal1-factors`
        - `nist-aal1-30-days`
        - `nist-password-salt-32-bits`
      - patterns now focus on required facts (keywords/numbers), not exact sentence formatting.
    - `/Users/evren/code/asky/docs/research_eval.md`
      - added guidance for `(?is)` and lookahead-based regex expectation tuning.

- **Why**:
  - Failures were dominated by strict string matching against otherwise-correct answers (markdown emphasis, casing, reordered phrasing).
  - Pass criteria now better reflect fact correctness instead of exact wording.

### Report Rendering Fixes + Single-File Failure Triage

**Summary**: Fixed markdown report table rendering, added per-tool total call counts, and embedded per-run failure details directly into `report.md`.

- **Changed**:
  - Updated:
    - `/Users/evren/code/asky/src/asky/evals/research_pipeline/evaluator.py`
      - fixed summary table separator row column mismatch that broke markdown rendering.
      - added `## Tool Call Totals` section (aggregated counts by tool type).
      - added `## Case Failure Details` section in `report.md`, sourced from run `results.jsonl`.
      - run execution and `report` regeneration now pass case-result payloads into report builder.
    - `/Users/evren/code/asky/docs/research_eval.md`
      - documented single-file triage behavior in `report.md`.
    - `/Users/evren/code/asky/ARCHITECTURE.md`
      - updated eval artifact/report behavior notes.
  - Added tests:
    - `/Users/evren/code/asky/tests/test_research_eval_evaluator.py`
      - validates tool totals section and case-failure detail rendering.

- **Why**:
  - `report.md` needed to be directly useful without opening extra files.
  - malformed table delimiter prevented reliable markdown rendering in editors.

### Results JSONL Markdown Converter (Auto-Generated)

**Summary**: Added automatic markdown conversion for per-run `results.jsonl` artifacts to make failure triage easy in editors that do not render JSONL well.

- **Changed**:
  - Updated:
    - `/Users/evren/code/asky/src/asky/evals/research_pipeline/evaluator.py`
      - added JSONL reader and markdown converter for case results.
      - new per-run artifact: `artifacts/results.md`.
      - `run_evaluation_matrix` now writes `results.md` immediately after `results.jsonl`.
      - `regenerate_report` now also regenerates each run's `results.md` from stored JSONL.
    - `/Users/evren/code/asky/src/asky/evals/research_pipeline/run.py`
      - terminal run summary now prints per-run `results_markdown` path.
    - `/Users/evren/code/asky/docs/research_eval.md`
      - documented `results.md` artifact and how to use it for fast failure analysis.
    - `/Users/evren/code/asky/ARCHITECTURE.md`
      - updated eval-flow artifact list and markdown-conversion note.
  - Added tests:
    - `/Users/evren/code/asky/tests/test_research_eval_evaluator.py`
      - validates markdown conversion content.
      - validates automatic write during matrix runs.
      - validates regeneration from existing JSONL during `report`.

- **Why**:
  - JSONL is hard to inspect interactively in VS Code.
  - A fail-focused markdown rendering shortens iteration time when adjusting prompts, tools, or expectations.

### Eval Tool-Call Argument Breakdown + Disabled-Tool Comparisons

**Summary**: Added per-run tool-call breakdowns (tool + arguments + count) to summaries/reports and surfaced disabled-tool profile settings so pass-rate impact can be compared directly.

- **Changed**:
  - Updated:
    - `/Users/evren/code/asky/src/asky/core/engine.py`
      - `tool_start` runtime event now includes raw `tool_arguments`.
    - `/Users/evren/code/asky/src/asky/evals/research_pipeline/evaluator.py`
      - per-case results now record `tool_calls` (tool name + parsed args).
      - run summaries now include:
        - `disabled_tools`
        - `tool_call_counts`
        - `tool_call_breakdown` (tool+args signature counts).
      - markdown report now includes:
        - `Disabled Tools` summary column
        - `Tool Call Breakdown` section per run with arguments.
    - `/Users/evren/code/asky/src/asky/evals/research_pipeline/run.py`
      - run summary printout now includes disabled tools and per-tool call counts.
    - `/Users/evren/code/asky/docs/research_eval.md`
      - added explicit `disabled_tools` per-run usage example and breakdown interpretation.
    - `/Users/evren/code/asky/src/asky/core/AGENTS.md`
      - documented `tool_start` event payload extension.
  - Added tests:
    - `/Users/evren/code/asky/tests/test_research_eval_evaluator.py`
      - validates tool-call breakdown aggregation and report rendering.

- **Why**:
  - Needed visibility into exact tool argument patterns and tool-disable experiments to explain pass-rate changes and guide profile tuning.

### Eval Harness End-to-End Timing Instrumentation

**Summary**: Added detailed timing metrics across prepare/run pipeline stages so eval outputs expose where time is spent (ingestion, llm/tool windows, run/session wall time).

- **Changed**:
  - Updated:
    - `/Users/evren/code/asky/src/asky/evals/research_pipeline/evaluator.py`
      - `prepare_dataset_snapshots` now records:
        - manifest-level timing totals (`prepare_total_ms`, downloaded/reused counts)
        - per-document prepare action + elapsed time.
      - per-case `results.jsonl` rows now include `timings_ms`:
        - `case_total_ms`, `source_prepare_ms`, `client_init_ms`, `run_turn_ms`
        - `llm_total_ms`, `tool_total_ms`, `local_ingestion_ms`, `shortlist_ms`
        - call counters for llm/tool/local_ingestion/shortlist.
      - run summaries now include:
        - `timing_totals_ms`
        - `timing_averages_ms`
        - `timing_counts`
        - `run_wall_ms` per run
      - session summary now includes `session_wall_ms` + `runs_wall_ms`.
    - `/Users/evren/code/asky/src/asky/evals/research_pipeline/run.py`
      - `prepare` prints timing totals and per-doc timing lines.
      - `run` prints per-run timing totals and session timing summary.
      - live progress now includes elapsed ms for external transition end events.
    - `/Users/evren/code/asky/docs/research_eval.md`
      - documented timing fields, semantics, and interpretation guidance.
  - Added tests:
    - `/Users/evren/code/asky/tests/test_research_eval_evaluator.py`
      - validates timing aggregation and report headers.

- **Why**:
  - Needed visibility into ingestion/preload/orchestration/model/tool time to tune quality-vs-latency tradeoffs and detect bottlenecks.

### Eval Runner Live External-Invocation Progress

**Summary**: Added real-time progress output during eval execution, including before/after transitions for external invocation phases.

- **Changed**:
  - Updated:
    - `/Users/evren/code/asky/src/asky/evals/research_pipeline/evaluator.py`
      - `_evaluate_case` now emits case-scoped progress events for:
        - `run_turn` start/end/error
        - engine external transitions (`llm_start`, `llm_end`, `tool_start`, `tool_end`)
        - preload and summarizer status callbacks
      - `run_evaluation_matrix` forwards case progress events through the existing run progress callback.
    - `/Users/evren/code/asky/src/asky/evals/research_pipeline/run.py`
      - progress printer now renders external transition/status lines in addition to run/case start/end lines.
    - `/Users/evren/code/asky/docs/research_eval.md`
      - documented live console progress behavior and event coverage.

- **Why**:
  - Long-running real-model eval cases previously looked idle; users needed explicit live feedback while waiting for network/model/tool phases.

### Eval Harness Role-Based Token Usage Metrics

**Summary**: Added model-role token usage reporting to research eval outputs so each run shows `main`, `summarizer`, and `audit_planner` input/output/total counts.

- **Changed**:
  - Updated:
    - `/Users/evren/code/asky/src/asky/evals/research_pipeline/evaluator.py`
      - records per-case `token_usage` in `results.jsonl` with role-level `input_tokens`, `output_tokens`, `total_tokens`.
      - aggregates run-level `token_usage_totals` in `summary.json`.
      - includes token usage columns in `report.md` (`in/out/total` per role).
    - `/Users/evren/code/asky/src/asky/evals/research_pipeline/run.py`
      - prints role token totals per run in terminal output after execution.
  - Added tests:
    - `/Users/evren/code/asky/tests/test_research_eval_evaluator.py`
      - validates default zero token totals, aggregation math, and report token columns.
  - Updated docs:
    - `/Users/evren/code/asky/docs/research_eval.md`
    - `/Users/evren/code/asky/ARCHITECTURE.md`

- **Why**:
  - Makes model-quality vs token-cost comparisons explicit across matrix runs.
  - Gives visibility into token split between primary answer generation and summarization work.

### Notes

- `audit_planner` is a forward-compatible placeholder role in v1; counts remain zero until that stage is integrated.

### Research Eval Documentation Expansion

**Summary**: Rewrote the eval harness guide into an operator-focused manual covering dataset/matrix authoring, expectation tuning, and output interpretation.

- **Changed**:
  - Updated:
    - `/Users/evren/code/asky/docs/research_eval.md`
      - added end-to-end workflow for creating new datasets and matrices
      - documented full dataset and matrix schema references
      - added expectation tuning guidance (`contains` vs `regex`)
      - added practical troubleshooting and interpretation guidance for summary/report/results
      - clarified path resolution, provider behavior, and rerun output directory behavior

- **Why**:
  - Existing documentation was too brief for creating and iterating new evaluations confidently.
  - Needed concrete examples for extending scenarios and tuning strictness without changing code.

### Research Runtime Warning Fixes (Tokenizer Length + Chroma Filter)

**Summary**: Eliminated two noisy/compatibility warnings observed in research eval runs by hardening embedding/chunker tokenization and Chroma metadata filter construction.

- **Changed**:
  - Updated:
    - `src/asky/research/vector_store_chunk_link_ops.py`
      - added strict-compatible Chroma metadata filter builder using `$and` for combined `cache_id` + `embedding_model` constraints.
      - applied it across chunk/link/hybrid Chroma query paths.
    - `src/asky/research/embeddings.py`
      - added pre-encode truncation path that caps embedding input texts to `max_seq_length`.
      - added tokenizer-compat encode/decode helpers and `verbose=False` in tokenizer token-count path.
    - `src/asky/research/chunker.py`
      - suppressed tokenizer length warning noise in token counting/encoding path via `verbose=False` compatible call pattern.
  - Added/updated tests:
    - `tests/test_research_vector_store.py`
      - validates Chroma query uses `$and` metadata filter.
    - `tests/test_research_embeddings.py`
      - validates over-length embedding input is truncated before model encode.
  - Updated package docs:
    - `src/asky/research/AGENTS.md`

- **Why**:
  - Research eval runs emitted:
    - tokenizer warning (`sequence length ... > 256`)
    - Chroma warning (`Expected where to have exactly one operator`)
  - Both were avoidable runtime noise and the Chroma filter warning forced unnecessary SQLite fallback.

### Eval Runtime DB Schema Initialization Fix

**Summary**: Fixed immediate per-case failures in eval runs caused by missing `sessions` table in isolated runtime databases.

- **Changed**:
  - Updated:
    - `src/asky/evals/research_pipeline/evaluator.py`
      - added `_initialize_runtime_storage()` and call it at the start of each isolated run (`run_evaluation_matrix`) before processing test cases.
  - Added regression test:
    - `tests/test_research_eval_evaluator.py`
      - verifies isolated runtime initialization creates the `sessions` table.

- **Why**:
  - Eval runs create isolated DB paths; without explicit schema init, `AskyClient.run_turn()` session resolution hit `OperationalError: no such table: sessions` and every case failed instantly.

### Eval Runner UX + Output Collision Safeguards

**Summary**: Improved eval-runner feedback for fast-failure runs and prevented same-second output directory reuse.

- **Changed**:
  - Updated:
    - `src/asky/evals/research_pipeline/evaluator.py`
      - output directory allocation now guarantees uniqueness (adds `_001`, `_002`, ...) when a timestamp directory already exists.
      - run summary now includes `error_cases` and `halted_cases`.
      - markdown report includes failed/error/halted columns.
    - `src/asky/evals/research_pipeline/run.py`
      - `run` command now prints per-run `passed/failed/errors/halted` counts from session summary.
      - prints a follow-up note when execution errors are present so users know to inspect `results.jsonl`.
  - Added tests:
    - `tests/test_research_eval_evaluator.py`
      - covers output directory collision suffixing and summary error/halt counting.
  - Updated docs:
    - `docs/research_eval.md`
      - documented unique output suffix behavior and terminal summary/error guidance.

- **Why**:
  - Fast execution failures previously looked like a silent early exit because only artifact paths were printed.
  - Same-second reruns could reuse one timestamp folder name, making reruns confusing.

### Eval Matrix Path Policy Refinement

**Summary**: Refined matrix path resolution rules so non-existent bare output paths do not get misinterpreted as matrix-relative.

- **Changed**:
  - Updated:
    - `src/asky/evals/research_pipeline/matrix.py`
      - `./` / `../` prefixes resolve relative to matrix file.
      - bare relative paths resolve from current working directory.
      - absolute paths unchanged.
  - Added test:
    - `tests/test_research_eval_matrix.py`
      - verifies `output_root = "temp/..."` resolves from cwd.
  - Updated docs:
    - `docs/research_eval.md` path-resolution section.

- **Why**:
  - Avoids duplicated path segments for output/snapshot roots when those directories do not already exist.

### Eval Matrix Dataset Path Resolution Fix

**Summary**: Fixed dataset path resolution in eval matrix loading so repo-root relative dataset paths no longer get incorrectly prefixed by the matrix directory.

- **Changed**:
  - Updated:
    - `src/asky/evals/research_pipeline/matrix.py`
      - relative matrix paths now resolve by preferring existing cwd-relative paths, then falling back to matrix-relative paths.
    - `evals/research_pipeline/matrices/default.toml`
      - switched dataset reference to matrix-relative form (`../datasets/...`) for portability.
  - Added regression test:
    - `tests/test_research_eval_matrix.py`
      - covers `dataset = "evals/research_pipeline/datasets/..."` with matrix file under `.../matrices`.
  - Updated docs:
    - `docs/research_eval.md`
      - clarified supported matrix path resolution behavior.

- **Why**:
  - Prevents `FileNotFoundError` caused by combining matrix directory + repo-root relative dataset path.

### Dual-Mode Research Eval Harness (Programmatic API, Manual Integration Runs)

**Summary**: Added a standalone evaluation harness around `AskyClient.run_turn(...)` to run real-model research/non-research integration checks with pinned datasets and model-parameter sweeps.

- **Changed**:
  - Added eval harness package:
    - `src/asky/evals/research_pipeline/run.py` (`prepare` / `run` / `report` commands)
    - `src/asky/evals/research_pipeline/dataset.py` (dataset parsing + validation, `doc_id`/`doc_ids` normalization)
    - `src/asky/evals/research_pipeline/matrix.py` (run-matrix parsing, source-provider resolution)
    - `src/asky/evals/research_pipeline/source_providers.py` (`local_snapshot`, `live_web`, `mock_web` placeholder)
    - `src/asky/evals/research_pipeline/runtime_isolation.py` (per-run DB/Chroma isolation + singleton reset)
    - `src/asky/evals/research_pipeline/assertions.py` (`contains` / `regex` assertions)
    - `src/asky/evals/research_pipeline/evaluator.py` (snapshot prep + run execution + result/report artifact writing)
  - Added seed evaluation data/config:
    - `evals/research_pipeline/datasets/rfc_http_nist_v1.yaml`
    - `evals/research_pipeline/matrices/default.toml`
  - Expanded API config surface for sweeps:
    - `src/asky/api/types.py` added `AskyConfig.model_parameters_override`
    - `src/asky/api/client.py` now deep-copies model config and merges overrides into effective LLM parameters.
  - Added docs:
    - `docs/research_eval.md`
    - updated `docs/library_usage.md`
    - updated `ARCHITECTURE.md`
    - updated `src/asky/api/AGENTS.md`
    - updated `tests/AGENTS.md`
  - Added tests:
    - `tests/test_research_eval_dataset.py`
    - `tests/test_research_eval_assertions.py`
    - `tests/test_research_eval_matrix.py`
    - `tests/test_research_eval_source_providers.py`
    - `tests/test_api_model_parameter_override.py`

- **Why**:
  - Enables repeatable manual evaluation of retrieval/orchestration quality across models and parameter sets.
  - Keeps the harness programmatic and future-ready for mocked/stubbed web-source testing without redesign.

- **Gotchas / Follow-ups**:
  - `mock_web` source provider is intentionally a placeholder in v1; stubbed network mode is deferred.
  - Live web runs can vary due to network/content drift; pinned local snapshots are recommended for stable baselines.

### Library Usage Documentation (API Config + Turn Request Options)

**Summary**: Added dedicated docs for programmatic `asky.api` usage, with explicit configuration/request field mapping and runnable examples.

- **Changed**:
  - Added:
    - `docs/library_usage.md`
      - `AskyConfig` option table (`model_alias`, `research_mode`, `disabled_tools`, etc.)
      - `AskyTurnRequest` option table (`continue_ids`, session fields, preload flags, persistence flag)
      - callback integration docs
      - `AskyTurnResult`/halt semantics
      - error handling (`ContextOverflowError`)
      - end-to-end examples (standard, research/lean, context continuation, sessions)
  - Updated:
    - `README.md` with a clear pointer to the library usage guide.

- **Why**:
  - Makes the new API-first orchestration discoverable and usable without reading source code.
  - Clarifies exactly how configuration and per-turn options should be passed.

- **Tests**:
  - Validation run:
    - `uv run pytest` (full suite)

### Full API Orchestration Migration (Context + Session + Shortlist)

**Summary**: Completed the migration of chat orchestration into `asky.api` so `AskyClient.run_turn()` now provides CLI-equivalent context/session/preload/model/persist flow.

- **Changed**:
  - Added API orchestration services:
    - `src/asky/api/context.py` (history selector parsing + context resolution)
    - `src/asky/api/session.py` (session create/resume/auto/research resolution)
    - `src/asky/api/preload.py` (local ingestion + shortlist preload pipeline)
  - Expanded API contract:
    - `src/asky/api/types.py`
      - added `AskyTurnRequest`, `AskyTurnResult`, and structured resolution payload types.
    - `src/asky/api/client.py`
      - added `run_turn(...)` as the full orchestration entrypoint,
      - integrated context/session/preload orchestration + persistence,
      - preserved callback hooks for CLI/web renderers.
  - Added API package docs:
    - `src/asky/api/AGENTS.md`
  - Refactored CLI into interface adapter:
    - `src/asky/cli/chat.py`
      - now maps argparse/UI callbacks to `AskyClient.run_turn(...)`,
      - keeps terminal rendering, html/email/push behaviors in CLI layer,
      - retains compatibility helper functions for existing tests/import paths.
  - Updated architecture/docs:
    - `ARCHITECTURE.md`
    - `src/asky/cli/AGENTS.md`

- **Tests**:
  - Extended API tests:
    - `tests/test_api_library.py` (new `run_turn` coverage)
  - Updated CLI integration expectation:
    - `tests/test_cli.py` (persistence assertions aligned with API-owned orchestration)
  - Validation runs:
    - `uv run pytest tests/test_cli.py tests/test_api_library.py`
    - `uv run pytest` → 422 passed

- **Why**:
  - Makes full chat orchestration callable as a stable programmatic API.
  - Keeps CLI as presentation/interaction layer over the same API workflow.

- **Gotchas / Follow-ups**:
  - `shortlist_flow.py` remains in `cli/` for now but orchestration path is API-owned.
  - Optional future cleanup: retire legacy helper wrappers in `cli/chat.py` once external imports no longer rely on them.

### Library API Slice + Non-Interactive Context Overflow Handling

**Summary**: Added a first-class programmatic API (`asky.api`) and removed interactive `input()` recovery from the core engine so library/web callers can control error handling safely.

- **Changed**:
  - Added new API package:
    - `src/asky/api/__init__.py`
    - `src/asky/api/types.py` (`AskyConfig`, `AskyChatResult`)
    - `src/asky/api/client.py` (`AskyClient` with message build + registry/engine orchestration)
    - `src/asky/api/exceptions.py` (public exception exports)
  - Added core exceptions module:
    - `src/asky/core/exceptions.py` (`AskyError`, `ContextOverflowError`)
  - Refactored core engine:
    - `src/asky/core/engine.py`
      - removed interactive 400 recovery (`input()` loop),
      - raises `ContextOverflowError` on HTTP 400 with compacted-message payload,
      - removed direct terminal rendering in engine fallback paths,
      - added optional structured `event_callback(name, payload)` hooks,
      - changed verbose tool callback payload to structured dicts.
  - Updated CLI orchestration:
    - `src/asky/cli/chat.py`
      - uses `AskyClient.run_messages(...)` for registry+engine execution,
      - adapts verbose dict payloads back into Rich panels for terminal UX,
      - handles `ContextOverflowError` with user-facing guidance.
  - Updated exports/docs:
    - `src/asky/core/__init__.py`
    - `ARCHITECTURE.md`
    - `src/asky/core/AGENTS.md`
    - `src/asky/cli/AGENTS.md`

- **Tests**:
  - Added `tests/test_api_library.py` for `AskyClient` behavior.
  - Updated `tests/test_context_overflow.py` to assert raised `ContextOverflowError` instead of interactive prompt flow.
  - Validation runs:
    - Pre-change baseline: `uv run pytest` → 416 passed
    - Post-change full suite: `uv run pytest` → 420 passed

- **Why**:
  - Separates core/business orchestration from terminal interaction.
  - Enables safe server/web embedding (no hidden stdin prompt paths).
  - Establishes a stable typed API surface for incremental CLI-to-library migration.

- **Gotchas / Follow-ups**:
  - CLI still owns post-answer delivery UI actions (mail/push/report) and shell-specific terminal context fetch.

### Pre-LLM Local Corpus Preload Stage + PyMuPDF Dependency

**Summary**: Added a deterministic local ingestion stage before first model call in research chat and added `pymupdf` as a project dependency.

- **Changed**:
  - Added new module:
    - `src/asky/cli/local_ingestion_flow.py`
      - extracts local targets from prompt text,
      - ingests/caches local sources via research adapter path,
      - indexes chunk embeddings before model/tool turns,
      - formats a compact preloaded-corpus context block.
  - Updated chat flow:
    - `src/asky/cli/chat.py`
      - runs local preload stage in research mode before shortlist stage,
      - merges local + shortlist contexts into one preloaded-source block.
  - Extended adapter helpers:
    - `src/asky/research/adapters.py`
      - added `extract_local_source_targets(...)` for deterministic prompt token extraction.
  - Added dependency:
    - `pyproject.toml` / `uv.lock`
      - `pymupdf==1.26.7` added via `uv add pymupdf`.

- **Tests**:
  - Added new tests:
    - `tests/test_local_ingestion_flow.py`
  - Extended existing tests:
    - `tests/test_cli.py`
    - `tests/test_research_adapters.py`
  - Validation run:
    - `uv run pytest` → 416 passed.

- **Why**:
  - Shifts more research orchestration into deterministic program flow (small-model-first goal).
  - Ensures local corpus material is indexed and available before model reasoning starts.

### Built-in Local Source Ingestion Fallback (Phase 3 Slice)

**Summary**: Added deterministic local-file ingestion fallback in research adapters so local corpus reads can flow through the existing cache/vector retrieval path without custom adapter tooling.

- **Changed**:
  - `src/asky/research/adapters.py`
    - Added built-in local target handling when no configured custom adapter matches.
    - Supported target forms: `local://...`, `file://...`, absolute/relative local paths.
    - Directory discover mode returns `local://` links for supported files (non-recursive in v1).
    - File read normalization added for text-like formats (`.txt`, `.md`, `.markdown`, `.html`, `.htm`, `.json`, `.csv`).
    - PDF/EPUB read path added via optional PyMuPDF import with explicit dependency error when unavailable.
  - No changes required in research tool orchestration: existing adapter/cache/vector flow consumes this fallback directly.

- **Tests**:
  - `tests/test_research_adapters.py`
    - Added coverage for builtin local text-file reads.
    - Added coverage for builtin directory discovery link generation.
    - Added coverage for PDF dependency-missing error behavior.
  - Validation runs:
    - `uv run pytest tests/test_research_adapters.py tests/test_research_tools.py`
    - `uv run pytest` (full suite)

- **Why**:
  - Moves local research toward deterministic ingestion and away from model-driven browsing behavior.
  - Reuses the same downstream caching/chunking/indexing retrieval pipeline already used for web content.

### Research Mode Now Auto-Starts a Session

**Summary**: Enforced session-backed execution for research mode so session-scoped memory isolation is always effective.

- **Changed**:
  - Added research-session guard in chat flow:
    - `src/asky/cli/chat.py`
      - New `_ensure_research_session(...)` helper.
      - `run_chat()` now auto-creates a session in research mode when no active/resumed session exists.
  - Added tests:
    - `tests/test_cli.py`
      - session creation path when research starts without session
      - no-op path when session already exists
  - Updated docs:
    - `ARCHITECTURE.md`
    - `src/asky/cli/AGENTS.md`
    - `src/asky/research/AGENTS.md`

- **Why**:
  - Session-scoped research memory (`save_finding` / `query_research_memory`) depends on an active `session_id`.
  - Auto-starting research sessions removes a footgun where isolation could silently degrade.

### Session-Scoped Research Memory + Shortlist Budget Defaults

**Summary**: Implemented first research-pipeline slice to scope findings memory by active chat session and increased default pre-LLM shortlist budgets.

- **Changed**:
  - Threaded active session context from chat into research registry construction:
    - `src/asky/cli/chat.py`
    - `src/asky/core/engine.py`
    - `src/asky/core/tool_registry_factory.py`
  - Added session-aware handling in research memory tool executors:
    - `src/asky/research/tools.py`
      - `save_finding` now persists `session_id` when provided.
      - `query_research_memory` now queries semantic/fallback memory in optional session scope.
  - Extended vector-store finding operations for session-filtered retrieval paths:
    - `src/asky/research/vector_store.py`
    - `src/asky/research/vector_store_finding_ops.py`
  - Raised shortlist defaults for larger bounded corpus construction:
    - `src/asky/data/config/research.toml` (`search_result_count=40`, `max_candidates=40`, `max_fetch_urls=20`)
    - `src/asky/config/__init__.py` fallback defaults aligned to `40/40/20`.

- **Tests**:
  - Added/updated coverage:
    - `tests/test_tools.py` (research registry session-id injection behavior)
    - `tests/test_research_tools.py` (session propagation for save/query memory tools)
    - `tests/test_research_vector_store.py` (session-scoped finding search)
  - Validation runs:
    - Pre-change baseline: `uv run pytest` → 402 passed
    - Post-change full suite: `uv run pytest` → 406 passed

- **Why**:
  - Keeps research-memory writes/reads isolated by active session without relying on the model to manage scope.
  - Increases shortlist breadth while keeping fetch/index work bounded for deterministic pipeline stages.

### Documentation Sync for Session-Scoped Memory + Shortlist Budgets

**Summary**: Updated architecture/package docs to reflect new research-memory scoping behavior and shortlist defaults.

- **Updated**:
  - `ARCHITECTURE.md`
  - `src/asky/cli/AGENTS.md`
  - `src/asky/core/AGENTS.md`
  - `src/asky/research/AGENTS.md`
  - `src/asky/config/AGENTS.md`

### Research Pipeline Plan Revisions (Decisions Applied)

**Summary**: Updated the research pipeline planning artifact with concrete defaults and decisions from review discussion.

- **Updated**:
  - `TODO_research_pipeline.md` now locks `session_id` as run isolation key.
  - Local ingestion milestone scope now explicitly includes EPUB support through the PyMuPDF path.
  - Model-role plan now supports a single shared optional `analysis_model` for both planning and audit stages.
  - Web corpus defaults now set to `40` candidates and `20` fetched/indexed sources (configurable).

- **Why**:
  - Converts ambiguous planning choices into implementable defaults so the first build phase can proceed without re-litigating core assumptions.

- **Gotchas / Follow-ups**:
  - Two clarifications remain in TODO: `analysis_model` default enablement and initial local ingestion UX scope (explicit files only vs directory recursion in v1).

### Research Pipeline Revamp Planning Artifact

**Summary**: Added a dedicated multi-session TODO plan for a pipeline-driven, small-model-first research workflow redesign.

- **Added**:
  - New planning document: `TODO_research_pipeline.md`
  - Phased roadmap covering orchestration stages, local/web corpus unification, retrieval-first targeted summarization, model-role split (worker/planner/auditor), and rollout gates.

- **Why**:
  - Current research behavior depends too much on model initiative for tool use.
  - Goal is to move orchestration and data flow into deterministic program logic so smaller/local models produce more consistent results.

- **Gotchas / Follow-ups**:
  - Implementation intentionally not started yet; this entry tracks planning output only.
  - Open architecture decisions are listed in `TODO_research_pipeline.md` and need confirmation before coding starts.

### Tool Metadata Prompt Guidance + Runtime Tool Exclusion Flags

**Summary**: Added per-tool prompt-guideline metadata and runtime tool exclusion flags so enabled tools can shape system prompt behavior and selected tools can be disabled from CLI invocation.

- **Refactors / Features**:
  - Extended `ToolRegistry` to store optional `system_prompt_guideline` metadata and expose enabled-tool guideline lines in registration order.
  - Updated `ToolRegistry.get_schemas()` to emit API-safe function schemas (`name`, `description`, `parameters`) while keeping internal metadata out of tool payloads.
  - Added `disabled_tools` support to `create_default_tool_registry()` and `create_research_tool_registry()` (including built-in, research, custom, and push-data tools).
  - Added CLI flags `-off`, `-tool-off`, and `--tool-off` (repeatable and comma-separated values supported).
  - Updated chat flow to parse runtime tool exclusions, build the filtered registry, and append enabled-tool guideline bullets into the system prompt before LLM execution.
  - Added `system_prompt_guideline` fields to research tool schemas and built-in registry schemas; custom tools now support the same optional field from config.
  - Updated `ConversationEngine.run()` to disable tool-calling automatically when the registry has no enabled tools.

- **Tests**:
  - Extended `tests/test_cli.py` with parser and helper coverage for tool-off alias parsing, disabled-tool normalization, and system-prompt guideline block injection.
  - Extended `tests/test_tools.py` with coverage for API schema sanitization and registry filtering/guideline behavior.

- **Why**:
  - Makes tool behavior instructions composable and tied to enabled toolset rather than hardcoded prompt text.
  - Supports quick per-run tool toggling from command line without editing config.

- **Gotchas / Follow-ups**:
  - Tool names in `--tool-off` are exact string matches against registered names.
  - If all tools are disabled, the LLM call now runs tool-free automatically.

### Summarization Latency + Non-Streaming LLM Requests

**Summary**: Reduced hierarchical summarization call count and forced non-streaming mode for all LLM requests.

- **Refactors**:
  - Updated `src/asky/summarization.py` to use bounded `map + single final reduce` for long content instead of recursive pairwise merge rounds.
  - Added reduce-input sizing helpers so final reduce input stays within `SUMMARIZATION_INPUT_LIMIT`.
  - Updated `src/asky/core/api_client.py` so every LLM payload explicitly sets `stream = false`, even if model parameters include `stream`.

- **Tests**:
  - Extended `tests/test_summarization.py` with a regression test that verifies hierarchical mode now performs `N map calls + 1 final reduce call`.
  - Extended `tests/test_model_params.py` to verify streaming is always disabled in outbound LLM payloads.

- **Why**:
  - Hierarchical summarization was creating too many round trips on long inputs.
  - Streaming responses are not consumed in current CLI/chat flow, so enabling them adds overhead without product value.

### Gotchas / Follow-ups

- If a future UI path consumes token streams incrementally, `get_llm_msg()` will need an explicit opt-in streaming mode rather than global `stream=false`.

### Maintainability Refactor (Phase 1-2)

**Summary**: Reduced duplication around URL handling and lazy imports, and extracted pre-LLM shortlist orchestration from `chat.py` to a dedicated helper module.

- **New Modules**:
  - Added `src/asky/url_utils.py` for shared URL sanitization and normalization.
  - Added `src/asky/lazy_imports.py` for shared lazy import/call helpers.
  - Added `src/asky/cli/shortlist_flow.py` to run shortlist stage and banner updates outside `run_chat()`.

- **Refactors**:
  - Updated `retrieval.py`, `tools.py`, `research/tools.py`, and `research/source_shortlist.py` to reuse shared URL helpers.
  - Updated `core/engine.py` lazy tool and research binding imports to use shared lazy-import utilities.
  - Slimmed `cli/chat.py` by extracting shortlist execution orchestration while preserving existing public helper functions and test patch points.

- **Why**:
  - Removes repeated URL sanitization/normalization implementations.
  - Makes lazy-loading patterns consistent and easier to maintain.
  - Reduces `run_chat()` complexity and isolates shortlist-side effects (banner/status/verbose output) in one place.

- **Gotchas / Follow-ups**:
  - `source_shortlist.py`, `vector_store.py`, and `sqlite.py` remain large; deeper module splits are still pending.
  - Config constants are still flat in `config/__init__.py`; grouping into structured settings is a later phase.

### Maintainability Refactor (Phase 3)

**Summary**: Extracted tool registry construction out of `core/engine.py` into `core/tool_registry_factory.py`, while preserving backwards compatibility for test patch points and public APIs.

- **New Module**:
  - Added `src/asky/core/tool_registry_factory.py` to own `create_default_tool_registry()` and `create_research_tool_registry()`.

- **Refactors**:
  - Replaced large in-module registry builders in `core/engine.py` with thin delegating wrappers.
  - Kept `engine.py` compatibility symbols (`execute_get_url_content`, `execute_web_search`, etc.) so existing tests and patch targets continue to work.
  - Updated core architecture docs (`ARCHITECTURE.md`, `src/asky/core/AGENTS.md`) to reflect the new module boundary.

- **Why**:
  - Reduces `engine.py` scope to conversation orchestration and summary logic.
  - Isolates registry/tool assembly for easier future extraction (e.g., custom/push-data/research registration).

### Maintainability Refactor (Phase 4)

**Summary**: Split shortlist internals into focused modules while keeping `source_shortlist.py` as the stable public API surface.

- **New Modules**:
  - Added `src/asky/research/shortlist_types.py` for shared shortlist datatypes and callback aliases.
  - Added `src/asky/research/shortlist_collect.py` for candidate collection + seed-link expansion.
  - Added `src/asky/research/shortlist_score.py` for scoring, ranking heuristics, and query fallback resolution.

- **Refactors**:
  - `source_shortlist.py` now delegates collection and scoring to dedicated modules.
  - Kept existing imports/functions in `source_shortlist.py` so tests and callers remain unchanged.

- **Why**:
  - Reduces single-module cognitive load and makes pipeline stages independently maintainable.
  - Creates clearer boundaries for future changes (collection vs scoring).

### Maintainability Refactor (Phase 5)

**Summary**: Split heavy `VectorStore` internals into dedicated operation modules and kept `vector_store.py` focused on lifecycle + compatibility wrappers.

- **New Modules**:
  - Added `src/asky/research/vector_store_common.py` for shared vector math/constants.
  - Added `src/asky/research/vector_store_chunk_link_ops.py` for chunk/link embedding and retrieval operations.
  - Added `src/asky/research/vector_store_finding_ops.py` for findings-memory embedding/search operations.

- **Refactors**:
  - Rewrote `vector_store.py` to delegate heavy method bodies to ops modules.
  - Preserved existing `VectorStore` method names and behavior for compatibility with current tests/callers.

- **Why**:
  - Shrinks the core class file and isolates distinct operational concerns.
  - Makes future work on chunk/link retrieval independent from findings-memory logic.

## 2026-02-08

### Codebase Documentation Restructuring

**Summary**: Restructured documentation by creating package-level `AGENTS.md` files, slimming `ARCHITECTURE.md`, and generating a maintainability report.

- **New Files**: Created `AGENTS.md` in `cli`, `core`, `storage`, `research`, `config`, and `tests` directories.
- **Refactor**: Reduced `ARCHITECTURE.md` to a high-level overview (~220 lines).
- **Report**: Analyzed maintainability (file sizes, config sprawl, duplication, testing gaps).

### CLI & UX Improvements

**Argcomplete & Selectors**:

- Added `argcomplete`-backed shell completion with dynamic value hints.
- implemented word-based selector tokens for `--continue-chat`, `--print-session`, `--resume-session`, `--print-answer`, and `--session-from-message`.
- Renamed `--from-message` to `--session-from-message` (`-sfm`).
- Selectors now support "word-based" matching for easier recall.
- Added `--completion-script` for easy shell setup.

**Session Features**:

- **Message to Session**: `-sfm <ID>` promotes a history message to a new session.
- **Quick Reply**: `--reply` shortcut to continue from the last message (resuming session or converting if needed).

**Banner & Observability**:

- **Live Progress**: Banner now shows pre-LLM retrieval progress (shortlist stats) before the model call.
- **Stability**: Fixed banner redraw issues caused by embedding model load noise (loading bars, warnings).
- **Verbose Trace**: Added rich terminal tables for shortlist candidates and tool calls in `-v` mode.
- **Summarization**: Added live banner updates for hierarchical summarization progress.

### Performance & Startup

**Optimization**:

- **Lazy Imports**: Made core package exports lazy (`asky.cli`, `asky.core`, `asky.research`) to reduce startup time.
- **Startup Slimming**: Reordered `main()` to short-circuit fast commands (help, edit-model) before DB init.
- **Background Cleanup**: Moved research cache cleanup to a background thread to unblock startup.

**Guardrails**:

- Added `tests/test_startup_performance.py` to enforce latency (<0.2s median) and idle RSS memory usage limits.

### Research & Retrieval Enhancements

**Shared Pipeline**:

- Unified URL retrieval logic in `retrieval.py` for standard tools, research mode, and shortlist.
- Implemented **Hierarchical Summarization** (map-reduce) for long content.

**Source Shortlist**:

- **Shared Pipeline**: Added a pre-LLM shortlist pipeline (URL parsing, extraction, ranking) shared by research/chat modes.
- **Models**: Added per-model control (`source_shortlist_enabled` in config) and runtime override (`--lean`).
- **Seed-Link Expansion**: Added support for expanding links from seed URLs in the prompt.
- **Hardening**: Improved filtering of utility/auth links and canonical deduplication.
- **Debug**: Added extensive performance logging for the shortlist path.

**Embeddings**:

- **Cache-First**: Application now prefers local cache and only hits HuggingFace if needed.
- **Fallback**: Added auto-download of fallback model (`all-MiniLM-L6-v2`) if configured model fails.
- **Fixes**: Fixed tokenizer max-length warnings and added noise suppression during load.

### Reliability & Testing

**Fixes**:

- **Graceful Exit**: Refactored max-turns exit to use a tool-free system prompt swap, preventing hallucinated XML calls.
- **Tests**: Fixed slow CLI tests (mocking cleanup/logging), fixed import errors in prompt tests, and resolved various failures.
- **XML Support**: Added support for parsing XML-style tool calls.

### 2026-02-21: Fixed Identical Tracker Display Bug in Banner

- **What**: Fixed a bug where the `BannerState` class incorrectly displayed the main model's token usage for the summarization model when both models shared the same alias (e.g., both configured as "step35").
- **Why**: The UI logic in `banner.py` looked up token usage in a shared dictionary (`token_usage`) using the exact model aliases. When both aliases were identical, `dictionary.get("step35")` fetched the usage of the main model for both lines in the banner, ignoring any suffix hacks or actual summarizer usage.
- **How**:
  - Reverted the dictionary suffix hack in `src/asky/cli/display.py` (`_get_combined_token_usage`).
  - Changed `BannerState` to explicitly accept `main_token_usage` and `sum_token_usage` as separate dictionaries.
  - Updated `get_token_str` in `banner.py` to use a new `is_summary=True` flag to target the correct dictionary.
  - Updated `test_banner_compact.py` and `test_display_token_usage.py` to test the new clean architecture.
- **Round 2 token UI bug**: The banner UI was freezing on 0 summarization tokens because the live display (`renderer.live.stop()`) was stopped _immediately_ after the synchronous background compaction finished. At the start of the compaction, the tokens were 0, and since `update_banner` was never called again _after_ the heavy LLM summarization completed, the final visual state remained frozen at 0 tokens despite the `UsageTracker` being correctly populated.
- **Fix**: Added a final `renderer.update_banner(renderer.current_turn, status_message=None)` call to the `finally` block in `asky/cli/chat.py` just before `renderer.stop_live()`. This guarantees the final token metrics are pulled from the trackers and rendered onto the screen before the process exits.
