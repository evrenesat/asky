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
    """Load configuration from TOML files, falling back to defaults."""
    config_dir = _get_config_dir()

    # Ensure config directory exists
    config_dir.mkdir(parents=True, exist_ok=True)

    # Define the list of config files to load
    config_files = [
        "general.toml",
        "api.toml",
        "prompts.toml",
        "user.toml",
        "plugins.toml",
        "xmpp.toml",
        "push_data.toml",
        "research.toml",
        "models.toml",
        "memory.toml",
    ]

    final_config: Dict[str, Any] = {
        "general": {},
        "api": {},
        "models": {},
        "prompts": {},
        "user_prompts": {},
        "tool": {},
        "email": {},
        "push_data": {},
        "research": {},
        "memory": {},
        "xmpp": {},
        "command_presets": {},
    }

    # Helper to merge dictionaries
    def merge(base, update):
        for k, v in update.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                merge(base[k], v)
            else:
                base[k] = v

    # 1. Load defaults from package resource files and copy to user config if missing
    for filename in config_files:
        try:
            # Get resource file path
            resource_path = resources.files("asky.data.config").joinpath(filename)
            user_file_path = config_dir / filename

            # Load default content
            with resource_path.open("rb") as f:
                file_config = tomllib.load(f)
                merge(final_config, file_config)

            # Copy to user directory if it doesn't exist
            if not user_file_path.exists():
                try:
                    with resources.as_file(resource_path) as source_path:
                        shutil.copy(source_path, user_file_path)
                    print(
                        f"Created default configuration {filename} at {user_file_path}"
                    )
                except Exception as e:
                    print(f"Warning: Failed to create default config {filename}: {e}")

        except Exception as e:
            print(f"Warning: Failed to load bundled config {filename}: {e}")

    # 2. Load user split config files
    for filename in config_files:
        user_file_path = config_dir / filename
        if user_file_path.exists():
            try:
                with open(user_file_path, "rb") as f:
                    file_config = tomllib.load(f)
                    merge(final_config, file_config)
            except tomllib.TOMLDecodeError as e:
                import sys

                print(
                    f"Error: Invalid configuration file at {user_file_path}",
                    file=sys.stderr,
                )
                print(f"Details: {e}", file=sys.stderr)
                # Don't exit here, attempt to continue loading other files or proceed with valid parts?
                # For now, exit to alert user something is wrong
                sys.exit(1)
            except Exception as e:
                print(f"Warning: Failed to load config from {user_file_path}: {e}")

    # 3. Load legacy config.toml for backward compatibility (overrides split files)
    legacy_config_path = config_dir / "config.toml"
    if legacy_config_path.exists():
        try:
            with open(legacy_config_path, "rb") as f:
                legacy_config = tomllib.load(f)
                merge(final_config, legacy_config)
            print(f"Loaded legacy config from {legacy_config_path}")
        except Exception as e:
            print(f"Warning: Failed to load legacy config: {e}")

    return _hydrate_models(final_config)
