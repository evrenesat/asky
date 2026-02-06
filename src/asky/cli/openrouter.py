"""OpenRouter model catalog integration."""

from datetime import datetime, timedelta
from pathlib import Path
import os
import json
import requests
from importlib import resources
from typing import List, Dict, Any, Optional

# Supported parameters based on OpenRouter docs
KNOWN_PARAMETERS = {
    "temperature": {"type": "float", "min": 0.0, "max": 2.0, "default": 1.0},
    "top_p": {"type": "float", "min": 0.0, "max": 1.0, "default": 1.0},
    "top_k": {"type": "int", "min": 0, "default": 0},
    "max_tokens": {"type": "int", "min": 1},
    "frequency_penalty": {"type": "float", "min": -2.0, "max": 2.0, "default": 0.0},
    "presence_penalty": {"type": "float", "min": -2.0, "max": 2.0, "default": 0.0},
    "repetition_penalty": {"type": "float", "min": 0.0, "max": 2.0, "default": 1.0},
    "min_p": {"type": "float", "min": 0.0, "max": 1.0, "default": 0.0},
    "top_a": {"type": "float", "min": 0.0, "max": 1.0, "default": 0.0},
    "seed": {"type": "int"},
}


def get_cache_path() -> Path:
    """Return the cache file path."""
    cache_dir = Path.home() / ".config" / "asky" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "openrouter_models.json"


def is_cache_valid() -> bool:
    """Check if the cache exists and is less than 1 day old."""
    cache_path = get_cache_path()
    if not cache_path.exists():
        return False
    try:
        with open(cache_path) as f:
            data = json.load(f)
        fetched_at = datetime.fromisoformat(data.get("fetched_at", ""))
        return datetime.now() - fetched_at < timedelta(days=1)
    except (json.JSONDecodeError, ValueError, OSError):
        return False


def load_bundled_models() -> List[Dict[str, Any]]:
    """Load models from the bundled JSON file."""
    try:
        resource = resources.files("asky.data").joinpath("openrouter_models.json")
        with resource.open("rb") as f:
            data = json.load(f)
        return data.get("models", [])
    except Exception:
        return []


def fetch_models(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """Fetch models from OpenRouter API, using cache or bundle if needed."""
    cache_path = get_cache_path()

    # 1. Valid Cache (if not forced)
    if not force_refresh and is_cache_valid():
        try:
            with open(cache_path) as f:
                data = json.load(f)
            return data.get("models", [])
        except (json.JSONDecodeError, OSError):
            pass

    # 2. Try Fetch (only if API key is present)
    # We rely on OPENROUTER_API_KEY being set.
    api_key = os.environ.get("OPENROUTER_API_KEY")

    if api_key:
        try:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://github.com/evrenesat/asky",
                "X-Title": "Asky CLI",
            }
            response = requests.get(
                "https://openrouter.ai/api/v1/models", headers=headers, timeout=30
            )
            response.raise_for_status()
            models = response.json().get("data", [])

            # Save to cache
            cache_data = {"fetched_at": datetime.now().isoformat(), "models": models}
            with open(cache_path, "w") as f:
                json.dump(cache_data, f, indent=2)

            return models
        except Exception:
            # Fallback to stale/bundled if fetch fails
            pass

    # 3. Fallback: Stale Cache
    if cache_path.exists():
        try:
            with open(cache_path) as f:
                data = json.load(f)
            return data.get("models", [])
        except Exception:
            pass

    # 4. Fallback: Bundled Models
    return load_bundled_models()


def search_models(query: str, models: List[Dict]) -> List[Dict]:
    """Search models by name or id (case-insensitive)."""
    if not query:
        return models
    query_lower = query.lower()
    return [
        m
        for m in models
        if query_lower in m.get("id", "").lower()
        or query_lower in m.get("name", "").lower()
    ]


def get_model_parameters(model: Dict) -> List[str]:
    """Get the list of supported parameters for a model."""
    return model.get("supported_parameters", [])
