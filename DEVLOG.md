# Development Log

## 2026-02-01

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
