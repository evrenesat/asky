"""Configuration constants and static declarations for asearch."""

import os
import tomllib
from pathlib import Path
import copy
from typing import Dict, Any


import shutil
from importlib import resources


def _get_config_dir() -> Path:
    """Return the configuration directory path."""
    return Path.home() / ".config" / "asearch"


def _hydrate_models(config: Dict[str, Any]) -> Dict[str, Any]:
    """Hydrate model definitions with API details."""
    api_defs = config.get("api", {})
    models = config.get("models", {})

    for model_data in models.values():
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

    bundled_config_path_traversable = resources.files("asearch").joinpath("config.toml")

    # Read default config from package
    try:
        with bundled_config_path_traversable.open("rb") as f:
            default_config = tomllib.load(f)
    except Exception as e:
        print(f"Error loading bundled config: {e}")
        # Build a minimal fallback if bundled config fails
        default_config = {"general": {}, "api": {}, "models": {}, "prompts": {}}

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
ANSWER_SUMMARY_MAX_CHARS = _gen["answer_summary_max_chars"]
ANSWER_SUMMARY_MAX_CHARS = _gen["answer_summary_max_chars"]
SEARXNG_URL = _gen["searxng_url"]
MAX_TURNS = _gen["max_turns"]
DEFAULT_MODEL = _gen["default_model"]
SUMMARIZATION_MODEL = _gen["summarization_model"]

# Database
# DB Path logic:
# 1. Env Var (name defined in config, e.g. SEARXNG_HISTORY_DB_PATH)
# 2. Configured 'db_path' in [general]
# 3. Default: ~/.config/asearch/history.db

_db_env_var_name = _gen.get("db_path_env_var", "SEARXNG_HISTORY_DB_PATH")
_env_path = os.environ.get(_db_env_var_name)

if _env_path:
    DB_PATH = Path(_env_path)
elif "db_path" in _gen and _gen["db_path"]:
    DB_PATH = Path(_gen["db_path"]).expanduser()
else:
    DB_PATH = _get_config_dir() / "history.db"

# Models
MODELS = _CONFIG["models"]

# Prompts
_prompts = _CONFIG["prompts"]
SYSTEM_PROMPT = _prompts["system_prefix"]
FORCE_SEARCH_PROMPT = _prompts["force_search"]
SYSTEM_PROMPT_SUFFIX = _prompts["system_suffix"]
DEEP_RESEARCH_PROMPT_TEMPLATE = _prompts["deep_research"]
DEEP_DIVE_PROMPT_TEMPLATE = _prompts["deep_dive"]


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
