# Development Log

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
- **Refactor**: Moved configuration to `~/.config/asearch/config.toml` (TOML format).
- **Feat**: Added `ConfigLoader` to `src/asearch/config.py` to auto-generate default config on first run.
- **Feat**: Added support for defining API keys directly in `config.toml` or via environment variables (customizable names).
- **Refactor**: Removed `python-dotenv` dependency and `.env` file loading logic.
- **Refactor**: Relocated default history database to `~/.config/asearch/history.db`. Path is configurable via `config.toml` or environment variable.
- **Refactor**: Decoupled API and Model definitions in `config.toml`. Now supports `[api.name]` sections used by `[models.name]`.
- **Feat**: Updated `config.py` to hydrate model configurations with API details (URLs, keys) automatically.
- **Refactor**: Removed direct `LMSTUDIO` constant usage in favor of data-driven configuration.
- **Test**: Verified new config schema with `pytest` and CLI execution (-v).
- **Test**: Verified config generation, loading, and API key precedence. Ran regression tests (50 passed).
- **Docs**: Added detailed explanatory comments to `src/asearch/config.toml` explaining all sections and individual configuration fields.

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
- **Feat**: Enhanced `asearch -c` (continue) to support relative history IDs. Users can now use `~1` (most recent), `~2` (second most recent), etc., instead of looking up exact database IDs.
- **Feat**: Added support for **Predefined Prompts**. Users can define reusable prompts in `config.toml` under `[user_prompts]` and invoke them via `/key` (e.g., `ask /wh Rotterdam`).
- **Feat**: Added `--prompts` / `-p` flag to list configured user prompts.
- **Change**: Renamed `--print-answer` short flag from `-p` to `-pa` to accommodate the new prompts flag.

