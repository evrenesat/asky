"""Tool execution functions for web search and URL content retrieval."""

import json
import logging
import os
import subprocess
from typing import Any, Dict, List

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
)
from asky.html import strip_tags
from asky.retrieval import fetch_url_document
from asky.url_utils import is_http_url, is_local_filesystem_target, sanitize_url

logger = logging.getLogger(__name__)
LOCAL_TARGET_UNSUPPORTED_ERROR = (
    "Local filesystem targets are not supported by this tool. "
    "Use an explicit local-source tool instead."
)
HTTP_URL_REQUIRED_ERROR = "Only HTTP(S) URLs are supported by this tool."


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
    return sanitize_url(url)


def fetch_single_url(url: str) -> Dict[str, str]:
    """Fetch content from a single URL."""
    sanitized_url = _sanitize_url(url)
    if is_local_filesystem_target(sanitized_url):
        return {sanitized_url: f"Error: {LOCAL_TARGET_UNSUPPORTED_ERROR}"}
    if not is_http_url(sanitized_url):
        return {sanitized_url: f"Error: {HTTP_URL_REQUIRED_ERROR}"}
    payload = fetch_url_document(sanitized_url, output_format="markdown")
    if payload.get("error"):
        return {sanitized_url: f"Error: {payload['error']}"}
    return {sanitized_url: str(payload.get("content", ""))}


def execute_get_url_content(args: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch content from one or more URLs."""
    header_url = args.get("url")
    urls: List[str] = args.get("urls", [])
    if isinstance(urls, str):
        urls = [urls]
    # Support both single 'url' and list 'urls'
    merged_urls: List[str] = []
    if header_url:
        merged_urls.append(str(header_url))
    merged_urls.extend([str(url) for url in urls if url])

    # Deduplicate while preserving first-seen order.
    seen = set()
    deduped_urls: List[str] = []
    for url in merged_urls:
        sanitized_url = _sanitize_url(url)
        if not sanitized_url or sanitized_url in seen:
            continue
        seen.add(sanitized_url)
        deduped_urls.append(sanitized_url)

    urls = deduped_urls
    if not urls:
        return {"error": "No URLs provided."}
    results = {}
    for url in urls:
        results.update(fetch_single_url(url))
    return results


def execute_get_url_details(args: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch content and extract links from a URL."""
    url = _sanitize_url(args.get("url", ""))
    if not url:
        return {"error": "Failed to fetch details: URL is empty."}
    if is_local_filesystem_target(url):
        return {"error": f"Failed to fetch details: {LOCAL_TARGET_UNSUPPORTED_ERROR}"}
    if not is_http_url(url):
        return {"error": f"Failed to fetch details: {HTTP_URL_REQUIRED_ERROR}"}

    payload = fetch_url_document(
        url=url,
        output_format="markdown",
        include_links=True,
        max_links=MAX_URL_DETAIL_LINKS,
    )
    if payload.get("error"):
        return {"error": f"Failed to fetch details: {payload['error']}"}

    return {
        "content": payload.get("content", ""),
        "links": payload.get("links", [])[
            :MAX_URL_DETAIL_LINKS
        ],  # Limit links to avoid context overflow
        "title": payload.get("title", ""),
        "date": payload.get("date"),
        "final_url": payload.get("final_url", url),
        "system_note": "IMPORTANT: Do NOT use get_url_details again. Use get_url_content to read links.",
    }


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
