"""LLM API client and token tracking logic."""

import json
import logging
import os
import requests
import time
from typing import Any, Callable, Dict, List, Optional


logger = logging.getLogger(__name__)


class UsageTracker:
    """Track token usage per model alias."""

    def __init__(self):
        # Format: {model_alias: {"input": int, "output": int}}
        self.usage: Dict[str, Dict[str, int]] = {}

    def add_usage(self, model_alias: str, input_tokens: int, output_tokens: int):
        if model_alias not in self.usage:
            self.usage[model_alias] = {"input": 0, "output": 0}
        self.usage[model_alias]["input"] += input_tokens
        self.usage[model_alias]["output"] += output_tokens

    def get_usage_breakdown(self, model_alias: str) -> Dict[str, int]:
        return self.usage.get(model_alias, {"input": 0, "output": 0})

    def record_tool_usage(self, tool_name: str):
        if not hasattr(self, "tools"):
            self.tools = {}
        self.tools[tool_name] = self.tools.get(tool_name, 0) + 1

    def get_tool_usage(self) -> Dict[str, int]:
        return getattr(self, "tools", {})


def count_tokens(messages: List[Dict[str, Any]]) -> int:
    """Naive token counting: chars / 4."""
    total_chars = 0
    for m in messages:
        content = m.get("content")
        if content:
            total_chars += len(content)
        # Also count tool calls and results
        tc = m.get("tool_calls")
        if tc:
            total_chars += len(json.dumps(tc))
    return total_chars // 4


def get_llm_msg(
    model_id: str,
    messages: List[Dict[str, Any]],
    use_tools: bool = True,
    verbose: bool = False,
    model_alias: Optional[str] = None,
    usage_tracker: Optional[UsageTracker] = None,
    tool_schemas: Optional[List[Dict[str, Any]]] = None,
    status_callback: Optional[Callable[[Optional[str]], None]] = None,
    parameters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Send messages to the LLM and get a response."""
    # Importing here to avoid circular dependencies during initialization
    from asky.config import (
        MODELS,
        LLM_USER_AGENT,
        REQUEST_TIMEOUT,
        MAX_RETRIES,
        INITIAL_BACKOFF,
        MAX_BACKOFF,
    )

    # Find the model config based on model_id
    model_config = next((m for m in MODELS.values() if m["id"] == model_id), None)

    url = ""
    headers = {
        "Content-Type": "application/json",
        "User-Agent": LLM_USER_AGENT,
    }

    if model_config and "base_url" in model_config:
        url = model_config["base_url"]

    api_key = None
    if model_config and "api_key" in model_config:
        api_key = model_config["api_key"]
    elif model_config and "api_key_env" in model_config:
        api_key_env_var = model_config["api_key_env"]
        api_key = os.environ.get(api_key_env_var)
        if not api_key:
            logger.info(
                f"Warning: {api_key_env_var} not found in environment variables."
            )

    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model_id,
        "messages": messages,
    }

    # Add generation parameters if provided
    if parameters:
        for key, value in parameters.items():
            if value is not None:
                payload[key] = value

    if use_tools:
        payload["tools"] = tool_schemas
        payload["tool_choice"] = "auto"

    current_backoff = INITIAL_BACKOFF

    logger.info(f"Sending request to LLM: {model_id}")
    # Log system messages separately
    for m in messages:
        if m.get("role") == "system":
            logger.debug(f"System Message: {m.get('content')}")

    def format_log_content(m: Dict[str, Any]) -> str:
        content = m.get("content") or ""
        if m.get("role") == "system" or verbose:
            return content
        if len(content) > 200:
            return content[:200] + "..."
        return content

    log_payload = {
        **payload,
        "messages": [{**m, "content": format_log_content(m)} for m in messages],
    }
    logger.debug(f"Payload: {json.dumps(log_payload)}")

    tokens_sent = count_tokens(messages)
    logger.info(f"[{model_alias or model_id}] Sent: {tokens_sent} tokens")

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(
                url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT
            )
            resp.raise_for_status()
            resp_json = resp.json()

            # Extract usage if available, otherwise use naive count
            usage = resp_json.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", tokens_sent)
            completion_tokens = usage.get("completion_tokens", 0)
            response_message = resp_json["choices"][0]["message"]
            logger.debug(f"Response message: {response_message}")
            if "completion_tokens" not in usage:
                completion_tokens = len(json.dumps(response_message)) // 4

            if usage_tracker and model_alias:
                usage_tracker.add_usage(model_alias, prompt_tokens, completion_tokens)

            # Clear any status message if we succeeded
            if status_callback:
                status_callback(None)

            return response_message
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 429:
                if attempt < MAX_RETRIES - 1:
                    retry_after = e.response.headers.get("Retry-After")
                    if retry_after:
                        try:
                            # Handle potential floating point strings (e.g. "5.0")
                            wait_time = int(float(retry_after))
                        except ValueError:
                            wait_time = current_backoff
                            current_backoff = min(current_backoff * 2, MAX_BACKOFF)
                    else:
                        wait_time = current_backoff
                        current_backoff = min(current_backoff * 2, MAX_BACKOFF)

                    msg = (
                        f"Rate limit exceeded (429). Retrying in {wait_time} seconds..."
                    )
                    logger.info(msg)
                    if status_callback:
                        status_callback(msg)

                    time.sleep(wait_time)
                    continue
            raise e
        except requests.exceptions.RequestException as e:
            if attempt < MAX_RETRIES - 1:
                logger.info(
                    f"Request error: {e}. Retrying in {current_backoff} seconds..."
                )
                time.sleep(current_backoff)
                current_backoff = min(current_backoff * 2, MAX_BACKOFF)
                continue
            raise e
    raise requests.exceptions.RequestException("Max retries exceeded")
