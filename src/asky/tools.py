"""Tool execution functions for web search and URL content retrieval."""

import json
import logging
import os
import subprocess
from datetime import datetime
from typing import Any, Dict

import requests

from asky.config import (
    CUSTOM_TOOLS,
    SEARCH_PROVIDER,
    SEARXNG_URL,
    SERPER_API_KEY_ENV,
    SERPER_API_URL,
    USER_AGENT,
    MAX_URL_DETAIL_LINKS,
    SEARCH_SNIPPET_MAX_CHARS,
    SEARCH_TIMEOUT,
    FETCH_TIMEOUT,
)
from asky.html import HTMLStripper, strip_tags

logger = logging.getLogger(__name__)


def _execute_searxng_search(q: str, count: int) -> Dict[str, Any]:
    """Execute a web search using SearXNG."""
    # Ensure no trailing slash on SEARXNG_URL
    base_url = SEARXNG_URL.rstrip("/")
    try:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        resp = requests.get(
            f"{base_url}/search",
            params={"q": q, "format": "json"},
            headers=headers,
            timeout=SEARCH_TIMEOUT,
        )
        if resp.status_code != 200:
            return {"error": f"SearXNG error {resp.status_code}: {resp.text[:200]}"}

        data = resp.json()
        results = []
        for x in data.get("results", [])[:count]:
            results.append(
                {
                    "title": strip_tags(x.get("title", "")),
                    "url": x.get("url"),
                    "snippet": strip_tags(x.get("content", ""))[
                        :SEARCH_SNIPPET_MAX_CHARS
                    ],
                    "engine": x.get("engine"),
                }
            )
        return {"results": results}
    except Exception as e:
        return {"error": f"SearXNG search failed: {str(e)}"}


def _execute_serper_search(q: str, count: int) -> Dict[str, Any]:
    """Execute a web search using Serper API."""
    api_key = os.environ.get(SERPER_API_KEY_ENV)
    if not api_key:
        return {
            "error": f"Serper API key not found in environment variable {SERPER_API_KEY_ENV}"
        }

    try:
        headers = {
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
        }
        payload = json.dumps({"q": q, "num": count})
        resp = requests.post(
            SERPER_API_URL,
            headers=headers,
            data=payload,
            timeout=SEARCH_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        # Support both 'organic' and 'knowledgeGraph' if present
        for x in data.get("organic", [])[:count]:
            results.append(
                {
                    "title": strip_tags(x.get("title", "")),
                    "url": x.get("link"),
                    "snippet": strip_tags(x.get("snippet", ""))[
                        :SEARCH_SNIPPET_MAX_CHARS
                    ],
                    "engine": "serper",
                }
            )
        return {"results": results}
    except Exception as e:
        return {"error": f"Serper search failed: {str(e)}"}


def execute_web_search(args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a web search using the configured provider."""
    q = args.get("q", "")
    count = args.get("count", 5)

    if SEARCH_PROVIDER == "serper":
        return _execute_serper_search(q, count)
    else:
        return _execute_searxng_search(q, count)


def _sanitize_url(url: str) -> str:
    """Remove artifacts like shell-escaped backslashes from URLs."""
    if not url:
        return ""
    # Remove backslashes which are often artifacts of shell-escaping parentheses or special chars
    return url.replace("\\", "")


def fetch_single_url(url: str) -> Dict[str, str]:
    """Fetch content from a single URL."""
    url = _sanitize_url(url)

    try:
        headers = {"User-Agent": USER_AGENT}
        resp = requests.get(url, headers=headers, timeout=FETCH_TIMEOUT)
        resp.raise_for_status()
        content = strip_tags(resp.text)
        return {url: content}
    except Exception as e:
        return {url: f"Error: {str(e)}"}


def execute_get_url_content(args: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch content from one or more URLs."""
    header_url = args.get("url")
    urls = args.get("urls", [])
    # Support both single 'url' and list 'urls'
    if header_url:
        urls.append(header_url)
    # Deduplicate and filter empty
    urls = list(set([u for u in urls if u]))
    if not urls:
        return {"error": "No URLs provided."}
    results = {}
    for i, url in enumerate(urls):
        results.update(fetch_single_url(url))
    return results


def execute_get_url_details(args: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch content and extract links from a URL."""
    url = _sanitize_url(args.get("url", ""))

    try:
        headers = {"User-Agent": USER_AGENT}
        resp = requests.get(url, headers=headers, timeout=FETCH_TIMEOUT)
        resp.raise_for_status()
        s = HTMLStripper(base_url=url)
        s.feed(resp.text)

        return {
            "content": s.get_data(),
            "links": s.get_links()[
                :MAX_URL_DETAIL_LINKS
            ],  # Limit links to avoid context overflow
            "system_note": "IMPORTANT: Do NOT use get_url_details again. Use get_url_content to read links.",
        }
    except Exception as e:
        return {"error": f"Failed to fetch details: {str(e)}"}


def execute_get_date_time() -> Dict[str, Any]:
    """Return the current date and time."""
    return {"date_time": datetime.now().isoformat()}


def _execute_custom_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a custom tool defined in config.toml."""
    tool_cfg = CUSTOM_TOOLS.get(name)
    if not tool_cfg:
        return {"error": f"Custom tool configuration for '{name}' not found."}

    cmd_base = tool_cfg.get("command", "")
    if not cmd_base:
        return {"error": f"No command defined for custom tool '{name}'."}

    # Prepare arguments:
    # 1. Get defaults from config
    props = tool_cfg.get("parameters", {}).get("properties", {})
    processed_args = {}

    # 2. Merge defaults with provided args
    # Note: LLM might already handle defaults, but we ensure it here
    for k, p in props.items():
        val = args.get(k)
        if val is None:
            val = p.get("default")

        if val is not None:
            # Remove existing double quotes and wrap in new ones
            clean_val = str(val).replace('"', "")
            processed_args[k] = f'"{clean_val}"'

    try:
        # Check if the command uses placeholders
        if "{" in cmd_base and "}" in cmd_base:
            try:
                cmd_str = cmd_base.format(**processed_args)
            except KeyError as e:
                return {"error": f"Missing parameter required by command template: {e}"}
        else:
            # Append arguments in order of appearance in properties mapping
            arg_list = []
            for k in props.keys():
                if k in processed_args:
                    arg_list.append(processed_args[k])

            cmd_str = f"{cmd_base} {' '.join(arg_list)}".strip()

        logger.info(f"Executing custom tool command: {cmd_str}")
        result = subprocess.run(
            cmd_str, shell=True, capture_output=True, text=True, timeout=30
        )

        return {
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "exit_code": result.returncode,
        }
    except Exception as e:
        return {"error": f"Failed to execute custom tool '{name}': {str(e)}"}
