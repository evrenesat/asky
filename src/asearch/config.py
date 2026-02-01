"""Configuration constants and static declarations for asearch."""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    load_dotenv(dotenv_path=env_path, override=True)
except ImportError:
    pass


# --- Database Configuration ---
DB_PATH = Path(
    os.environ.get(
        "SEARXNG_HISTORY_DB_PATH",
        Path(__file__).resolve().parent.parent.parent / "data" / "history.db",
    )
)
QUERY_SUMMARY_MAX_CHARS = 40
ANSWER_SUMMARY_MAX_CHARS = 200


# --- API Configuration ---
LMSTUDIO = "http://localhost:1234/v1/chat/completions"
SEARXNG_URL = "http://localhost:8888"
MAX_TURNS = 20


# --- Model Definitions ---
MODELS = {
    "q34t": {
        "id": "qwen/qwen3-4b-thinking-2507",
        "max_chars": 4000,
        "context_size": 32000,
    },
    "q34": {"id": "qwen/qwen3-4b-2507", "max_chars": 4000, "context_size": 32000},
    "lfm": {"id": "liquid/lfm2.5-1.2b", "max_chars": 100000, "context_size": 32000},
    "q8": {"id": "qwen/qwen3-8b", "max_chars": 4000, "context_size": 32000},
    "q30": {"id": "qwen/qwen3-30b-a3b-2507", "max_chars": 3000, "context_size": 32000},
    "gf": {
        "id": "gemini-flash-latest",
        "max_chars": 1000000,
        "base_url": "https://generativelanguage.googleapis.com/v1beta/chat/completions",
        "api_key_env": "GOOGLE_API_KEY",
        "context_size": 1000000,
    },
}

DEFAULT_MODEL = "gf"
SUMMARIZATION_MODEL = "lfm"


# --- Tool Definitions ---
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


# --- System Prompts ---
SYSTEM_PROMPT = (
    "You are a helpful assistant with web searc and URL retrieval capabilities. "
    "Use get_date_time for current date/time if needed (e.g., for 'today' or 'recently'). "
)

FORCE_SEARCH_PROMPT = "Unless you are asked to use a specific URL, always use web_search, never try to answer without using web_search. "

SYSTEM_PROMPT_SUFFIX = (
    "Then use get_url_content for details of the search results. "
    "You can pass a list of URLs to get_url_content to fetch multiple pages efficiently at once. "
    "Use tools, don't say you can't."
    "You have {MAX_TURNS} turns to complete your task, if you reach the limit, process will be terminated."
    "You should finish your task before reaching %100 of your token limit."
)

DEEP_RESEARCH_PROMPT_TEMPLATE = (
    "\nYou are in DEEP RESEARCH mode. You MUST perform at least {n} "
    "distinct web searches, or make {n} get_url_content calls to gather comprehensive information before providing a final answer."
    "If you need to get links from a URL, use get_url_details. If you just need to get content from a URL, use get_url_content."
)

DEEP_DIVE_PROMPT_TEMPLATE = (
    "\nYou are in DEEP DIVE mode. Follow these instructions:\n"
    "1. Use 'get_url_details' for the INITIAL page to retrieve content and links.\n"
    "2. Follow up to 25 relevant links within the same domain to gather comprehensive information.\n"
    "3. IMPORTANT: Use 'get_url_details' ONLY for the first page. Use 'get_url_content' for all subsequent links.\n"
    "4. Do not rely on your internal knowledge; base your answer strictly on the retrieved content."
    "5. Do not use web_search in deep dive mode."
)
