"""Configuration constants and static declarations for asky."""

import os
import tomllib
from pathlib import Path
import copy
from typing import Dict, Any


import shutil
from importlib import resources


def _get_config_dir() -> Path:
    """Return the configuration directory path."""
    return Path.home() / ".config" / "asky"


def _hydrate_models(config: Dict[str, Any]) -> Dict[str, Any]:
    """Hydrate model definitions with API details."""
    api_defs = config.get("api", {})
    models = config.get("models", {})

    for alias, model_data in models.items():
        model_data["alias"] = alias
        api_ref = model_data.get("api")
        if api_ref and api_ref in api_defs:
            api_config = api_defs[api_ref]

            if "url" in api_config and "base_url" not in model_data:
                model_data["base_url"] = api_config["url"]

            if "api_key" in api_config and "api_key" not in model_data:
                model_data["api_key"] = api_config["api_key"]

            if "api_key_env" in api_config and "api_key_env" not in model_data:
                model_data["api_key_env"] = api_config["api_key_env"]

    return config


def load_config() -> Dict[str, Any]:
    """Load configuration from TOML file, falling back to defaults."""
    config_dir = _get_config_dir()
    config_path = config_dir / "config.toml"

    # Ensure config directory exists
    config_dir.mkdir(parents=True, exist_ok=True)

    bundled_config_path_traversable = resources.files("asky").joinpath("config.toml")

    # Read default config from package
    try:
        with bundled_config_path_traversable.open("rb") as f:
            default_config = tomllib.load(f)
    except Exception as e:
        print(f"Error loading bundled config: {e}")
        # Build a minimal fallback if bundled config fails
        default_config = {
            "general": {
                "query_summary_max_chars": 40,
                "continue_query_threshold": 160,
                "log_level": "INFO",
                "log_file": "~/.config/asky/asky.log",
                "answer_summary_max_chars": 200,
                "searxng_url": "http://localhost:8888",
                "max_turns": 20,
                "default_model": "gf",
                "summarization_model": "lfm",
                "request_timeout": 60,
                "default_context_size": 4096,
            },
            "api": {},
            "models": {
                "gf": {
                    "id": "gemini-flash-latest",
                    "api": "gemini",
                    "max_chars": 1000000,
                    "context_size": 1000000,
                }
            },
            "prompts": {
                "system_prefix": "",
                "force_search": "",
                "system_suffix": "",
                "deep_research": "",
                "deep_dive": "",
            },
            "user_prompts": {},
            "tool": {},
        }

    # Initialize from defaults
    final_config = copy.deepcopy(default_config)

    # Copy bundled config to user config dir if it doesn't exist
    if not config_path.exists():
        try:
            with resources.as_file(bundled_config_path_traversable) as source_path:
                shutil.copy(source_path, config_path)
            print(f"Created default configuration at {config_path}")
        except Exception as e:
            print(f"Warning: Failed to create default config at {config_path}: {e}")

    # Load user config if it exists and merge
    if config_path.exists():
        try:
            with open(config_path, "rb") as f:
                user_config = tomllib.load(f)

            # Recursive merge with default config
            def merge(base, update):
                for k, v in update.items():
                    if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                        merge(base[k], v)
                    else:
                        base[k] = v

            merge(final_config, user_config)

        except Exception as e:
            print(f"Warning: Failed to load config from {config_path}: {e}")

    return _hydrate_models(final_config)


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

# Database
# DB Path logic:
# 1. Env Var (name defined in config, e.g. SEARXNG_HISTORY_DB_PATH)
# 2. Configured 'db_path' in [general]
# 3. Default: ~/.config/asky/history.db

_db_env_var_name = _gen.get("db_path_env_var", "SEARXNG_HISTORY_DB_PATH")
_env_path = os.environ.get(_db_env_var_name)

if _env_path:
    DB_PATH = Path(_env_path)
elif "db_path" in _gen and _gen["db_path"]:
    DB_PATH = Path(_gen["db_path"]).expanduser()
else:
    DB_PATH = _get_config_dir() / "history.db"

TEMPLATE_PATH = Path(__file__).parent / "template.html"

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
    "Summarize the following query into a single short sentence (max {QUERY_SUMMARY_MAX_CHARS} chars).",
)
SUMMARIZE_ANSWER_PROMPT_TEMPLATE = _prompts.get(
    "summarize_answer",
    "Summarize the following answer into a short paragraph (max {ANSWER_SUMMARY_MAX_CHARS} chars).",
)
USER_PROMPTS = _CONFIG.get("user_prompts", {})

# --- Custom Tools ---
# These are loaded from [tool.NAME] sections in config.toml
CUSTOM_TOOLS = _CONFIG.get("tool", {})


# --- Tool Definitions ---
# Tools are code-coupled schemas, keeping them here as constants.
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web and return top results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {"type": "string"},
                    "count": {"type": "integer", "default": 5},
                },
                "required": ["q"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_url_content",
            "description": "Fetch the content of one or more URLs and return their text content (HTML stripped).",
            "parameters": {
                "type": "object",
                "properties": {
                    "urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of URLs to fetch content from.",
                    },
                    "url": {
                        "type": "string",
                        "description": "Single URL (deprecated, use 'urls' instead).",
                    },
                    "summarize": {
                        "type": "boolean",
                        "description": "If true, summarize the content of the page using an LLM.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_url_details",
            "description": "Fetch content and extract links from a URL. Use this in deep dive mode.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_date_time",
            "description": "Return the current date and time.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

# Append custom tools from config.toml
for tool_name, tool_data in CUSTOM_TOOLS.items():
    tool_entry = {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": tool_data.get("description", f"Custom tool: {tool_name}"),
            "parameters": tool_data.get(
                "parameters", {"type": "object", "properties": {}}
            ),
        },
    }
    TOOLS.append(tool_entry)
