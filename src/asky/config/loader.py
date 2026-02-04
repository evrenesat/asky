"""Configuration loading and hydration logic."""

import copy
import os
import shutil
import tomllib
from importlib import resources
from pathlib import Path
from typing import Any, Dict


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
                    "context_size": 4096,
                }
            },
            "prompts": {
                "system_prefix": "",
                "system_suffix": "",
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

        except tomllib.TOMLDecodeError as e:
            import sys

            print(
                f"Error: Invalid configuration file at {config_path}", file=sys.stderr
            )
            print(f"Details: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Warning: Failed to load config from {config_path}: {e}")

    return _hydrate_models(final_config)
