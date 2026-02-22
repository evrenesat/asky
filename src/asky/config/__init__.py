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
LOG_FILE = _gen.get("log_file", "~/.config/asky/logs/asky.log")
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

# Summarization Settings
_summarizer_section = _CONFIG.get("summarizer", {})
SUMMARIZATION_LAZY_THRESHOLD_CHARS = _summarizer_section.get(
    "lazy_threshold_chars", 2000
)
SUMMARIZATION_HIERARCHICAL_TRIGGER_CHARS = _summarizer_section.get(
    "hierarchical_trigger_chars", 3200
)
SUMMARIZATION_HIERARCHICAL_MAX_INPUT_CHARS = _summarizer_section.get(
    "hierarchical_max_input_chars", 32000
)
SUMMARIZATION_HIERARCHICAL_CHUNK_TARGET_CHARS = _summarizer_section.get(
    "hierarchical_chunk_target_chars", 2800
)
SUMMARIZATION_HIERARCHICAL_CHUNK_OVERLAP_CHARS = _summarizer_section.get(
    "hierarchical_chunk_overlap_chars", 220
)
SUMMARIZATION_HIERARCHICAL_MAP_MAX_OUTPUT_CHARS = _summarizer_section.get(
    "hierarchical_map_max_output_chars", 750
)

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
GRACEFUL_EXIT_SYSTEM = _prompts.get("graceful_exit", "")
RESEARCH_RETRIEVAL_ONLY_GUIDANCE_PROMPT = _prompts.get(
    "research_retrieval_only_guidance",
    (
        "A research corpus has been pre-loaded for this query. Your sources are already\n"
        "indexed and available.\n\n"
        "Your task:\n"
        "1. Use `query_research_memory` to check if relevant findings already exist.\n"
        "2. Use `get_relevant_content` with specific sub-questions to retrieve evidence\n"
        "   from the indexed corpus.\n"
        "3. Use `save_finding` to persist key facts with source attribution.\n"
        "4. Use `save_finding` for source-backed research evidence.\n"
        "   Use `save_memory` only for durable user preferences/facts.\n"
        "5. Before the final answer, run `query_research_memory` again and synthesize\n"
        "   from the saved findings with citations.\n\n"
        "Do NOT attempt to browse new URLs or extract links - the corpus is already built."
    ),
)
TOOL_PROMPT_OVERRIDES = (
    _prompts.get("tool_overrides", {})
    if isinstance(_prompts.get("tool_overrides", {}), dict)
    else {}
)

# Session
_session = _CONFIG.get("session", {})
SESSION_COMPACTION_THRESHOLD = _session.get("compaction_threshold", 80)
SESSION_COMPACTION_STRATEGY = _session.get("compaction_strategy", "summary_concat")
SESSION_IDLE_TIMEOUT_MINUTES = _session.get("idle_timeout_minutes", 5)

USER_PROMPTS = _CONFIG.get("user_prompts", {})

# Custom Tools
CUSTOM_TOOLS = _CONFIG.get("tool", {})

# Push Data Endpoints
PUSH_DATA_ENDPOINTS = _CONFIG.get("push_data", {})

# Research Mode
_research = _CONFIG.get("research", {})
RESEARCH_ENABLED = _research.get("enabled", True)
QUERY_EXPANSION_ENABLED = _research.get("query_expansion_enabled", True)
QUERY_EXPANSION_MODE = _research.get("query_expansion_mode", "deterministic")
QUERY_EXPANSION_MAX_SUB_QUERIES = _research.get("max_sub_queries", 4)
RESEARCH_CACHE_TTL_HOURS = _research.get("cache_ttl_hours", 24)
RESEARCH_MAX_LINKS_PER_URL = _research.get("max_links_per_url", 50)
RESEARCH_MAX_RELEVANT_LINKS = _research.get("max_relevant_links", 20)
RESEARCH_CHUNK_SIZE = _research.get("chunk_size", 256)
RESEARCH_CHUNK_OVERLAP = _research.get("chunk_overlap", 48)
RESEARCH_MAX_CHUNKS_PER_RETRIEVAL = _research.get("max_chunks_per_retrieval", 5)
RESEARCH_EVIDENCE_EXTRACTION_ENABLED = _research.get(
    "evidence_extraction_enabled", False
)
RESEARCH_EVIDENCE_EXTRACTION_MAX_CHUNKS = _research.get(
    "evidence_extraction_max_chunks", 10
)
RESEARCH_SUMMARIZATION_WORKERS = _research.get("summarization_workers", 2)
RESEARCH_MEMORY_MAX_RESULTS = _research.get("memory_max_results", 10)
RESEARCH_LOCAL_DOCUMENT_ROOTS = [
    str(Path(raw_path).expanduser())
    for raw_path in _research.get("local_document_roots", [])
    if str(raw_path).strip()
]
_research_chromadb = _research.get("chromadb", {})
RESEARCH_CHROMA_PERSIST_DIRECTORY = Path(
    _research_chromadb.get("persist_directory", "~/.config/asky/chromadb")
).expanduser()
RESEARCH_CHROMA_CHUNKS_COLLECTION = _research_chromadb.get(
    "chunks_collection", "asky_content_chunks"
)
RESEARCH_CHROMA_LINKS_COLLECTION = _research_chromadb.get(
    "links_collection", "asky_link_embeddings"
)
RESEARCH_CHROMA_FINDINGS_COLLECTION = _research_chromadb.get(
    "findings_collection", "asky_research_findings"
)

