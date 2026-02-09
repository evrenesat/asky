For older logs, see [DEVLOG_ARCHIVE.md](DEVLOG_ARCHIVE.md)

## 2026-02-09

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
