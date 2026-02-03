# Development Log

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


