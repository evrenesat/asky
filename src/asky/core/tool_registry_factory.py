"""Factory helpers for default and research tool registries."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Set

from rich.panel import Panel

from asky import summarization
from asky.config import (
    ANSWER_SUMMARY_MAX_CHARS,
    CUSTOM_TOOLS,
    SUMMARIZE_ANSWER_PROMPT_TEMPLATE,
)
from asky.core.api_client import UsageTracker, get_llm_msg
from asky.core.registry import ToolRegistry
from asky.lazy_imports import call_attr, load_module
from asky.research.tools import ACQUISITION_TOOL_NAMES

ToolExecutor = Callable[[Dict[str, Any]], Dict[str, Any]]
CustomToolExecutor = Callable[[str, Dict[str, Any]], Dict[str, Any]]
ResearchBindingsLoader = Callable[[], Dict[str, Any]]


def _execute_web_search(args: Dict[str, Any]) -> Dict[str, Any]:
    return call_attr("asky.tools", "execute_web_search", args)


def _execute_get_url_content(args: Dict[str, Any]) -> Dict[str, Any]:
    return call_attr("asky.tools", "execute_get_url_content", args)


def _execute_get_url_details(args: Dict[str, Any]) -> Dict[str, Any]:
    return call_attr("asky.tools", "execute_get_url_details", args)


def _execute_custom_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    return call_attr("asky.tools", "_execute_custom_tool", name, args)


def _default_research_bindings_loader() -> Dict[str, Any]:
    tools_module = load_module("asky.research.tools")
    return {
        "schemas": getattr(tools_module, "RESEARCH_TOOL_SCHEMAS"),
        "extract_links": getattr(tools_module, "execute_extract_links"),
        "get_link_summaries": getattr(tools_module, "execute_get_link_summaries"),
        "get_relevant_content": getattr(tools_module, "execute_get_relevant_content"),
        "get_full_content": getattr(tools_module, "execute_get_full_content"),
        "save_finding": getattr(tools_module, "execute_save_finding"),
        "query_research_memory": getattr(tools_module, "execute_query_research_memory"),
    }


def _is_tool_enabled(tool_name: str, disabled_tools: Set[str]) -> bool:
    """Return True when a tool is not excluded by runtime CLI options."""
    return tool_name not in disabled_tools


def create_tool_registry(
    usage_tracker: Optional[UsageTracker] = None,
    summarization_tracker: Optional[UsageTracker] = None,
    summarization_status_callback: Optional[Callable[[Optional[str]], None]] = None,
    summarization_verbose_callback: Optional[Callable[[Any], None]] = None,
    execute_web_search_fn: Optional[ToolExecutor] = None,
    execute_get_url_content_fn: Optional[ToolExecutor] = None,
    execute_get_url_details_fn: Optional[ToolExecutor] = None,
    execute_custom_tool_fn: Optional[CustomToolExecutor] = None,
    custom_tools: Optional[Dict[str, Any]] = None,
    disabled_tools: Optional[Set[str]] = None,
) -> ToolRegistry:
    """Create a ToolRegistry with all default and custom tools."""
    registry = ToolRegistry()
    web_search_executor = execute_web_search_fn or _execute_web_search
    get_url_content_executor = execute_get_url_content_fn or _execute_get_url_content
    get_url_details_executor = execute_get_url_details_fn or _execute_get_url_details
    custom_tool_executor = execute_custom_tool_fn or _execute_custom_tool
    active_custom_tools = custom_tools if custom_tools is not None else CUSTOM_TOOLS
    excluded_tools = disabled_tools or set()

    if _is_tool_enabled("web_search", excluded_tools):
        registry.register(
            "web_search",
            {
                "name": "web_search",
                "description": "Search the web and return top results.",
                "system_prompt_guideline": "Use for discovery of relevant sources before deep content fetches.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "q": {"type": "string"},
                        "count": {"type": "integer", "default": 5},
                    },
                    "required": ["q"],
                },
            },
            web_search_executor,
        )

    def url_content_executor(
        args: Dict[str, Any],
        summarize: bool = False,
    ) -> Dict[str, Any]:
        result = get_url_content_executor(args)
        effective_summarize = args.get("summarize", summarize)
        if effective_summarize:
            content_items = list(result.items())
            total_urls = len(content_items)
            for url_index, (url, content) in enumerate(content_items, start=1):
                if not content.startswith("Error:"):

                    def summary_progress(payload: Dict[str, Any]) -> None:
                        stage = str(payload.get("stage", "single"))
                        call_index = int(payload.get("call_index", 0) or 0)
                        call_total = int(payload.get("call_total", 0) or 0)
                        input_chars = int(payload.get("input_chars", 0) or 0)
                        output_chars = int(payload.get("output_chars", 0) or 0)
                        elapsed_ms = float(payload.get("elapsed_ms", 0.0) or 0.0)
                        status_msg = (
                            f"Summarizer: URL {url_index}/{total_urls} "
                            f"{stage} {call_index}/{call_total} "
                            f"(in {input_chars:,}, out {output_chars:,}, {elapsed_ms:.0f}ms)"
                        )
                        if summarization_status_callback:
                            summarization_status_callback(status_msg)

                    summary_text = summarization._summarize_content(
                        content=content,
                        prompt_template=SUMMARIZE_ANSWER_PROMPT_TEMPLATE,
                        max_output_chars=ANSWER_SUMMARY_MAX_CHARS,
                        get_llm_msg_func=get_llm_msg,
                        usage_tracker=summarization_tracker,
                        progress_callback=summary_progress,
                    )
                    result[url] = f"Summary of {url}:\n" + summary_text

                    if summarization_verbose_callback:
                        input_chars = len(content)
                        output_chars = len(summary_text)
                        ratio = (output_chars / input_chars) if input_chars > 0 else 0.0
                        summarization_verbose_callback(
                            Panel(
                                "\n".join(
                                    [
                                        f"URL: {url}",
                                        f"Input chars: {input_chars:,}",
                                        f"Summary chars: {output_chars:,}",
                                        f"Compression ratio: {ratio:.3f}",
                                    ]
                                ),
                                title=f"Summarization Stats {url_index}/{total_urls}",
                                border_style="magenta",
                                expand=False,
                            )
                        )
            if summarization_status_callback:
                summarization_status_callback(None)
        return result

    if _is_tool_enabled("get_url_content", excluded_tools):
        registry.register(
            "get_url_content",
            {
                "name": "get_url_content",
                "description": "Fetch one or more URLs and return extracted main content in lightweight markdown.",
                "system_prompt_guideline": "Use after discovery to read the primary content of selected pages.",
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
            url_content_executor,
        )

    if _is_tool_enabled("get_url_details", excluded_tools):
        registry.register(
            "get_url_details",
            {
                "name": "get_url_details",
                "description": "Fetch extracted main content plus discovered links from a URL.",
                "system_prompt_guideline": "Use when you need both page body and outgoing links from a single URL.",
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            },
            get_url_details_executor,
        )

    for tool_name, tool_data in active_custom_tools.items():
        if not tool_data.get("enabled", True):
            continue
        if not _is_tool_enabled(tool_name, excluded_tools):
            continue
        registry.register(
            tool_name,
            {
                "name": tool_name,
                "description": tool_data.get(
                    "description", f"Custom tool: {tool_name}"
                ),
                "system_prompt_guideline": tool_data.get("system_prompt_guideline", ""),
                "parameters": tool_data.get(
                    "parameters", {"type": "object", "properties": {}}
                ),
            },
            lambda args, name=tool_name: custom_tool_executor(name, args),
        )

    from asky.push_data import execute_push_data, get_enabled_endpoints

    for endpoint_name, endpoint_config in get_enabled_endpoints().items():
        fields_config = endpoint_config.get("fields", {})
        properties = {}
        required = []

        for key, value in fields_config.items():
            if (
                isinstance(value, str)
                and value.startswith("${")
                and value.endswith("}")
            ):
                param_name = value[2:-1]
                if param_name not in {"query", "answer", "timestamp", "model"}:
                    properties[param_name] = {
                        "type": "string",
                        "description": f"Value for {param_name}",
                    }
                    required.append(param_name)

        def make_push_executor(ep_name: str):
            def push_executor(args: Dict[str, Any]) -> Dict[str, Any]:
                return execute_push_data(ep_name, dynamic_args=args)

            return push_executor

        tool_name = f"push_data_{endpoint_name}"
        description = endpoint_config.get(
            "description", f"Push data to {endpoint_name}"
        )
        if not _is_tool_enabled(tool_name, excluded_tools):
            continue
        registry.register(
            tool_name,
            {
                "name": tool_name,
                "description": description,
                "system_prompt_guideline": endpoint_config.get(
                    "system_prompt_guideline",
                    "Use only after the final answer is complete and data is ready to publish.",
                ),
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
            make_push_executor(endpoint_name),
        )

    return registry


def create_research_tool_registry(
    usage_tracker: Optional[UsageTracker] = None,
    execute_web_search_fn: Optional[ToolExecutor] = None,
    execute_custom_tool_fn: Optional[CustomToolExecutor] = None,
    load_research_tool_bindings_fn: Optional[ResearchBindingsLoader] = None,
    custom_tools: Optional[Dict[str, Any]] = None,
    disabled_tools: Optional[Set[str]] = None,
    session_id: Optional[str] = None,
    corpus_preloaded: bool = False,
) -> ToolRegistry:
    """Create a ToolRegistry with research mode tools."""
    registry = ToolRegistry()
    web_search_executor = execute_web_search_fn or _execute_web_search
    custom_tool_executor = execute_custom_tool_fn or _execute_custom_tool
    active_custom_tools = custom_tools if custom_tools is not None else CUSTOM_TOOLS
    excluded_tools = disabled_tools or set()
    if corpus_preloaded:
        excluded_tools = excluded_tools | ACQUISITION_TOOL_NAMES

    load_research_tool_bindings = (
        load_research_tool_bindings_fn or _default_research_bindings_loader
    )

    if _is_tool_enabled("web_search", excluded_tools):
        registry.register(
            "web_search",
            {
                "name": "web_search",
                "description": "Search the web and return top results. Use this to find relevant sources for your research.",
                "system_prompt_guideline": "Use for broad discovery and to refresh candidate sources as research evolves.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "q": {"type": "string", "description": "Search query"},
                        "count": {
                            "type": "integer",
                            "default": 5,
                            "description": "Number of results",
                        },
                    },
                    "required": ["q"],
                },
            },
            web_search_executor,
        )

    research_bindings = load_research_tool_bindings()
    schemas = research_bindings["schemas"]

    def _execute_with_session_context(
        executor: ToolExecutor,
    ) -> ToolExecutor:
        if session_id is None:
            return executor

        def _wrapped(args: Dict[str, Any]) -> Dict[str, Any]:
            if "session_id" in args:
                return executor(args)
            enriched_args = dict(args)
            enriched_args["session_id"] = session_id
            return executor(enriched_args)

        return _wrapped

    for schema in schemas:
        tool_name = schema["name"]
        if not _is_tool_enabled(tool_name, excluded_tools):
            continue
        if tool_name == "extract_links":
            registry.register(tool_name, schema, research_bindings["extract_links"])
        elif tool_name == "get_link_summaries":
            registry.register(
                tool_name,
                schema,
                research_bindings["get_link_summaries"],
            )
        elif tool_name == "get_relevant_content":
            registry.register(
                tool_name,
                schema,
                research_bindings["get_relevant_content"],
            )
        elif tool_name == "get_full_content":
            registry.register(tool_name, schema, research_bindings["get_full_content"])
        elif tool_name == "save_finding":
            registry.register(
                tool_name,
                schema,
                _execute_with_session_context(research_bindings["save_finding"]),
            )
        elif tool_name == "query_research_memory":
            registry.register(
                tool_name,
                schema,
                _execute_with_session_context(
                    research_bindings["query_research_memory"]
                ),
            )

    for tool_name, tool_data in active_custom_tools.items():
        if not tool_data.get("enabled", True):
            continue
        if not _is_tool_enabled(tool_name, excluded_tools):
            continue
        registry.register(
            tool_name,
            {
                "name": tool_name,
                "description": tool_data.get(
                    "description", f"Custom tool: {tool_name}"
                ),
                "system_prompt_guideline": tool_data.get("system_prompt_guideline", ""),
                "parameters": tool_data.get(
                    "parameters", {"type": "object", "properties": {}}
                ),
            },
            lambda args, name=tool_name: custom_tool_executor(name, args),
        )

    return registry
