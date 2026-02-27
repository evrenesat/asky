"""HTTP data push execution logic for the push_data plugin."""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

from asky.config import MODELS

logger = logging.getLogger(__name__)

SPECIAL_VARIABLES = {"query", "answer", "timestamp", "model"}


def _resolve_field_value(
    key: str,
    value: Any,
    dynamic_args: Dict[str, str],
    special_vars: Dict[str, str],
) -> str:
    """Resolve a field value from config, environment, dynamic args, or special vars.

    Raises ValueError if a required parameter is missing.
    """
    if key.endswith("_env"):
        env_var_name = str(value)
        env_value = os.environ.get(env_var_name)
        if env_value is None:
            raise ValueError(f"Environment variable '{env_var_name}' not found")
        return env_value

    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        param_name = value[2:-1]
        if param_name in SPECIAL_VARIABLES:
            if param_name not in special_vars:
                raise ValueError(f"Special variable '{param_name}' not available")
            return special_vars[param_name]
        if param_name not in dynamic_args:
            raise ValueError(f"Missing required parameter: {param_name}")
        return dynamic_args[param_name]

    return str(value)


def _resolve_headers(headers_config: Dict[str, Any]) -> Dict[str, str]:
    """Resolve headers, substituting _env-suffixed keys from environment variables.

    Raises ValueError if an environment variable is missing.
    """
    resolved = {}
    for key, value in headers_config.items():
        if key.endswith("_env"):
            header_name = key[:-4]
            env_var_name = str(value)
            env_value = os.environ.get(env_var_name)
            if env_value is None:
                raise ValueError(f"Environment variable '{env_var_name}' not found")
            resolved[header_name] = env_value
        else:
            resolved[key] = str(value)
    return resolved


def _build_payload(
    fields_config: Dict[str, Any],
    dynamic_args: Dict[str, str],
    special_vars: Dict[str, str],
) -> Dict[str, str]:
    """Build request payload from field configuration.

    Raises ValueError if a required parameter is missing.
    """
    payload = {}
    for key, value in fields_config.items():
        resolved_value = _resolve_field_value(key, value, dynamic_args, special_vars)
        payload[key] = resolved_value
    return payload


def execute_push_data(
    endpoint_name: str,
    dynamic_args: Optional[Dict[str, str]] = None,
    query: Optional[str] = None,
    answer: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute a push_data request to a configured endpoint.

    Returns a result dict with ``success``, ``endpoint``, and either
    ``status_code`` or ``error``.
    """
    from asky.config import _CONFIG

    dynamic_args = dynamic_args or {}

    push_data_config = _CONFIG.get("push_data", {})
    if endpoint_name not in push_data_config:
        raise ValueError(f"Push data endpoint '{endpoint_name}' not found in configuration")

    endpoint_config = push_data_config[endpoint_name]

    url = endpoint_config.get("url")
    if not url:
        raise ValueError(f"Endpoint '{endpoint_name}' missing 'url' field")

    method = endpoint_config.get("method", "post").lower()
    if method not in ("get", "post"):
        raise ValueError(f"Endpoint '{endpoint_name}' has invalid method: {method}")

    special_vars: Dict[str, str] = {}
    if query is not None:
        special_vars["query"] = query
    if answer is not None:
        special_vars["answer"] = answer
    if model is not None:
        special_vars["model"] = model
    special_vars["timestamp"] = datetime.now(timezone.utc).isoformat()

    headers_config = endpoint_config.get("headers", {})
    try:
        headers = _resolve_headers(headers_config)
    except ValueError as e:
        logger.error("Failed to resolve headers for endpoint '%s': %s", endpoint_name, e)
        return {"success": False, "error": str(e), "endpoint": endpoint_name}

    fields_config = endpoint_config.get("fields", {})
    try:
        payload = _build_payload(fields_config, dynamic_args, special_vars)
    except ValueError as e:
        logger.error("Failed to build payload for endpoint '%s': %s", endpoint_name, e)
        return {"success": False, "error": str(e), "endpoint": endpoint_name}

    try:
        if method == "get":
            response = requests.get(url, params=payload, headers=headers, timeout=30)
        else:
            response = requests.post(url, json=payload, headers=headers, timeout=30)

        response.raise_for_status()
        logger.info("Successfully pushed data to '%s': %s", endpoint_name, response.status_code)
        return {
            "success": True,
            "endpoint": endpoint_name,
            "status_code": response.status_code,
            "url": url,
        }

    except requests.RequestException as e:
        logger.error("Failed to push data to '%s': %s", endpoint_name, e)
        return {"success": False, "error": str(e), "endpoint": endpoint_name, "url": url}


def get_enabled_endpoints() -> Dict[str, Dict[str, Any]]:
    """Return all push_data endpoints marked enabled in config."""
    from asky.config import _CONFIG

    push_data_config = _CONFIG.get("push_data", {})
    return {name: cfg for name, cfg in push_data_config.items() if cfg.get("enabled", False)}
