## 2026-02-08 - Final Warning Refactor & Import Fix

**Summary**: Refactored the "graceful exit" mechanism to prevent models from generating imaginary XML tool calls when max turns are reached. Fixed a major `ImportError` where `construct_research_system_prompt` was incorrectly named.

**Changes**:
- **Core Engine** (`src/asky/core/engine.py`):
  - Extracted graceful exit logic into `_execute_graceful_exit` helper method.
  - Implemented **system prompt replacement**: the original tool-mentioning system prompt is now swapped for a clean, tool-free version (`GRACEFUL_EXIT_SYSTEM`) during the final turn.
- **Configuration** (`prompts.toml`, `config/__init__.py`):
  - Added new `graceful_exit` prompt template.
  - Exported `GRACEFUL_EXIT_SYSTEM` constant.
- **Bug Fix** (`src/asky/core/prompts.py`):
  - Renamed `construct_ch_system_prompt` back to `construct_research_system_prompt` to match usages in `chat.py` and `__init__.py`, fixing a critical `ImportError`.
- **Testing**:
  - Updated `tests/test_llm.py`:
    - Adjusted `test_run_conversation_loop_max_turns_graceful_exit` to match new message structure.
    - Added `test_graceful_exit_replaces_system_prompt` to verify the tool-free prompt swap.

**Verification**:
- Fixed `ImportError` preventing test collection.
- Ran focused suite: `pytest tests/test_llm.py`
- Result: `17 passed` (including new and updated graceful exit tests).
- All tool calls avoided in final turn as verified by mocks.

## 2026-02-07 - Shared Pre-LLM Source Shortlisting Pipeline

**Summary**: Added a shared pre-LLM source shortlisting pipeline that extracts prompt URLs, optionally performs web search, fetches/extracts page content, and ranks candidates before the first model call.

**Changes**:
- **New shared module** (`src/asky/research/source_shortlist.py`):
  - Added prompt parsing for seed URL extraction and URL-stripped query text.
  - Added URL normalization/deduplication (fragment removal, default-port cleanup, tracking param stripping, query sorting).
  - Added optional YAKE keyphrase extraction for long prompts with token-based fallback when YAKE is unavailable.
  - Added candidate collection from prompt URLs and optional `web_search` results.
  - Added content extraction pipeline:
    - Primary: `trafilatura` main-text extraction.
    - Fallback: `requests` + `HTMLStripper`.
  - Added relevance scoring:
    - Semantic similarity via existing sentence-transformers embedding client.
    - Heuristic bonuses/penalties (keyphrase overlap, same-domain bonus, short/noisy page penalties).
  - Added formatted shortlist context generation for prompt injection.
- **Chat integration** (`src/asky/cli/chat.py`):
  - `run_chat` now builds a pre-LLM shortlist payload and injects compact ranked context into the user message when enabled for the active mode.
  - `build_messages` now accepts optional `source_shortlist_context`.
- **Config additions**:
  - Added `[research.source_shortlist]` section to `src/asky/data/config/research.toml`.
  - Exported `SOURCE_SHORTLIST_*` settings in `src/asky/config/__init__.py`.
  - Current defaults: enabled in research mode, disabled in standard mode (can be enabled via config).
- **Dependencies** (`pyproject.toml`, `uv.lock`):
  - Added `trafilatura>=1.12.2`
  - Added `yake>=0.6.0`
- **Tests**:
  - Added `tests/test_source_shortlist.py` (URL parsing/normalization, ranking flow, seed-only behavior, context formatting).
  - Added `test_build_messages_with_source_shortlist_context` in `tests/test_cli.py`.

**Verification**:
- Focused suite:
  - `uv run pytest tests/test_source_shortlist.py tests/test_cli.py`
  - Result: `39 passed`
- Full suite:
  - `uv run pytest tests`
  - Result: `347 passed`

**Gotchas / Follow-up**:
- `trafilatura`/`yake` are optional at runtime in code paths; if unavailable, shortlist flow degrades to fallback extraction and simple keyphrase behavior.
- Non-research mode shortlisting is currently off by default (`research.source_shortlist.enable_standard_mode = false`) to keep rollout controlled.

## 2026-02-07 - Sentence-Transformers Memory Embeddings (all-MiniLM-L6-v2)

**Summary**: Replaced research embedding generation with an in-memory `sentence-transformers` backend (`all-MiniLM-L6-v2` by default), and updated chunking to use tokenizer-aware sentence windows with legacy char fallback.

**Changes**:
- **Embedding Backend Migration** (`src/asky/research/embeddings.py`):
  - Replaced the LM Studio/OpenAI-compatible HTTP embedding client with a local `SentenceTransformer` backend.
  - Added lazy model loading so the singleton client can be created without immediately loading torch/model weights.
  - Preserved existing client contract (`embed`, `embed_single`, `get_usage_stats`, serialization helpers) for compatibility with vector store, tools, and banner rendering.
  - Kept compatibility constructor arguments (`api_url`, `timeout`, retry fields) as no-ops to avoid breakage in existing call sites/tests.
- **Chunking Update** (`src/asky/research/chunker.py`):
  - `chunk_text` now prefers token-aware sentence chunking using the active embedding tokenizer.
  - Effective chunk size is clamped by embedding model max sequence length when available.
  - Added robust fallback to prior character-overlap chunking when tokenizer/model is unavailable.
  - Added long-sentence token window splitting with overlap for cases that exceed the target token budget.
- **Config Defaults and Schema**:
  - `src/asky/config/__init__.py`:
    - Updated research defaults to token-oriented chunk sizing (`chunk_size=256`, `chunk_overlap=48`).
    - Replaced API embedding settings exports with sentence-transformer settings:
      - `research.embedding.model`
      - `research.embedding.batch_size`
      - `research.embedding.device`
      - `research.embedding.normalize`
      - `research.embedding.local_files_only`
  - `src/asky/data/config/research.toml`:
    - Updated comments and defaults for token-based chunking + local embedding model config.
- **Vector Store Safety Fix** (`src/asky/research/vector_store.py`):
  - Added a guard to `search_findings` that returns early when SQLite has no finding embeddings for the current model.
  - This prevents stale Chroma-only hits from leaking into memory search when no persisted embeddings exist locally.
- **Dependencies**:
  - Added `sentence-transformers>=3.0.0` to `pyproject.toml`.
- **Tests**:
  - Reworked `tests/test_research_embeddings.py` to validate sentence-transformers behavior using mocked local model objects.
  - Reworked `tests/test_banner_embedding.py` to validate usage counters and banner integration without HTTP embedding mocks.
  - Updated `tests/test_research_chunker.py`:
    - Existing coverage still validates char fallback path.
    - Added token-aware chunking tests (model max-length clamping and long-sentence overlap behavior).

**Verification**:
- Baseline before changes: `uv run pytest tests` had 1 pre-existing failure in `tests/test_research_vector_store.py::test_search_findings_no_embeddings`.
- Focused suite:
  - `uv run pytest tests/test_research_embeddings.py tests/test_research_chunker.py tests/test_banner_embedding.py tests/test_research_vector_store.py`
  - Result: `89 passed`
- Full suite:
  - `uv run pytest tests`
  - Result: `340 passed`

**Gotchas / Follow-up**:
- `sentence-transformers` model loading requires local model availability or network/model cache unless `local_files_only = true`.
- Token-aware chunking uses tokenizer boundaries when possible, but automatically degrades to char-based chunking if the embedding backend is unavailable.

## 2026-02-07 - Research RAG Migration to ChromaDB Backend

**Summary**: Replaced the research-mode vector retrieval path with a ChromaDB-backed dense retrieval layer while preserving existing research tool interfaces and adding graceful SQLite fallback when Chroma is unavailable.

**Changes**:
- **Vector Store Migration** (`src/asky/research/vector_store.py`):
  - Refactored `VectorStore` to use Chroma collections for:
    - Content chunk embeddings
    - Link embeddings
    - Research finding embeddings
  - Kept existing method contracts (`store_*`, `search_*`, `rank_*`, `has_*`) so `research/tools.py` required no API-level change.
  - Implemented deterministic Chroma IDs per entity (`chunk:{cache_id}:{chunk_index}`, `link:{cache_id}:{url}`, `finding:{id}`).
  - Added runtime fallback to SQLite-only cosine search when Chroma import/client setup is unavailable.
  - Preserved hybrid retrieval behavior by combining:
    - Dense relevance from Chroma nearest-neighbor results
    - Lexical relevance from SQLite BM25 (FTS5) / token overlap fallback
- **Cache Invalidation** (`src/asky/research/cache.py`):
  - Extended stale-vector invalidation and expired-cache cleanup to also clear Chroma vectors (`clear_cache_embeddings`, bulk variant).
  - Cleanup is best-effort and non-fatal; failures are debug-logged to avoid interrupting cache writes.
