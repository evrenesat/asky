"""Tool execution functions for web search and URL content retrieval."""

import json
import os
import requests
import subprocess
import time
from datetime import datetime
from typing import Any, Dict, List

from asearch.config import (
    SEARXNG_URL,
    MODELS,
    SUMMARIZATION_MODEL,
    SEARCH_PROVIDER,
    SERPER_API_URL,
    SERPER_API_KEY_ENV,
    CUSTOM_TOOLS,
    USER_AGENT,
)
from asearch.html import HTMLStripper, strip_tags, strip_think_tags


# Track URLs that have been read in the current session
read_urls: List[str] = []


def reset_read_urls() -> None:
    """Reset the list of read URLs for a new session."""
    global read_urls
    read_urls = []


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
            timeout=20,
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
                    "snippet": strip_tags(x.get("content", ""))[:400],
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
            timeout=20,
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
                    "snippet": strip_tags(x.get("snippet", ""))[:400],
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


def summarize_text(text: str) -> str:
    """Summarize text using the defined summarization model."""
    # Import here to avoid circular dependency
    from asearch.llm import get_llm_msg

    if not text:
        return ""

    try:
        messages = [
            {
                "role": "system",
                "content": "You are a helpful assistant. Summarize the following text concisely, focusing on key facts.",
            },
            {
                "role": "user",
                "content": f"Text to summarize:\n\n{text[:50000]}",
            },
        ]

        model_id = MODELS[SUMMARIZATION_MODEL]["id"]
        msg = get_llm_msg(model_id, messages, tools=None)
        return strip_think_tags(msg.get("content", ""))
    except Exception as e:
        return f"[Error in summarization: {str(e)}]"


def _sanitize_url(url: str) -> str:
    """Remove artifacts like shell-escaped backslashes from URLs."""
    if not url:
        return ""
    # Remove backslashes which are often artifacts of shell-escaping parentheses or special chars
    return url.replace("\\", "")


def fetch_single_url(
    url: str, max_chars: int, summarize: bool = False
) -> Dict[str, str]:
    """Fetch content from a single URL."""
    url = _sanitize_url(url)
    global read_urls
    if url in read_urls:
        return {url: "Error: Already read this URL."}
    try:
        headers = {"User-Agent": USER_AGENT}
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        content = strip_tags(resp.text)

        if summarize:
            content = f"Summary of {url}:\n" + summarize_text(content)
        else:
            content = content[:max_chars]

        read_urls.append(url)
        return {url: content}
    except Exception as e:
        return {url: f"Error: {str(e)}"}


def execute_get_url_content(
    args: Dict[str, Any], max_chars: int, summarize: bool
) -> Dict[str, Any]:
    """Fetch content from one or more URLs."""
    header_url = args.get("url")
    urls = args.get("urls", [])

    # LLM can override the global summarize flag in its tool call
    effective_summarize = args.get("summarize", summarize)

    # Support both single 'url' and list 'urls'
    if header_url:
        urls.append(header_url)

    # Deduplicate and filter empty
    urls = list(set([u for u in urls if u]))

    if not urls:
        return {"error": "No URLs provided."}

    results = {}
    for i, url in enumerate(urls):
        if i > 0 and effective_summarize:
            # Small delay between summarizations to avoid hitting RPM limits
            time.sleep(1)
        results.update(fetch_single_url(url, max_chars, effective_summarize))

    return results


def execute_get_url_details(args: Dict[str, Any], max_chars: int) -> Dict[str, Any]:
    """Fetch content and extract links from a URL."""
    url = _sanitize_url(args.get("url", ""))
    global read_urls
    if url in read_urls:
        return {"error": "You have already read this URL."}
    try:
        headers = {"User-Agent": USER_AGENT}
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        s = HTMLStripper()
        s.feed(resp.text)

        # Mark as read only after successful fetch
        read_urls.append(url)

        return {
            "content": s.get_data()[:max_chars],
            "links": s.get_links()[:50],  # Limit links to avoid context overflow
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

        print(f"Executing custom tool command: {cmd_str}")
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


def dispatch_tool_call(
    call: Dict[str, Any], max_chars: int, summarize: bool
) -> Dict[str, Any]:
    """Dispatch a tool call to the appropriate executor."""
    func = call["function"]
    name = func["name"]
    args = json.loads(func["arguments"]) if func.get("arguments") else {}
    print(f"Dispatching tool call: {name} with args {args}")
    if name == "web_search":
        return execute_web_search(args)
    if name == "get_url_content":
        return execute_get_url_content(args, max_chars, summarize)
    if name == "get_url_details":
        return execute_get_url_details(args, max_chars)
    if name == "get_date_time":
        return execute_get_date_time()

    if name in CUSTOM_TOOLS:
        return _execute_custom_tool(name, args)

    return {"error": f"Unknown tool: {name}"}
