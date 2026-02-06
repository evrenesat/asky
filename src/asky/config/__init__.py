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
TERMINAL_CONTEXT_LINES = _gen.get("terminal_context_lines", 10)
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
LIVE_BANNER = True
COMPACT_BANNER = _gen.get("compact_banner", False)
ARCHIVE_DIR = Path(_gen.get("archive_dir", "~/.config/asky/archive")).expanduser()


# Limits & Timeouts
_limits = _CONFIG.get("limits", {})
MAX_URL_DETAIL_LINKS = _limits.get("max_url_detail_links", 50)
SEARCH_SNIPPET_MAX_CHARS = _limits.get("search_snippet_max_chars", 400)
QUERY_EXPANSION_MAX_DEPTH = _limits.get("query_expansion_max_depth", 5)
MAX_PROMPT_FILE_SIZE = _limits.get("max_prompt_file_size", 10240)
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
_db_env_var_name = _gen.get("db_path_env_var", "ASKY_DB_PATH")
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
SEARCH_SUFFIX = _prompts["search_suffix"]
SYSTEM_PROMPT_SUFFIX = _prompts["system_suffix"]
SUMMARIZE_QUERY_PROMPT_TEMPLATE = _prompts.get(
    "summarize_query",
    "Summarize the following query into a single short sentence.",
)
SUMMARIZE_ANSWER_PROMPT_TEMPLATE = _prompts.get(
    "summarize_answer",
    "Summarize the following answer into a short paragraph. Be sure to include all numerical values and dates.",
)
SUMMARIZE_SESSION_PROMPT = _prompts.get(
    "summarize_session",
    "Summarize this conversation history into a concise context summary.",
)

# Session
_session = _CONFIG.get("session", {})
SESSION_COMPACTION_THRESHOLD = _session.get("compaction_threshold", 80)
SESSION_COMPACTION_STRATEGY = _session.get("compaction_strategy", "summary_concat")

USER_PROMPTS = _CONFIG.get("user_prompts", {})

# Custom Tools
CUSTOM_TOOLS = _CONFIG.get("tool", {})

# Push Data Endpoints
PUSH_DATA_ENDPOINTS = _CONFIG.get("push_data", {})

# Research Mode
_research = _CONFIG.get("research", {})
RESEARCH_ENABLED = _research.get("enabled", True)
RESEARCH_CACHE_TTL_HOURS = _research.get("cache_ttl_hours", 24)
RESEARCH_MAX_LINKS_PER_URL = _research.get("max_links_per_url", 50)
RESEARCH_MAX_RELEVANT_LINKS = _research.get("max_relevant_links", 20)
RESEARCH_CHUNK_SIZE = _research.get("chunk_size", 1000)
RESEARCH_CHUNK_OVERLAP = _research.get("chunk_overlap", 200)
RESEARCH_MAX_CHUNKS_PER_RETRIEVAL = _research.get("max_chunks_per_retrieval", 5)
RESEARCH_SUMMARIZATION_WORKERS = _research.get("summarization_workers", 2)
RESEARCH_MEMORY_MAX_RESULTS = _research.get("memory_max_results", 10)
RESEARCH_SOURCE_ADAPTERS = _research.get("source_adapters", {})

# Research Embedding Settings
_research_embedding = _research.get("embedding", {})
RESEARCH_EMBEDDING_API_URL = _research_embedding.get(
    "api_url", "http://localhost:1234/v1/embeddings"
)
RESEARCH_EMBEDDING_MODEL = _research_embedding.get(
    "model", "text-embedding-nomic-embed-text-v1.5"
)
RESEARCH_EMBEDDING_DIMENSION = _research_embedding.get("dimension", 768)
RESEARCH_EMBEDDING_BATCH_SIZE = _research_embedding.get("batch_size", 32)
RESEARCH_EMBEDDING_TIMEOUT = _research_embedding.get("timeout", 30)
RESEARCH_EMBEDDING_RETRY_ATTEMPTS = _research_embedding.get("retry_attempts", 3)
RESEARCH_EMBEDDING_RETRY_BACKOFF_SECONDS = _research_embedding.get(
    "retry_backoff_seconds", 0.5
)

# Research Prompts
RESEARCH_SYSTEM_PROMPT = _prompts.get("research_system", "")
SUMMARIZE_PAGE_PROMPT = _prompts.get(
    "summarize_page", "Summarize this webpage content concisely in 2-3 sentences."
)

# Email
_email = _CONFIG.get("email", {})
SMTP_HOST = _email.get("smtp_host", "localhost")
SMTP_PORT = _email.get("smtp_port", 587)
SMTP_USE_SSL = _email.get("smtp_use_ssl", False)
SMTP_USE_TLS = _email.get("smtp_use_tls", True)

_smtp_user_env = _email.get("smtp_user_env", "ASKY_SMTP_USER")
SMTP_USER = os.environ.get(_smtp_user_env) or _email.get("smtp_user")

_smtp_password_env = _email.get("smtp_password_env", "ASKY_SMTP_PASSWORD")
SMTP_PASSWORD = os.environ.get(_smtp_password_env) or _email.get("smtp_password")

EMAIL_FROM_ADDRESS = _email.get("from_address") or SMTP_USER