- **Configuration**:
  - Added Chroma config exports in `src/asky/config/__init__.py`:
    - `RESEARCH_CHROMA_PERSIST_DIRECTORY`
    - `RESEARCH_CHROMA_CHUNKS_COLLECTION`
    - `RESEARCH_CHROMA_LINKS_COLLECTION`
    - `RESEARCH_CHROMA_FINDINGS_COLLECTION`
  - Added `[research.chromadb]` section in `src/asky/data/config/research.toml` for persist directory and collection names.
- **Tests**:
  - Updated `tests/test_research_vector_store.py` with Chroma-path coverage:
    - Chunk upsert writes to Chroma collection
    - Query path prefers Chroma results before SQLite fallback
  - Updated `tests/test_research_cache.py` to verify Chroma cleanup hooks are invoked on:
    - Content-change invalidation
    - Link-change invalidation
    - Expired-entry cleanup

**Verification**:
- Focused research suite:
  - `.venv/bin/pytest tests/test_research_vector_store.py tests/test_research_tools.py tests/test_research_cache.py tests/test_research_embeddings.py tests/test_research_chunker.py tests/test_research_adapters.py`
  - Result: `154 passed`
- Full project tests:
  - `.venv/bin/pytest tests`
  - Result: `341 passed`

**Gotchas / Follow-up**:
- Chroma is currently runtime-optional in code; if not installed, research mode falls back to SQLite dense scan.
- To enforce a hard Chroma dependency, add `chromadb` to `pyproject.toml` dependencies after confirming dependency-policy preference.

## 2026-02-07 - Modular Research Prompts

**Summary**: Enabled modular system prompt construction for Research Mode, allowing users to define `system_prefix`, `force_search`, and `system_suffix` in `research.toml` to override or supplement the default research prompt.

**Changes**:
- **Configuration** (`src/asky/config/__init__.py`):
    - Exported `RESEARCH_SYSTEM_PREFIX`, `RESEARCH_SYSTEM_SUFFIX`, and `RESEARCH_FORCE_SEARCH` from the `research` config section.
- **Core** (`src/asky/core/prompts.py`):
    - Implemented `construct_research_system_prompt` to build the prompt dynamically from components if available.
    - Added `{CURRENT_DATE}` injection support to the `system_prefix`.
- **CLI** (`src/asky/cli/chat.py`):
    - Refactored research prompt construction to use the centralized core function.
- **Verification**:
    - Added `temp/verify_prompts.py` to validate both modular and monolithic fallback scenarios.

**Impact**: Users can now customize specific parts of the research behavior (like forcing web search) directly in `research.toml` without losing the benefits of dynamic date injection.

---

## 2026-02-07 - XML Tool Call Support

**Summary**: Added support for parsing XML-style tool calls (e.g., `<tool_call>...`) to handle models that deviate from standard JSON output.

**Changes**:
- **Prompts** (`src/asky/core/prompts.py`):
  - Implemented `parse_xml_tool_calls` to detect and parse `<tool_call>` blocks with `<function=NAME>` and `<parameter=KEY> VALUE` tags.
  - Updated `extract_calls` to attempt XML parsing before fallback to textual format.
- **Testing**:
  - Added `tests/test_xml_tool_parsing.py` with unit tests for various XML patterns.
  - Verified with manual script `temp_reproduce_xml_parsing.py`.

**Verification**:
- Manual verification script passed (exit code 0).

---

## 2026-02-07 - Smart Archive Filename Extraction

**Summary**: Improved archive file naming by prompting models to use H1 markdown headers and automatically extracting titles for filenames.

**Changes**:
- **Prompts** (`prompts.toml`): Added instruction for models to start responses with an H1 header as a concise title (3-7 words).
- **Rendering** (`rendering.py`):
  - Added `H1_PATTERN` regex and `extract_markdown_title()` function to extract H1 headers from markdown.
  - Modified `_save_to_archive()` to accept original markdown content and extract titles when no explicit `filename_hint` is provided.
  - Updated `render_to_browser()` and `save_html_report()` to pass markdown content for title extraction.
- **Tests**: Updated `test_html_report.py` and `test_llm.py` to reflect new behavior:
  - Added `test_extract_markdown_title` with edge cases.
  - Added `test_save_html_report_no_hint_no_h1` for fallback behavior.
  - Updated existing mocks to match new function signature.

**Impact**: Archive files now have descriptive names like `python_data_types_explained_20260207_003800.html` instead of `untitled_20260207_003800.html`.

**Verification**:
- All 330 tests passed.

---



**Summary**: Upgraded research-mode retrieval to be more reliable and higher quality by fixing chunk overlap behavior, invalidating stale vectors on cache updates, introducing hybrid dense+BM25 ranking with diversity filtering, and hardening embedding API calls with retry/backoff.

**Changes**:
- **Chunking** (`src/asky/research/chunker.py`):
  - Fixed overlap progression logic so configured overlap is preserved deterministically and cannot collapse due a faulty loop guard.
  - Added explicit constants for sentence-boundary search window and lookahead.
- **Cache Freshness** (`src/asky/research/cache.py`):
  - Added schema migration support for `link_embeddings.embedding_model`.
  - Added stale-vector invalidation when cached content or link lists change (`content_chunks` / `link_embeddings` cleanup by `cache_id`).
- **Vector Store** (`src/asky/research/vector_store.py`):
  - Added model-aware freshness checks:
    - `has_chunk_embeddings_for_model(...)`
    - `has_link_embeddings_for_model(...)`
  - Added `search_chunks_hybrid(...)` for combined semantic (cosine) + BM25 lexical ranking via SQLite FTS5.
  - Improved storage behavior by clearing old rows before re-indexing chunks/links to avoid stale leftovers.
- **Research Tools** (`src/asky/research/tools.py`):
  - Replaced non-deterministic URL dedupe (`set`) with order-preserving dedupe.
  - `get_relevant_content` now supports optional `dense_weight` and `min_relevance`.
  - Added chunk diversity filtering to reduce near-duplicate snippets.
  - Added compatibility fallbacks so tools still work with stores that only implement legacy dense search methods.
- **Embedding Client** (`src/asky/research/embeddings.py`, `src/asky/config/__init__.py`, `src/asky/data/config/research.toml`):
  - Added bounded retry/backoff for transient embedding API failures.
  - Switched embedding requests to a persistent session.
  - Added new config fields:
    - `research.embedding.retry_attempts`
    - `research.embedding.retry_backoff_seconds`
- **Tests**:
  - Added/updated tests in:
    - `tests/test_research_chunker.py`
    - `tests/test_research_cache.py`
    - `tests/test_research_vector_store.py`
    - `tests/test_research_embeddings.py`
    - `tests/test_research_tools.py`
  - New coverage includes overlap determinism, cache-driven vector invalidation, model-aware freshness checks, retry behavior, and URL order preservation.

**Verification**:
- Focused research suite:
  - `HOME=/tmp/asky-test-home uv run pytest tests/test_research_chunker.py tests/test_research_embeddings.py tests/test_research_vector_store.py tests/test_research_tools.py tests/test_research_cache.py`
  - Result: `148 passed`
- Full project tests (excluding scratch instability from `temp/` by using the committed suite path):
  - `HOME=/tmp/asky-test-home uv run pytest tests`
  - Result: `327 passed`

**Gotchas / Follow-up**:
- FTS5 support depends on the SQLite build; code falls back to token-overlap lexical scoring if FTS5 is unavailable.
- Existing scratch tests under `temp/` may still affect `uv run pytest` if they are intentionally left failing.

## 2026-02-06 - Fixed Session Count Crash

**Summary**: Fixed an `AttributeError` crash when starting the CLI or viewing sessions, caused by a missing `count_sessions` method in the `SQLiteHistoryRepository`.

**Changes**:
- **Storage**: Added `count_sessions` method to `HistoryRepository` ABC in `src/asky/storage/interface.py`.
- **Implementation**: Implemented `count_sessions` in `src/asky/storage/sqlite.py` to return the count of rows in the `sessions` table.
- **Testing**: Added `test_count_sessions` regression test to `tests/test_sessions.py`.

**Verification**:
- Verified with reproduction script `temp_reproduce_crash.py`.
- Ran full test suite: 346 tests passed. (Note: One unrelated failure in `temp/test_visual_indicators.py` observed).

---

## 2026-02-06 - Refactoring File Generation and Session Utils

**Summary**: Refactored the HTML file generation mechanism to save files in a persistent archive directory (`~/.config/asky/archive`) with meaningful, timestamped names. Also extracted session slug generation logic into a reusable utility module.

**Changes**:
- **Core**: created `src/asky/core/utils.py` and moved `STOPWORDS` and `generate_slug` (renamed from `generate_session_name`) there.
- **Rendering**: updated `src/asky/rendering.py` to use `ARCHIVE_DIR` and `generate_slug`. Added `save_html_report` logic to generate filenames like `slug_YYYYMMDD_HHMMSS.html`.
- **Config**: added `ARCHIVE_DIR` to `src/asky/config/__init__.py`.
- **CLI**: updated `sessions.py`, `history.py`, and `engine.py` to pass context-aware `filename_hint`s (e.g., session name, answer preview) to the rendering function.
- **Testing**: updated `tests/test_html_report.py` and `tests/test_llm.py` to verify the new archiving behavior and mocking strategies.

