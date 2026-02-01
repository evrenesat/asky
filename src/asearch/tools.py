"""Tool execution functions for web search and URL content retrieval."""

import json
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List

from asearch.config import SEARXNG_URL, MODELS, SUMMARIZATION_MODEL
from asearch.html import HTMLStripper, strip_tags, strip_think_tags


# Track URLs that have been read in the current session
read_urls: List[str] = []


def reset_read_urls() -> None:
    """Reset the list of read URLs for a new session."""
    global read_urls
    read_urls = []


def execute_web_search(args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a web search using SearXNG."""
    q = args.get("q", "")
    count = args.get("count", 5)
    try:
        resp = requests.get(
            f"{SEARXNG_URL}/search",
            params={"q": q, "format": "json"},
            timeout=20,
        )
        resp.raise_for_status()
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
        return {"error": f"Search failed: {str(e)}"}


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


def fetch_single_url(
    url: str, max_chars: int, summarize: bool = False
) -> Dict[str, str]:
    """Fetch content from a single URL."""
    global read_urls
    if url in read_urls:
        return {url: "Error: Already read this URL."}
    try:
        resp = requests.get(url, timeout=20)
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

    # Support both single 'url' and list 'urls'
    if header_url:
        urls.append(header_url)

    # Deduplicate and filter empty
    urls = list(set([u for u in urls if u]))

    if not urls:
        return {"error": "No URLs provided."}

    results = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_url = {
            executor.submit(fetch_single_url, url, max_chars, summarize): url
            for url in urls
        }
        for future in as_completed(future_to_url):
            results.update(future.result())

    return results


def execute_get_url_details(args: Dict[str, Any], max_chars: int) -> Dict[str, Any]:
    """Fetch content and extract links from a URL."""
    url = args.get("url", "")
    global read_urls
    if url in read_urls:
        return {"error": "You have already read this URL."}
    read_urls.append(url)
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        s = HTMLStripper()
        s.feed(resp.text)
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
    return {"error": f"Unknown tool: {name}"}
