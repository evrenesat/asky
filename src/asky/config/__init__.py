"""Configuration constants and re-exports for asky."""

import os
from pathlib import Path
from asky.config.loader import load_config, _get_config_dir

# --- Initialize Configuration ---
_CONFIG = load_config()

# --- Expose Constants ---

# General
_gen = _CONFIG["general"]
QUERY_SUMMARY_MAX_CHARS = _gen["query_summary_max_chars"]
CONTINUE_QUERY_THRESHOLD = _gen.get("continue_query_threshold", 160)
ANSWER_SUMMARY_MAX_CHARS = _gen["answer_summary_max_chars"]
SEARXNG_URL = _gen["searxng_url"]
MAX_TURNS = _gen["max_turns"]
DEFAULT_MODEL = _gen["default_model"]
SUMMARIZATION_MODEL = _gen["summarization_model"]
SEARCH_PROVIDER = _gen.get("search_provider", "searxng")
SERPER_API_URL = _gen.get("serper_api_url", "https://google.serper.dev/search")
SERPER_API_KEY_ENV = _gen.get("serper_api_key_env", "SERPER_API_KEY")
USER_AGENT = _gen.get(
    "user_agent",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
)
LLM_USER_AGENT = _gen.get("llm_user_agent", USER_AGENT)
REQUEST_TIMEOUT = _gen.get("request_timeout", 60)
DEFAULT_CONTEXT_SIZE = _gen.get("default_context_size", 4096)
LOG_LEVEL = _gen.get("log_level", "INFO")
LOG_FILE = _gen.get("log_file", "~/.config/asky/asky.log")

# Limits & Timeouts
_limits = _CONFIG.get("limits", {})
MAX_URL_DETAIL_LINKS = _limits.get("max_url_detail_links", 50)
SEARCH_SNIPPET_MAX_CHARS = _limits.get("search_snippet_max_chars", 400)
QUERY_EXPANSION_MAX_DEPTH = _limits.get("query_expansion_max_depth", 5)
MAX_RETRIES = _limits.get("max_retries", 10)
INITIAL_BACKOFF = _limits.get("initial_backoff", 2)
MAX_BACKOFF = _limits.get("max_backoff", 60)
SEARCH_TIMEOUT = _limits.get("search_timeout", 20)
FETCH_TIMEOUT = _limits.get("fetch_timeout", 20)

# Summarization Input Limit Calculation
_SUMMARIZATION_INPUT_RATIO = 0.8
_CHARS_PER_TOKEN = 4
_summarizer_config = _CONFIG["models"].get(SUMMARIZATION_MODEL, {})
_summarizer_context = _summarizer_config.get("context_size", DEFAULT_CONTEXT_SIZE)
SUMMARIZATION_INPUT_LIMIT = int(
    _summarizer_context * _SUMMARIZATION_INPUT_RATIO * _CHARS_PER_TOKEN
)

# Database
_db_env_var_name = _gen.get("db_path_env_var", "SEARXNG_HISTORY_DB_PATH")
_env_path = os.environ.get(_db_env_var_name)

if _env_path:
    DB_PATH = Path(_env_path)
elif "db_path" in _gen and _gen["db_path"]:
    DB_PATH = Path(_gen["db_path"]).expanduser()
else:
    DB_PATH = _get_config_dir() / "history.db"

TEMPLATE_PATH = Path(__file__).parent.parent / "template.html"

# Models
MODELS = _CONFIG["models"]

# Prompts
_prompts = _CONFIG["prompts"]
SYSTEM_PROMPT = _prompts["system_prefix"]
FORCE_SEARCH_PROMPT = _prompts["force_search"]
SYSTEM_PROMPT_SUFFIX = _prompts["system_suffix"]
DEEP_RESEARCH_PROMPT_TEMPLATE = _prompts["deep_research"]
DEEP_DIVE_PROMPT_TEMPLATE = _prompts["deep_dive"]
SUMMARIZE_QUERY_PROMPT_TEMPLATE = _prompts.get(
    "summarize_query",
    "Summarize the following query into a single short sentence.",
)
SUMMARIZE_ANSWER_PROMPT_TEMPLATE = _prompts.get(
    "summarize_answer",
    "Summarize the following answer into a short paragraph. Be sure to include all numerical values and dates.",
)
USER_PROMPTS = _CONFIG.get("user_prompts", {})

# Custom Tools
CUSTOM_TOOLS = _CONFIG.get("tool", {})