**Verification**:
- Verified that `asky ... --open` generates correctly named files in `~/.config/asky/archive/`.
- Verified that session and history viewing works with the new system.
- All tests passed.

---

## 2026-02-06 - Terminal Context Status in Banner

**Summary**: Moved the "Fetching last N lines..." message from stdout to the CLI banner status line using a callback mechanism. This improves the UI by keeping the history clean and preventing status messages from cluttering the scrollback.

**Changes**:
- **UI**: Added `status_callback` to `inject_terminal_context` in `src/asky/cli/terminal.py`.
- **Integration**: Updated `src/asky/cli/chat.py` to:
  - Initialize `InterfaceRenderer` earlier in the startup flow.
  - Start the live banner before fetching terminal context.
  - Pass a lambda callback that updates the banner status message instead of printing.
- **Testing**: Added `test_main_terminal_lines_callback` to `tests/test_cli.py` to verify the callback invocation.

**Verification**:
- Verified that `asky -tl 5` updates the banner status line and does not print to stdout.
- Ran full test suite, all tests passed.

---

## 2026-02-06 - Terminal Context Fix

**Summary**: Fixed a bug where terminal context was being fetched and appended unconditionally because of the default configuration value, even when the `-tl` flag was not provided.

**Changes**:
- **Logic Fix**: Updated `src/asky/cli/chat.py` to ensure terminal context is only fetched when `args.terminal_lines` is explicitly provided (either with a value or as a flag using the default from config).
- **Default Behavior**: If the flag is missing, `lines_count` now defaults to 0, effectively disabling the feature unless opted-in.
- **Testing**:
  - Updated `tests/test_cli.py` to explicitly request terminal lines in verbose flow tests.
  - Added new test case `test_main_flow_default_no_context` to verify that no context is injected by default.

**Verification**:
- Ran full test suite (`uv run pytest`), all 31 tests in `test_cli.py` passed (and others).

---

## 2026-02-06 - Compact Two-Line Banner

**Summary**: Introduced an optional "compact banner" mode that reduces the CLI header to two lines using unicode icons and emojis, suitable for smaller screens or power users who prefer minimal UI.

**Changes**:
- **Config**: Added `compact_banner` (default: `false`) to `[general]` section in `config.toml` (and `loader.py` defaults).
- **UI**: Added `get_compact_banner` in `banner.py` which renders:
  - Line 1: Models & Token Usage (🤖, 📝)
  - Line 2: Tools, Turns, Research Stats, DB Count, Session Name (🛠️, 🔄, 🧠, 💾, 🗂️)
- **Integration**: Updated `InterfaceRenderer` in `display.py` to respect the configuration.
- **Testing**: Added `tests/test_banner_compact.py` to verify rendering logic and emoji presence.

**Verification**:
- Verified `get_compact_banner` produces expected string output via new unit tests.
- Full test suite passed (314 tests).

---

**Summary**: Added optional feature to include the last N lines of terminal output as context for queries, enabling "asky -tl why is this error happening?" workflows.

**Changes**:
- **Core**: Added `src/asky/cli/terminal.py` to fetch context using `iterm2` library.
- **Config**: Added `terminal_context_lines` to `config.toml` (default 0) and `[project.optional-dependencies]` in `pyproject.toml`.
- **CLI**: Added `-tl / --terminal-lines` flag to `main.py`.
- **Integration**: Updated `chat.py` to use `inject_terminal_context` helper, keeping the chat loop clean.
- **Docs**: Updated `README.md` with optional installation (`asky[iterm]`) and usage instructions.
- **Refactor**: Moved context injection logic to `src/asky/cli/terminal.py`.
- **Robustness**: Improved terminal scanning to ignore empty lines and the command line itself.

**Verification**:
- Verified `asky -tl 5` logic flows correctly (gracefully warns if iTerm2 is missing).

---

## 2026-02-05 - Research Source Adapters for Local/Custom Content

**Summary**: Added a thin adapter layer that lets research mode reuse existing `extract_links/get_*` tools for non-HTTP targets (for example `local://...`) via user-defined custom tools.

**Changes**:
- **Adapter Layer**:
  - Added `src/asky/research/adapters.py`.
  - New config-backed adapter resolution via `research.source_adapters`.
  - Supports single-tool adapters (`tool`) or split adapters (`discover_tool` + `read_tool`).
  - Adapter contract expects custom tool `stdout` JSON with `title`, `content`, and `links`.
  - Added payload normalization for common link fields (`href/url/id/path` + title/text fallbacks).
- **Config**:
  - Added `RESEARCH_SOURCE_ADAPTERS` export in `src/asky/config/__init__.py`.
  - Added documented adapter example in `src/asky/config.toml` under the `[research]` section.
- **Research Tool Integration** (`src/asky/research/tools.py`):
  - `_fetch_and_parse()` now checks adapter mappings first, then falls back to HTTP fetching.
  - `extract_links` can cache adapter-backed targets without changing tool schema.
  - Added lazy adapter cache hydration for `get_link_summaries`, `get_relevant_content`, and `get_full_content` when adapter targets are requested before being cached.
  - Summarization trigger for adapter content is conditional on non-empty content.
- **Tests**:
  - Added `tests/test_research_adapters.py` (6 tests) for adapter matching, normalization, JSON error handling, discover/read tool routing, and hydration behavior in research tools.

**Verification**:
- Full test suite passed: `308 passed` (`uv run pytest`).

**Gotchas / Follow-up**:
- Adapter tools must emit valid JSON on `stdout`; non-JSON output is treated as an adapter error.
- For best RAG results on local sources, adapter tools should provide meaningful plain-text `content` (not only link metadata).

---

## 2026-02-05 - Context Clipping and Error Handling

**Summary**: Implemented proactive context compaction and interactive error handling to prevent application crashes due to LLM context overflow (400 Bad Request).

**Changes**:
- **Core**: Added `check_and_compact` method to `ConversationEngine` in `src/asky/core/engine.py`.
  - Proactively checks if message tokens exceed `compaction_threshold` (default 80%) of model context.
  - **Smart Compaction**: First attempts to replace large tool outputs (from URL fetches) with cached summaries from `ResearchCache`.
  - **Fallback Strategy**: If still over threshold, preserves System Prompt and Latest User Query; drops oldest middle messages until fit.
- **Error Handling**: Implemented interactive recovery for 400 Bad Request errors in `run` loop.
  - Users can now choosing to:
    - **Retry**: Compacting context further.
    - **Switch Model**: Selecting a model with larger context on the fly.
    - **Exit**: Gracefully terminating.
- **Logging**: Added debug logs (`[Smart Compaction]`) to trace summary hit/miss and truncation decisions for both dictionary and string content types.
- **Testing**: Added `tests/test_context_overflow.py` covering compaction logic (smart & destructive) and error interception.

**Verification**:
- Validated with new unit tests simulating overflow and API errors.
- Full test suite passed (299 tests).

---

## 2026-02-05 - Embedding Model Usage in Banner (Research Mode)

**Summary**: Added embedding model usage statistics display in the CLI banner when research mode (`-r`) is active, showing texts embedded, API calls, and tokens consumed.

**Changes**:
- **src/asky/research/embeddings.py**:
  - Added usage tracking counters: `texts_embedded`, `api_calls`, `prompt_tokens`
  - Counters increment in `_embed_batch()` after successful API responses
  - Added `get_usage_stats()` method to retrieve usage dictionary
  - Handles missing `usage` field in API responses gracefully (tokens = 0)
- **src/asky/banner.py**:
  - Added embedding fields to `BannerState`: `research_mode`, `embedding_model`, `embedding_texts`, `embedding_api_calls`, `embedding_prompt_tokens`
  - Added conditional "Embedding" row in banner when `research_mode=True`
  - Row format: `Embedding  : nomic-embed-text-v1.5 | Texts: 42 | API Calls: 3 | Tokens: 1,200`
  - Tokens portion only shown when `embedding_prompt_tokens > 0`
- **src/asky/cli/display.py**:
  - Added `research_mode` parameter to `InterfaceRenderer.__init__`
  - In `_build_banner()`, when `research_mode=True`, imports and reads from `get_embedding_client()` singleton
  - Passes embedding model name and usage stats to `BannerState`
- **src/asky/cli/chat.py**:
  - Passed `research_mode=research_mode` when constructing `InterfaceRenderer` (line ~228)
- **tests/test_banner_embedding.py** (NEW):
  - 10 new tests covering:
    - EmbeddingClient usage counter increments
    - `get_usage_stats()` returns correct dict
    - Banner shows/hides embedding row based on `research_mode`
    - Tokens display conditional logic
    - InterfaceRenderer integration with embedding client

**Verification**:
- Full test suite: 293 tests passing (10 new)
- Manual testing: `uv run asky -r "test query"` shows Embedding row with live stats
- Non-research mode: `uv run asky "test query"` hides Embedding row

**Follow-up**: None

---

