For older logs, see [DEVLOG_ARCHIVE.md](DEVLOG_ARCHIVE.md)

## 2026-02-09

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