# Source Shortlist Settings (shared by research and standard modes)
_source_shortlist = _research.get("source_shortlist", {})
SOURCE_SHORTLIST_ENABLED = _source_shortlist.get("enabled", True)
SOURCE_SHORTLIST_ENABLE_RESEARCH_MODE = _source_shortlist.get(
    "enable_research_mode", True
)
SOURCE_SHORTLIST_ENABLE_STANDARD_MODE = _source_shortlist.get(
    "enable_standard_mode", False
)
SOURCE_SHORTLIST_SEARCH_WITH_SEED_URLS = _source_shortlist.get(
    "search_with_seed_urls", False
)
SOURCE_SHORTLIST_SEED_LINK_EXPANSION_ENABLED = _source_shortlist.get(
    "seed_link_expansion_enabled", True
)
SOURCE_SHORTLIST_SEED_LINK_MAX_PAGES = _source_shortlist.get("seed_link_max_pages", 3)
SOURCE_SHORTLIST_SEED_LINKS_PER_PAGE = _source_shortlist.get("seed_links_per_page", 50)
SOURCE_SHORTLIST_SEARCH_RESULT_COUNT = _source_shortlist.get("search_result_count", 40)
SOURCE_SHORTLIST_MAX_CANDIDATES = _source_shortlist.get("max_candidates", 40)
SOURCE_SHORTLIST_MAX_FETCH_URLS = _source_shortlist.get("max_fetch_urls", 20)
SOURCE_SHORTLIST_TOP_K = _source_shortlist.get("top_k", 8)
SOURCE_SHORTLIST_MIN_CONTENT_CHARS = _source_shortlist.get("min_content_chars", 300)
SOURCE_SHORTLIST_MAX_SCORING_CHARS = _source_shortlist.get("max_scoring_chars", 5000)
SOURCE_SHORTLIST_SNIPPET_CHARS = _source_shortlist.get("snippet_chars", 700)
SOURCE_SHORTLIST_DOC_LEAD_CHARS = _source_shortlist.get("doc_lead_chars", 1400)
SOURCE_SHORTLIST_QUERY_FALLBACK_CHARS = _source_shortlist.get(
    "query_fallback_chars", 600
)
SOURCE_SHORTLIST_KEYPHRASE_MIN_QUERY_CHARS = _source_shortlist.get(
    "keyphrase_min_query_chars", 220
)
SOURCE_SHORTLIST_KEYPHRASE_TOP_K = _source_shortlist.get("keyphrase_top_k", 20)
SOURCE_SHORTLIST_SEARCH_PHRASE_COUNT = _source_shortlist.get("search_phrase_count", 5)
SOURCE_SHORTLIST_SHORT_TEXT_THRESHOLD = _source_shortlist.get(
    "short_text_threshold", 700
)
SOURCE_SHORTLIST_SAME_DOMAIN_BONUS = _source_shortlist.get("same_domain_bonus", 0.05)
SOURCE_SHORTLIST_OVERLAP_BONUS_WEIGHT = _source_shortlist.get(
    "overlap_bonus_weight", 0.10
)
SOURCE_SHORTLIST_SHORT_TEXT_PENALTY = _source_shortlist.get("short_text_penalty", 0.10)
SOURCE_SHORTLIST_NOISE_PATH_PENALTY = _source_shortlist.get("noise_path_penalty", 0.15)

# Research Embedding Settings
_research_embedding = _research.get("embedding", {})
RESEARCH_EMBEDDING_MODEL = _research_embedding.get("model", "all-MiniLM-L6-v2")
RESEARCH_EMBEDDING_BATCH_SIZE = _research_embedding.get("batch_size", 32)
RESEARCH_EMBEDDING_DEVICE = _research_embedding.get("device", "cpu")
RESEARCH_EMBEDDING_NORMALIZE = _research_embedding.get("normalize", True)
RESEARCH_EMBEDDING_LOCAL_FILES_ONLY = _research_embedding.get("local_files_only", False)

# Research Prompts
RESEARCH_SYSTEM_PROMPT = _prompts.get("research_system", "")
RESEARCH_SYSTEM_PREFIX = _research.get("system_prefix")
RESEARCH_SYSTEM_SUFFIX = _research.get("system_suffix")
RESEARCH_FORCE_SEARCH = _research.get("force_search")

SUMMARIZE_PAGE_PROMPT = _prompts.get(
    "summarize_page", "Summarize this webpage content concisely in 2-3 sentences."
)

# User Memory
_memory = _CONFIG.get("memory", {})
USER_MEMORY_ENABLED = _memory.get("enabled", True)
USER_MEMORY_RECALL_TOP_K = _memory.get("recall_top_k", 5)
USER_MEMORY_RECALL_MIN_SIMILARITY = _memory.get("recall_min_similarity", 0.35)
USER_MEMORY_DEDUP_THRESHOLD = _memory.get("dedup_threshold", 0.90)
USER_MEMORY_CHROMA_COLLECTION = _memory.get("chroma_collection", "asky_user_memories")
USER_MEMORY_GLOBAL_TRIGGERS = _memory.get(
    "global_triggers", ["remember globally:", "global memory:"]
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