## 2026-02-05 - List User Prompts Feature

**Summary**: Added feature to list available user prompts when entering unmatched slash commands.

**Changes**:
- **src/asky/cli/prompts.py**:
  - Replaced plain text output with `rich.Table` for better formatting
  - Added `filter_prefix` parameter for case-insensitive partial matching
  - Added `PROMPT_EXPANSION_MAX_DISPLAY_CHARS = 50` constant for truncation
  - When filter has no matches, shows "No matches for '/prefix'" then lists all prompts
- **src/asky/cli/main.py**:
  - Added slash command detection after query expansion
  - `asky /` → lists all prompts
  - `asky /partial` → filters prompts by prefix
  - `asky /nonexistent` → shows no matches message then all prompts
  - Prevents sending unresolved slash commands to LLM
- **tests/test_cli.py**:
  - Added 8 new tests covering all slash command scenarios and list_prompts_command function

**Usage**:
```bash
asky /                  # List all prompts
asky /g                 # Filter prompts starting with 'g'
asky /nonexistent       # Shows "No matches" then all prompts
asky /gn Rotterdam      # Still works normally (expands and queries)
```

---

## 2026-02-05 - Push Data Feature

**Summary**: Implemented HTTP data push functionality that allows pushing query results to external endpoints via GET/POST requests, both from CLI and as LLM-callable tools.

**Changes**:
- **Core Module**: Created `src/asky/push_data.py` with:
  - Field resolution for static, environment, dynamic, and special variables
  - Header resolution with `_env` suffix support for environment variables
  - Payload building from configuration
  - HTTP request execution (GET/POST)
  - Endpoint filtering for LLM tool registration
- **Configuration**:
  - Added `PUSH_DATA_ENDPOINTS` to `src/asky/config/__init__.py`
  - Added example `[push_data]` section to `config.toml` with documentation
  - Supports field types: static literals, environment variables (key_env), dynamic parameters (${param}), and special variables (${query}, ${answer}, ${timestamp}, ${model})
- **CLI**:
  - Added `--push-data` flag to specify endpoint name
  - Added `--push-param KEY VALUE` flag for dynamic parameters (repeatable)
  - Integrated push execution in `src/asky/cli/chat.py` after answer generation
- **LLM Tools**:
  - Registered enabled push_data endpoints as LLM-callable tools in `src/asky/core/engine.py`
  - Tool names formatted as `push_data_{endpoint_name}`
  - Dynamic parameters extracted from field configuration and exposed in tool schema
  - Special variables auto-filled during tool execution
- **Testing**: Created comprehensive `tests/test_push_data.py` with 27 test cases covering:
  - Field value resolution (all types)
  - Header resolution
  - Payload building
  - HTTP requests (mocked)
  - Error handling (missing params, missing endpoint, HTTP errors)
  - Endpoint filtering for LLM tools

**Usage Examples**:
```bash
# CLI: Push with dynamic parameters
asky --push-data my_webhook --push-param title "My Title" "my query"

# Configuration example:
[push_data.my_webhook]
url = "https://example.com/api"
method = "post"
enabled = true  # Expose to LLM as tool
description = "Post findings to webhook"

[push_data.my_webhook.fields]
title = "${title}"           # Dynamic from CLI/LLM
content = "${answer}"        # Special variable (auto-filled)
query_text = "${query}"      # Special variable (auto-filled)
api_key_env = "MY_API_KEY"   # From environment variable
```

**Follow-up**: Consider adding support for PUT/PATCH methods and request body templates for more complex payloads.

---

## 2026-02-05 - Removed Force-Search Flag

**Summary**: Removed the `--force-search` (`-fs`) flag and related code paths to simplify the interface and system prompt construction.

**Changes**:
- **CLI**: Removed `-fs` / `--force-search` from `parse_args` in `src/asky/cli/main.py`.
- **Core**: Removed `force_search` parameter and logic from `construct_system_prompt` in `src/asky/core/prompts.py`.
- **Config**: Removed `FORCE_SEARCH_PROMPT` and `force_search` template from `config.toml` and defaults.
- **Cleanup**: Removed verbose configuration print for force-search.
- **Docs**: Updated `ARCHITECTURE.md` and `DEVLOG.md`.
- **Tests**: Updated `tests/test_cli.py` and `tests/test_llm.py` to match the new API.

---

## 2026-02-05 - File-Based Custom Prompts

**Summary**: Added support for reading custom prompts from external files using the `file://` prefix in `config.toml`. Includes validation for file existence, size, and content type.

**Changes**:
- **CLI**: Added `load_custom_prompts` to `src/asky/cli/utils.py` to pre-load file content into `USER_PROMPTS`.
- **Config**: Added `max_prompt_file_size` limit (default 10KB) to `config.toml`.
- **Validation**: Implemented checks for file existence, size, and UTF-8 encoding.
- **Integration**: Integrated hook into `src/asky/cli/main.py`.
- **Tests**: Added `tests/test_file_prompts.py` with 6 new test cases.

---

## 2026-02-04 - History Command UI Update

**Summary**: Updated the `history` command (`-H`) to use a modern `rich.Table` output, consistent with `session-history`. Fixed data indexing bugs that caused "broken" output.

**Changes**:
- **CLI**: Replaced plain-text history list with `rich.Table` in `src/asky/cli/history.py`.
- **Logic**: Fixed incorrect attribute access on `Interaction` objects in `show_history_command`.
- **Formatting**: Added truncation for long queries/answers and formatted timestamps.
- **Tests**: Updated `tests/test_cli.py` to use `Interaction` objects in mocks and match new table title.

---

## 2026-02-04 - Simplified Research (Removed Deep Modes)

**Summary**: Removed Deep Dive (`-dd`) and Deep Research (`-d`) modes to simplify the codebase. Most of their functionality can be achieved via custom user prompts.

**Changes**:
- **CLI**: Removed `-d/--deep-research` and `-dd/--deep-dive` flags.
- **Core**: Deleted `page_crawler.py` and its registry logic. 
- **Prompts**: Simplified `construct_system_prompt` to remove mode-specific injections.
- **Config**: Cleaned up `config.toml` and exports by removing deep-mode templates.
- **Tests**: Deleted related tests and updated CLI/LLM tests to match new signatures.
- **Docs**: Updated `ARCHITECTURE.md` to reflect the removal.

---

## 2026-02-04 - Auto HTML Generation

**Summary**: Added automatic generation of HTML reports for conversations, improving readability and accessibility of outputs.

**Changes**:
- **Feature**: Automatically saves an HTML version of the conversation to `asky_latest_output.html` in the system temporary directory after every turn.
- **Refactor**: Extracted HTML templating logic in `rendering.py` to be reusable.
- **UX**: Prints a clickable file URL (`file:///...`) in the shell, allowing users to open the report on demand without forcing a browser window to open.
- **Modes**:
  - **Single Query**: Reports just the current Query and Answer.
  - **Session Mode**: Reports the entire session transcript.

**Notes**:
- The file is overwritten on each turn, serving as a "current view" of the conversation.

## 2026-02-04 - In-Place Banner Updates with rich.Live

**Summary**: Refactored banner display to use `rich.Live` for in-place multi-line updates, preserving terminal history.

**Problem**: The previous approach used `clear_screen()` which:
- Destroyed user's terminal history/context
- Made it impossible to continue work in the same shell after using asky
- Caused double banner when scrolling up

**Solution**: Replaced screen-clearing with `rich.Live` context manager that updates the banner in-place using ANSI cursor control.

**Changes**:
- Rewrote `InterfaceRenderer` in `display.py` to use `rich.Live`:
  - `start_live()`: Starts the Live context with initial banner
  - `update_banner()`: Updates banner in-place during execution
  - `stop_live()`: Stops Live before printing final output
  - `print_final_answer()`: Prints answer normally after stopping Live
- Updated `chat.py` to manage Live lifecycle with proper cleanup in `finally` block
- Removed `clear_screen()` entirely

**Benefits**:
- Terminal history preserved (can scroll up to see previous commands)
- Single banner that updates in-place
- Final answer prints normally below banner
- Clean exit on keyboard interrupt

---


## 2026-02-04 - Banner Redraw Bug Fix

**Summary**: Fixed critical bugs with banner display and extracted interface rendering to a proper module.

**Bugs Fixed**:
1. **Screen clearing after answer**: The `finally` block was calling `redraw_interface()` after the engine printed the final answer, making it unreadable. Removed.
2. **Double banner at end**: The engine was printing the answer AND the interface redraw was showing it from messages. Fixed by skipping engine's print when `display_callback` is provided.
3. **Summarizer stats always zero**: `InterfaceRenderer` only used the main tracker. Now combines both `usage_tracker` and `summarization_tracker` for display.

**Refactoring**:
- Extracted `redraw_interface` from `run_chat()` closure to `InterfaceRenderer` class in `cli/display.py`.
- Removed redundant `show_banner(args)` call in `main.py`.

**Files Modified**:
- `src/asky/cli/display.py` (NEW): `InterfaceRenderer` class with `_get_combined_token_usage()`.
- `src/asky/cli/chat.py`: Uses `InterfaceRenderer`, passes both trackers.
- `src/asky/core/engine.py`: Skips printing answer when in live mode.
- `src/asky/cli/main.py`: Removed redundant `show_banner` call.

---

## 2026-02-04 - Rate Limit Status Bar

**Summary**: Separated input and output token tracking in `UsageTracker` to provide more granular usage reporting.

**Changes**:
- **UsageTracker**: Updated to track `input_tokens` and `output_tokens` separately for each model alias.
- **Reporting**: Updated `chat.py` to display a detailed breakdown table (Input, Output, Total) instead of just single total.
- **API Client**: Updated `get_llm_msg` to extract prompt and completion tokens from API responses and feed them into the improved tracker.
- **Refactor**: Replaced direct access to `.usage` dict in `chat.py` with `get_usage_breakdown` accessor method.

**Files Modified**:
- `src/asky/core/api_client.py`: Updated `UsageTracker` and `get_llm_msg`.
- `src/asky/cli/chat.py`: Updated usage reporting block.
- `tests/test_usage_tracker.py`: Added new tests for split tracking.

## 2026-02-04 - Summarization Usage Tracking

**Summary**: Added separate usage tracking for summarization tasks to distinguish between conversation cost and overhead cost.

**Changes**:
- **Tracker Isolation**: Introduced a dedicated `summarization_tracker` instance alongside the main `usage_tracker`.
- **Binding Strategy**: trackers are now instantiated in `chat.py` and bound to tool registries and session managers at creation time, ensuring consistent usage without complex threading through the engine loop.
- **Reporting**: CLI now displays a second table "SUMMARIZATION TOKEN USAGE" when summarization occurs (e.g., during session compaction or URL summarization).

**Files Modified**:
- `src/asky/cli/chat.py`: Instantiated `summarization_tracker`, updated reporting.
- `src/asky/core/engine.py`: Updated registry factories to accept and bind trackers.
- `src/asky/core/registry.py`: Removed `usage_tracker` from dispatch logic.
- `src/asky/core/page_crawler.py`: Updated signature to accept `summarization_tracker`.
- `src/asky/core/session_manager.py`: Updated to use `summarization_tracker` for compaction.

---

# Development Log

## 2026-02-04 - Session Architecture Refactor (Persistent Sessions)

**Summary**: Refactored session management to make sessions persistent conversation threads that never "end". Sessions can be resumed from any shell at any time.

**Changes**:
- **Removed `is_active`/`ended_at`** from `Session` dataclass - sessions are now permanent
- **Removed `get_active_session()`/`end_session()`** from repository - DB no longer tracks active state
- **Shell-Sticky Model**: Sessions are attached to shells via lock files only (`/tmp/asky_session_{PID}`)
- **Auto-Naming**: New sessions auto-generate names from query keywords (e.g., "what is python" → "python")
  - Added `generate_session_name()` with stopword filtering
- **Duplicate Handling**: When resuming by name, if multiple sessions match, user gets a list with IDs and previews
  - Added `get_sessions_by_name()` and `DuplicateSessionError`
  - Added `get_first_message_preview()` for showing session context
- **`-se` command now only detaches** shell from session (clears lock file), doesn't modify DB
- **Removed Status column** from `-sH` session list output

**Files Modified**:
- `src/asky/storage/interface.py`: Session dataclass simplified
- `src/asky/storage/sqlite.py`: Removed `end_session`, added `get_sessions_by_name`, `get_first_message_preview`
- `src/asky/core/session_manager.py`: Added auto-naming logic, duplicate handling, shell lock file checks
- `src/asky/cli/chat.py`: Pass query to `start_or_resume`, handle `DuplicateSessionError`
- `src/asky/cli/sessions.py`: Simplified `end_session_command`, removed Status column
- `tests/test_sessions.py`: Updated tests for new architecture

---

## 2026-02-03 - Storage Refinement (Pure Message Model)

- **Refactor**: Completed transition to a **Pure Message Model**.
  - **Schema Cleanup**: Removed `query_summary` and `answer_summary` columns from the `messages` table, fully relying on the unified `summary` field.
  - **Two-Row Storage**: Enforced strict 1-row-per-message storage for all interactions (User row + Assistant row), eliminating hybrid storage.
  - **Smart Deletion**: Implemented intelligent deletion logic in `SQLiteHistoryRepository` that automatically identifies and deletes the corresponding partner message when a single message ID is targeted in global history.
  - **Context Expansion**: Updated `get_interaction_context` to automatically retrieve the full conversation turn (Query + Answer) when given a single message ID.
  - **Legacy Compatibility**: `get_history` now transparently populates the legacy `content` field (combining Query/Answer) to ensure CLI `ask -H` output remains consistent.
  - **Testing**: Updated integration tests to reflect the new 2-row architecture (e.g., deletion counts).
  - **Migration**: Added automated migration to convert legacy `history` tables to the new `messages` format, preserving all past interactions.

## 2026-02-03 - Conditional Summarization

### Changed
- Refactored `generate_summaries` in `asky/core/engine.py` and `asky/summarization.py` to skip LLM summarization if the content is already shorter than the configured thresholds (`QUERY_SUMMARY_MAX_CHARS`, `ANSWER_SUMMARY_MAX_CHARS`).
- Updated `asky/summarization.py` to use `QUERY_SUMMARY_MAX_CHARS` for query consistency.
- Updated unit tests in `tests/test_llm.py` to verify that short content is returned as-is (previously empty string for queries, or summarized for answers).

## 2026-02-03 - Database Schema Consolidation

**Summary**: Refactored database schema to consolidate `history` and `session_messages` tables into a single unified `messages` table, eliminating redundant data storage in session mode.

**Changes**:
- **Database Schema**: Created unified `messages` table with nullable `session_id` and `role` fields to distinguish between regular history entries (where both are NULL) and session messages (where both are set)
- **Repository Layer**: Merged `SessionRepository` functionality into `SQLiteHistoryRepository`, making it the single source of truth for all message storage
- **Data Models**: Updated `Interaction` dataclass to include session-related fields (`session_id`, `role`, `content`, `summary`, `token_count`)
- **Session Manager**: Updated to use `SQLiteHistoryRepository` and call `save_message()` for individual user/assistant messages instead of the old `SessionRepository.add_message()`
- **CLI Layer**: 
  - Removed duplicate `save_interaction()` call in session mode from `chat.py` - session messages are now only saved via `session_manager.save_turn()`
  - Updated `sessions.py` to use `SQLiteHistoryRepository` instead of `SessionRepository`
- **Tests**: Updated all storage, session, and integration tests to work with the new unified schema (92/92 tests passing)

**Gotchas**:
- The `content` field in the `messages` table serves dual purpose: for history entries, it contains the full "Query: X\n\nAnswer: Y" format; for session messages, it contains just the message content
- Legacy fields `query_summary` and `answer_summary` are retained for backwards compatibility with history entries
- Session messages use the `summary` field instead of the legacy summary fields
- When testing, ensure the global `_repo` instance has its `db_path` set to the mocked path before any database operations

**Follow-up**: Consider renaming `SQLiteHistoryRepository` to `SQLiteMessageRepository` to better reflect its unified purpose.

---


## 2026-02-03 (Major Refactor & Feat)

- **Refactor**: Database deletion commands completely redesigned
  - Renamed `--cleanup-db` → `--delete-messages` for clarity
  - **Removed undocumented days-based deletion logic** (single integers now mean single IDs, not days)
  - Updated storage interface: removed `days` parameter completely
  - Signature: `delete_messages(ids: Optional[str] = None, delete_all: bool = False)`
  
- **Feat**: Added `--delete-sessions` command
  - Same semantics as messages: single ID, range (`1-10`), list (`1,3,5`), or `--all`
  - **Cascade deletion**: Automatically removes associated `session_messages`
  - Implementation leverages shared deletion logic for consistency
  
- **UX**: Removed confusing "S" prefix from sessions
  - Sessions now display as `1, 2, 3` instead of `S1, S2, S3`
  - Simplified session interaction across CLI
  - Updated: session tables, chat banners, print commands
  
- **Feat**: Added `--print-session` command
  - Dedicated command for session content: `-ps` / `--print-session`
  - Accepts session ID or name directly (no S prefix)
  - Separate from `--print-answer` (now history-only)
  
- **Testing**: Comprehensive test coverage
  - All 24 unit tests passing
  - Updated storage and CLI tests for new functionality
  - Added integration test framework

## 2026-02-03 (Refactor)

- **Refactor**: Replaced `get_date_time` tool with **system message date injection**.
  - Removed `execute_get_date_time` function from `tools.py`.
  - Removed `get_date_time` tool registration from both default and deep dive tool registries in `engine.py`.
  - Updated `system_prefix` in `config.toml` to include a `{CURRENT_DATE}` placeholder with emphatic language.
  - Modified `construct_system_prompt` in `prompts.py` to inject the current date dynamically.
  - Uses strong wording ("VERIFIED", "CONFIRMED", "NOT a mock date") to ensure small local models trust the provided date over their training cutoff.
  - Verified with 87 passing tests.

## 2026-02-03 (Feat)

- **Feat**: Implemented **Persistent Session Support** with automatic context compaction.
  - Added `--sticky-session` (`-ss`) flag to start/resume conversation sessions.
  - Implemented auto-incremental session IDs (e.g., `S1`, `S22`) and user-provided session names.
  - Added `session_history` (`-sH`) to list recent and active sessions.
  - Integrated **automatic compaction**: Sessions trigger compression when context reaches a configurable threshold (default 80%).
  - Supported two compaction strategies: `summary_concat` (fast) and `llm_summary` (comprehensive).
  - Enhanced numeric-id queries to support `S` prefix (e.g., `ask S1`) for printing session content.
  - Supported `-o/--open` and `--mail` for session content export.
  - Created `SessionRepository` and `SessionManager` for clean lifecycle management.
  - **Shell-Sticky Sessions**: Sessions are now tied to each terminal instance (via parent shell PID). After using `-ss` once, subsequent calls in the same terminal auto-resume the session without needing the flag again. `--session-end` clears the association.
  - Verified with comprehensive unit tests and regression testing.

## 2026-02-03 (Fix)

- **Fix**: Updated logging handler to **clear logs at application start**.
  - Modified `setup_logging` in `logger.py` to explicitly delete the existing log file and its rotated backups upon initialization.
  - Ensures each application run starts with a fresh log, improving readability and managing disk space.
  - Verified with 0B truncation on start and 100% test pass rate.


## 2026-02-03 (Feat)

- **Feat**: Improved **LLM request logging** in `api_client.py`.
  - System messages are now logged separately for better visibility.
  - Content clipping in the payload log now respects the `verbose` flag.
  - Non-system messages are clipped to 200 characters by default, while system messages remain full.
  - Integrated `json.dumps` for cleaner payload logging.

## 2026-02-03 (Fix)

- **Fix**: Resolved `KeyError: 'content'` in `api_client.py`.
  - Occurred when logging request payloads containing messages without a `content` key (e.g., tool results).
  - Switched to safe `.get("content")` with a fallback to an empty string.

## 2026-02-03 (Metadata & Fix)

- **Feat**: Updated `pyproject.toml` with comprehensive project metadata.
  - Added `authors` and `maintainers` (Evren Esat).
  - Added `project.urls` (Homepage, Repository, Issues).
  - Added `classifiers` for PyPI (Development Status, Environment, Audience, License, Topics).
  - Added `keywords` for better discoverability.
- **Fix**: Resolved `pytest` regression in `test_email.py`.
  - Tests were inadvertently loading local configuration (e.g., `SMTP_USE_TLS`).
  - Added explicit patching for `SMTP_USE_SSL` and `SMTP_USE_TLS` in test cases to ensure hermetic execution.

## 2026-02-03 (Feat)

- **Feat**: Implemented **email sending capability**.
  - Added `markdown` dependency for server-side HTML generation.
  - Created `email_sender.py` module for SMTP communication.
  - Added `[email]` section to `config.toml` for SMTP settings.
  - Introduced `--mail` (recipients) and `--subject` CLI flags.
  - Supported emailing both new chat results and history records.
  - Integrated units tests for email module and updated CLI tests.

## 2026-02-03 (Feat)

## 2026-02-03 (Feat)

- **Feat**: Implemented **`page_crawler` tool for Deep Dive mode**.
  - Designed separate `PageCrawlerState` to map complex URLs to simple integer IDs (e.g., `1:about, 2:contact`).
  - Created `page_crawler` tool that accepts either `url` (initial fetch) or `link_ids` (follow-up).
  - Enforced mutual exclusion: Deep Dive mode now *only* exposes `page_crawler` and `get_date_time` to the model.
  - Implemented **summarization support**: When `-s/--summarize` is enabled, crawled pages are automatically summarized using the existing summarization engine.
  - Helps smaller models explore links effectively without managing long URL strings.
  - Updates persisting across conversation turns.

## 2026-02-03 (Refactor)

- **Refactor**: Re-architected core conversation loop into `ConversationEngine` and `ToolRegistry`.
  - Converted `run_conversation_loop` from a standalone function to a structured class (`ConversationEngine`).
  - Introduced `ToolRegistry` to manage tool schemas and dispatching dynamically at runtime.
  - Eliminated hardcoded tool selection logic in favor of a registration-based system.
  - Improved extensibility for future AI agent features (e.g., dynamic tool loading/unloading).
  - Maintained 100% test pass rate (69 tests) with backward-compatibility wrappers.
  - Updated `config.py` to deprecate the global `TOOLS` constant in favor of the registry.


## 2026-02-02

- **Feat**: Enabled **browser rendering for history printing**.
  - Updated `print_answers` in `cli.py` to support the `-o/--open` flag.
  - Users can now use `asky -pa <ID> -o` or `asky <ID> -o` to render and open previous results in their default browser.
  - Integrated `render_to_browser` from `llm.py` into the history printing flow.
- **Feat**: Improved **relative link handling** in `get_url_details`.
  - Updated `HTMLStripper` in `html.py` to accept an optional `base_url`.
  - Used `urllib.parse.urljoin` to resolve relative links found during HTML parsing.
  - Updated `execute_get_url_details` in `tools.py` to pass the target URL as the base URL to `HTMLStripper`.
  - This ensures that LLMs receive fully qualified, usable links even when the source page uses relative URLs.

## 2026-02-02 (Refactor)

- **Refactor**: Improved **summarization logic and context management**.
  - Extracted `_summarize_content` helper in `llm.py` to handle both query and answer summarization.
  - Removed hard-coded character limits (1000/5000) for summarization input.
  - Introduced dynamic `SUMMARIZATION_INPUT_LIMIT` calculated as 80% of the summarization model's context size.
  - Cleaned up `generate_summaries` to use the new helper and dynamic limits.
- **Fix**: Resolved **test regressions** caused by refactoring.
  - Removed obsolete `read_urls` tracking and related tests from `test_tools.py`.
  - Fixed missing `dispatch_tool_call` import and corrected its call signature in `test_tools.py`.
  - Updated `CUSTOM_TOOLS` mocks in `test_custom_tools.py` to ensure consistency across modules.

## 2026-02-02

- **Feat**: Introduced **system-wide logging**.
  - Added `log_level` and `log_file` to `config.toml`.
  - Implemented `asky.logger` for centralized log configuration.
  - Instrumented `cli.py`, `tools.py`, and `llm.py` to log critical events (tool dispatch, LLM requests, summarization).
  - Logs are written to `~/.config/asky/asky.log` by default.

- **Feat**: Introduced **markdown browser rendering**.
  - Added `-o/--open` flag to the CLI to render model output in the browser.
  - Created a lean, responsive `template.html` using a lightweight markdown parser.
  - Implemented `render_to_browser` in `llm.py` to inject content into the template and open it with the system browser.
  - Updated `system_prefix` in `config.toml` to encourage models to use markdown formatting.
  - Added unit tests for browser rendering logic and updated existing tests to handle the new flag.


- **Fix**: Resolved **database bootstrapping failure** on first run.
  - The CLI was attempting to count database records for the banner before the database was initialized.
  - Moved `init_db()` to the beginning of `main()` in `cli.py`.
  - Updated `tests/test_cli.py` to mock `get_db_record_count` in main flow tests to align with mocked `init_db`.

## 2026-02-02

- **Feat**: Enhanced CLI with a **shiny banner**.
  - Renamed project from "asearch" to "asky".
  - Added a cute icon.
  - Added `get_banner` function to `banner.py` using `rich`.
  - Integrated the banner into `cli.py` to show model details, summarizer details, search backend, and context limits in a rounded rectangle.
  - **Expansion**: Reorganized the banner into a two-column layout to include **Default Model**, **Max Turns**, and **Database Record Count**.
  - **Fix**: Adjusted banner styling to use `border_style="dim"` instead of a global `style="dim"`, ensuring icon and text colors remain vibrant.
  - Ensured the banner is only shown for actual queries to maintain a clean interface for history and maintenance tasks.

- **Feat**: Introduced **configurable query summarization threshold**.
  - Added `continue_query_threshold` (default: 160) to `[general]` section in `config.toml`.
  - Exposed `CONTINUE_QUERY_THRESHOLD` in `config.py`.
  - Updated `generate_summaries` in `llm.py` to only summarize queries exceeding this threshold.
  - Updated `get_interaction_context` in `storage.py` to use the full query if it's below the threshold, even if a summary exists.
  - Added unit tests to verify the threshold logic.

- **Feat**: Introduced **default context size setting** in the configuration.
  - Added `default_context_size` (default: 4096) to `[general]` section in `config.toml`.
  - Exposed `DEFAULT_CONTEXT_SIZE` in `config.py`.
  - Updated `run_conversation_loop` in `llm.py` to use `DEFAULT_CONTEXT_SIZE` if not specified in model configuration.
  - Added unit test in `test_config.py` to verify the setting.

- **Feat**: Implemented **token usage tracking and reporting**.
  - Added `UsageTracker` class to `llm.py` to accumulate token counts per model alias.
  - Updated `get_llm_msg` to print the number of tokens sent in each turn.
  - Enhanced `get_llm_msg` to extract real usage data from API responses if available (falls back to naive `len // 4` count).
  - Updated `run_conversation_loop` and `generate_summaries` to report usage through the tracker.
  - Added a session summary report at the end of the query execution, showing separate usage for the main model and the summarization model.
  - Updated unit tests to support the new tracking logic.

- **Fix**: Improved **rate limit handling and backoff robustness**.
  - Increased `max_retries` from 5 to 10 in `llm.py`.
  - Capped exponential backoff at 60 seconds to stay within API limit reset windows.
  - Added support for respecting the `Retry-After` header from API responses (now handles decimal strings).
  - Introduced a 1-second delay between sequential summarizations in `get_url_content` to reduce RPM (Requests Per Minute) pressure.
  - Added unit tests to verify `Retry-After` handling and batch delay logic.
- **Fix**: Resolved issue where **failed URL fetches were marked as "read"**.
  - Updated `execute_get_url_details` in `tools.py` to only append to `read_urls` after a successful request.
- **Fix**: Ensured `get_url_content` **respects the summarization flag** requested by the LLM.
  - Previously, if the CLI was run without `-s`, the tool would ignore the LLM's own request for summaries and return full content.
  - This often caused the next turn of the conversation to have a massive payload, triggering 429 rate limits on the LLM API itself.
  - Now, `execute_get_url_content` uses `effective_summarize = args.get("summarize", summarize)`, correctly balancing user preference and LLM context management.
- **Fix**: Added **URL sanitization** to remove shell-escaped backslashes.
  - Wikipedia and other servers often return 403 Forbidden for URLs containing literal backslashes (e.g., `\(`, `\)`).
  - These backslashes are frequently added when a user pastes a URL into a shell without proper quoting.
  - Added `_sanitize_url` and applied it to `fetch_single_url` and `execute_get_url_details`.

## 2026-02-01

- **Feat**: Switched to `argparse.RawTextHelpFormatter` to allow explicit newlines in CLI help text.
- **Feat**: Integrated **markdown rendering with `rich`**.

  - Added `rich` to project dependencies.
  - Implemented `is_markdown` detection in `llm.py`.
  - Updated `run_conversation_loop` in `llm.py` and `print_answers` in `cli.py` to use `rich.markdown.Markdown` for rendering LLM output if markdown is detected.



## 2026-02-01

- **Refactor**: Consolidated `-f/--full` and `-s/--summarize` into a single `-s/--summarize` parameter.
  - Removed `-f/--full` flag.
  - Updated `-s/--summarize` to handle both URL content summarization and chat context summarization.
  - Chat context now defaults to full content, and uses summaries only when `-s` is provided.
  - Updated `cli.py` and consolidated tests in `test_cli.py`.


## 2026-02-01

- **Fix**: Added **configurable request timeout** for LLM API calls.
  - Added `request_timeout` (default 60s) to `[general]` section in `config.toml`.
  - Updated `get_llm_msg` in `llm.py` to use `REQUEST_TIMEOUT` from `config.py`.
  - Broadened exception handling in `get_llm_msg` to catch and retry all `RequestException` errors (including timeouts).
  - Verified with new unit test simulating connection timeouts and verifying retries.

## 2026-02-01

- **Refactor**: Removed **multi-threaded execution** from `get_url_content` tool.
  - Replaced `ThreadPoolExecutor` with sequential execution to prevent rate limiting.
  - Simplified `execute_get_url_content` logic.
- **Feat**: Made **summarization prompts configurable** via `config.toml` under `[prompts]` section.
  - Added `summarize_query` and `summarize_answer` templates with `{QUERY_SUMMARY_MAX_CHARS}` and `{ANSWER_SUMMARY_MAX_CHARS}` placeholders.
  - Updated `llm.py` to use these templates for internal summarization tasks.

- **Feat**: Made **User-Agent configurable** via `config.toml` under `[general]` section.
  - Replaced hardcoded UA strings in `tools.py` with `USER_AGENT` constant.
  - Introduced `llm_user_agent` for LLM requests in `llm.py`.
  - Added support for loading both from configuration with sensible defaults.
- **Fix**: Made `tests/test_cli.py` independent of local configuration by patching `DEFAULT_MODEL` and `MODELS`.

- **Fix**: Added `User-Agent` header to all `requests` calls in `tools.py` to resolve **SearXNG 403 Forbidden** errors.
- **Feat**: Introduced **custom user-defined tool support**.
  - Users can define tools in `config.toml` under `[tool.NAME]`.
  - Supports command execution via `subprocess`.
  - Arguments are automatically quoted (inner quotes removed and wrapped in double quotes).
  - Supports placeholder replacement (e.g., `command = "ls {path}"`) or positional appending.
  - Default `list_dir` tool added to `config.toml`.
- **Feat**: Added **clipboard support** via `/cp` slash command.
  - Can be used anywhere in the query (not just at start).
  - Integrates with `pyperclip`.
- **Feat**: Improved **prompt expansion** to be recursive and work anywhere in the query string.
- **Fix**: Made `tests/test_tools.py` independent of user's local configuration by explicitly patching `SEARCH_PROVIDER`.
- **Refactor**: Cleaned up CLI code, removed unused imports and fixed lint warnings.
- **Feat**: Introduced **Serper API** search provider support.
  - Added `search_provider`, `serper_api_url`, and `serper_api_key_env` to `config.toml`.
  - Refactored `execute_web_search` in `tools.py` to dispatch between `SearXNG` and `Serper`.
  - Added full documentation comments for new configuration options.
- **Fix**: Resolved `AttributeError: 'Namespace' object has no attribute 'prompts'` in CLI tests caused by recent changes.
- **Refactor**: Moved configuration to `~/.config/asky/config.toml` (TOML format).
- **Feat**: Added `ConfigLoader` to `src/asky/config.py` to auto-generate default config on first run.
- **Feat**: Added support for defining API keys directly in `config.toml` or via environment variables (customizable names).
- **Refactor**: Removed `python-dotenv` dependency and `.env` file loading logic.
- **Refactor**: Relocated default history database to `~/.config/asky/history.db`. Path is configurable via `config.toml` or environment variable.
- **Refactor**: Decoupled API and Model definitions in `config.toml`. Now supports `[api.name]` sections used by `[models.name]`.
- **Feat**: Updated `config.py` to hydrate model configurations with API details (URLs, keys) automatically.
- **Refactor**: Removed direct `LMSTUDIO` constant usage in favor of data-driven configuration.
- **Test**: Verified new config schema with `pytest` and CLI execution (-v).
- **Test**: Verified config generation, loading, and API key precedence. Ran regression tests (50 passed).
- **Docs**: Added detailed explanatory comments to `src/asky/config.toml` explaining all sections and individual configuration fields.

### Dependency Cleanup
- Removed `liteLLM` dependency (simplified project, reduced bloat).
- Implemented naive token counting: `len(content) // 4`.
- Updated tests and matched `run_conversation_loop` tracking.

### Debug Flag
- Added `-v` / `--verbose` flag.
- Prints full configuration (models, constants) at startup.
- Prints LLM input previews (truncated) and tool usage status.

### Database Cleanup & Bug Fixes
- Added `--cleanup-db` (delete by ID/list/range/all)
- Fixed duplicate history output (`ask -H`)
- Fixed reverse ranges (e.g., `9-6`)
- Restored `-fs` / `--force-search`

### SQLite Conversation History
- Local SQLite storage (queries, answers, model)
- Added: `init_db`, `save_interaction`, `get_history`
- Flags:
  - `-H/--history` view recent history
  - `-c/--continue` load context by ID
  - `-f/--full` load full content
- Numeric-only query → show past answers
- Conversation loop returns final answer for storage
- Added `force_search` logic to system prompt

### Documentation
- Updated `README.md` with "Key Features" and "How it Works" sections to provide a clearer overview of the tool's purpose and functionality.


## 2026-01-31

### Tools
- `get_url_content` → fetch + strip HTML (4000 char cap, error handling)
- `get_url_details` → content + links (Deep Dive, single-use)
- `get_date_time` → ISO timestamp

### HTML Processing
- `HTMLStripper` (stdlib `html.parser`)
- Skips `<script>/<style>`, extracts `<a>`
- Major noise reduction (~734k → ~21k chars)

### Tool Execution Engine
- Multi-turn loop for sequential tool calls
- Textual tool-call regex fixed (removed strict `$`)
- Batch URL fetching + concurrency (`ThreadPoolExecutor`)
- Single-use enforcement for heavy tools
- Max turns increased to 15
- Exponential backoff for `429` rate limits

### CLI & Config
- `argparse` integration
- `-m/--model` selection
- Unquoted queries supported (`nargs='+'`)
- Per-model config (`max_chars`, auth, base_url)
- `.env` support (`python-dotenv`, override enabled)
- API auth via `api_key_env` or direct `api_key`
- Added remote model examples (`gpt-4o`, Gemini)
- Removed hardcoded keys

### Modes
- `-d/--deep-research [N]` → enforce multiple searches (default 3)
- `-dd/--deep-dive` → recursive link exploration
- Prompt construction moved to helpers/constants

### Refactor & Cleanup
- Fully modular; ≤30 lines per function
- Type hints everywhere
- Removed debug prints / unused imports
- Safe import guard (`if __name__ == "__main__"`)
- `strip_think_tags` removes `<think>` blocks

### UX / Behavior
- Query timing with `perf_counter`
- Numeric-only queries auto-load history
- Improved system prompts for tool usage
- Direct SearXNG integration (removed `app.py` dependency)

### Misc
- Lint fixes
- Improved errors and stability

### Added Unit Tests
- Installed `pytest` and configured it for the project.
- Created comprehensive unit tests for core modules:
    - `html.py`: HTML stripping and tag handling.
    - `tools.py`: Web search, URL fetching, and date utilities (mocked network calls).
    - `storage.py`: Database initialization, history storage, and cleanup (using temp DB).
    - `config.py`: Configuration validation.
    - `llm.py`: Helper functions and API call logic (mocked external APIs).
- Verified all tests pass with `uv run pytest`.


### Expanded Unit Coverage
- Created `tests/test_cli.py` to cover all CLI functionality including argument parsing, history display, and context loading.
- Updated `tests/test_llm.py` to test the core conversation loop (`run_conversation_loop`) and summarization logic (`generate_summaries`) using mocks.
- Updated `tests/test_tools.py` to test text summarization (`summarize_text`).
- Updated `tests/test_storage.py` to cover edge cases in database cleanup (e.g., reverse ranges).
- Achieved 100% pass rate for 47 unit tests.
- **Refactor**: Replaced dynamic configuration generation with a bundled `config.toml`. The default configuration file is now shipped with the package and copied to the user's config directory on first run.
- **Feat**: Enhanced `asky -c` (continue) to support relative history IDs. Users can now use `~1` (most recent), `~2` (second most recent), etc., instead of looking up exact database IDs.
- **Feat**: Added support for **Predefined Prompts**. Users can define reusable prompts in `config.toml` under `[user_prompts]` and invoke them via `/key` (e.g., `ask /wh Rotterdam`).
- **Feat**: Added `--prompts` / `-p` flag to list configured user prompts.
- **Change**: Renamed `--print-answer` short flag from `-p` to `-pa` to accommodate the new prompts flag.
- **Feat**: Improved **URL link handling** in `HTMLStripper`.
  - Added post-processing step to remove fragments (hash tags) from all extracted URLs.
  - Implemented deduplication of links based on the clean URL.
  - Removed debug prints from `html.py`.
  - Added unit test coverage for hash stripping and deduplication in `tests/test_html.py`.



## 2026-02-04

### Architecture Documentation & Code Cleanup

Created comprehensive [ARCHITECTURE.md](ARCHITECTURE.md) and addressed code quality issues.

- **Storage Consolidation**: 
  - Merged  dataclass into .
  - Removed redundant .
  - Updated  to use shared interface.

- **CLI Improvements**:
  - **Safety**: Warning: --all must be used with --delete-messages to confirm deletion.
Deleted all 1 session records and their messages. now requires explicit  or  flags to prevent accidental deletion.
  - **Output**: Removed legacy "S" prefixes from session ID displays (e.g., "S1" -> "1").
  - **Docs**: Updated  to reference checking  instead of legacy .

- **Configuration**:
  - Renamed  to  in , , and .

- **Testing**:
  - Created  with an autouse fixture to isolate tests from the user's environment (mocks  and ).
  - Fixed  execution by mocking .
  - All 94 tests passing.

- **Other**:
  - Created  to track future refactoring tasks (e.g., banner overhaul).

## 2026-02-04

### Architecture Documentation & Code Cleanup

Created comprehensive [ARCHITECTURE.md](ARCHITECTURE.md) and addressed code quality issues.

- **Storage Consolidation**: 
  - Merged `Session` dataclass into `storage/interface.py`.
  - Removed redundant `storage/session.py`.
  - Updated `storage/sqlite.py` to use shared interface.

- **CLI Improvements**:
  - **Safety**: `asky --all` now requires explicit `--delete-messages` or `--delete-sessions` flags to prevent accidental deletion.
  - **Output**: Removed legacy "S" prefixes from session ID displays (e.g., "S1" -> "1").
  - **Docs**: Updated `README.md` to reference checking `--delete-messages` instead of legacy `--cleanup-db`.

- **Configuration**:
  - Renamed `SEARXNG_HISTORY_DB_PATH` to `ASKY_DB_PATH` in `config.toml`, `config/__init__.py`, and `storage/sqlite.py`.

- **Testing**:
  - Created `tests/conftest.py` with an autouse fixture to isolate tests from the user's environment (mocks `HOME` and `ASKY_DB_PATH`).
  - Fixed `test_main_flow` execution by mocking `SUMMARIZATION_MODEL`.
  - All 94 tests passing.

- **Other**:
  - Created `TODO.md` to track future refactoring tasks (e.g., banner overhaul).

## 2026-02-04 - Session Logic Refinement (Separated Create/Resume)

**Summary**: Refined session management to clearly distinguish between creating a new session and resuming an existing one, improving UX and removing implicit behaviors.

**Changes**:
- **Flag Separation**:
  - `-ss / --sticky-session`: Now ONLY creates a new named session and exits immediately (e.g., `asky -ss MyProject`).
  - `-rs / --resume-session`: New flag to search and resume existing sessions (e.g., `asky -rs MyPro`).
- **Feature Changes**:
  - **Removed Auto-Naming**: Sessions no longer auto-generate names from queries. Names must be explicit via `-ss`.
  - **Fuzzy Search**: `-rs` supports partial name matching. If multiple sessions match, a list is displayed.
- **Code Refactor**:
  - Refactored `SessionManager` to remove `start_or_resume` complexity.
  - Implemented cleaner `create_session` and `find_sessions` methods.
- **Testing**:
  - Updated CLI tests and Session Manager tests to cover separate flows and partial matching.

## 2026-02-04 - Rate Limit Status Bar

**Summary**: Implemented a status bar in the CLI banner to display rate limit warnings (429 errors) and other system messages in real-time without polluting the chat log.

**Changes**:
- **Banner UI**: Updated `BannerState` and `get_banner` in `banner.py` to support a `status_message` displayed as a right-aligned subtitle.
- **API Client**: Updated `get_llm_msg` in `api_client.py` to accept a `status_callback`. It now invokes this callback with "Retrying in X seconds..." when a 429 error occurs, and clears it on success.
- **Engine Support**: Updated `ConversationEngine` in `engine.py` to bridge the API client's status updates to the CLI display loop.
- **CLI Integration**: Updated `chat.py` to redraw the interface with the current status message.
- **Testing**: Added `tests/test_api_client_status.py` to verify the callback logic in isolation.

**Verification**:
- Verified visually using a reproduction script.
- Verified logic with new unit tests.
- Ran full test suite (99 passed) to ensure no regressions.

## 2026-02-04 - Graceful Exit on Turn Limit

**Summary**: Improved the user experience when the conversation exceeds the maximum turn limit (`MAX_TURNS`).

**Changes**:
- **Engine Logic**: Instead of abruptly aborting with an error log, the engine now:
    1. Injects a strong system instruction: "Finish your task now. You cannot make any more tool calls."
    2. Forces one final LLM call with `use_tools=False`.
    3. Displays the final text-only response to the user.
- **Testing**: Added unit tests in `tests/test_llm.py` to verify the graceful exit sequence and message injection.

**Verification**:
- Ran full test suite (101 passed) to ensure no regressions.

## 2026-02-04 - Deep Dive Prompt Fix

**Summary**: Fixed a bug where the `get_url_content` tool was incorrectly mentioned in the system prompt during Deep Dive mode, confusing models.

**Changes**:
- **Configuration**: Split `system_suffix` in `config.toml` into `search_suffix` (containing `get_url_content` instructions) and a reduced `system_suffix`.
- **Logic**: Updated `prompts.py` to conditionally append `SEARCH_SUFFIX` only when *not* in Deep Dive mode.
- **Verification**: Verified with reproduction script and full test suite (101 passed).

## 2026-02-05 - Strict TOML Validation

**Summary**: Implemented strict validation for the configuration file. The application now exits with an error if `config.toml` contains invalid TOML syntax, preventing silent failures and unexpected default behaviors.

**Changes**:
- **Loader**: Updated `src/asky/config/loader.py` to catch `tomllib.TOMLDecodeError`.
- **Error Handling**: Prints a descriptive error message to stderr and exits with status code 1.
- **Testing**: Added `tests/test_config.py::test_invalid_config_exits` to verify the behavior.
- **Verification**: Verified with both manual reproduction script and automated tests.
