"""Factory helpers for default and research tool registries."""

from __future__ import annotations

import inspect
from typing import Any, Callable, Dict, Optional, Set

from rich.panel import Panel

from asky import summarization
from asky.config import (
    ANSWER_SUMMARY_MAX_CHARS,
    CUSTOM_TOOLS,
    SUMMARIZE_ANSWER_PROMPT_TEMPLATE,
    TOOL_PROMPT_OVERRIDES,
)
from asky.core.api_client import UsageTracker, get_llm_msg
from asky.core.registry import ToolRegistry
from asky.lazy_imports import call_attr, load_module
from asky.plugins.hook_types import TOOL_REGISTRY_BUILD, ToolRegistryBuildContext
from asky.plugins.hooks import HookRegistry
from asky.research.tools import ACQUISITION_TOOL_NAMES

ToolExecutor = Callable[[Dict[str, Any]], Dict[str, Any]]
CustomToolExecutor = Callable[[str, Dict[str, Any]], Dict[str, Any]]
ResearchBindingsLoader = Callable[[], Dict[str, Any]]
TraceCallback = Callable[[Dict[str, Any]], None]
LOCAL_CORPUS_ONLY_RESEARCH_TOOLS = frozenset({"list_sections", "summarize_section"})


def _execute_web_search(
    args: Dict[str, Any],
    trace_callback: Optional[TraceCallback] = None,
) -> Dict[str, Any]:
    return call_attr(
        "asky.tools",
        "execute_web_search",
        args,
        trace_callback=trace_callback,
    )


def _execute_get_url_content(
    args: Dict[str, Any],
    trace_callback: Optional[TraceCallback] = None,
) -> Dict[str, Any]:
    return call_attr(
        "asky.tools",
        "execute_get_url_content",
        args,
        trace_callback=trace_callback,
    )


def _execute_get_url_details(
    args: Dict[str, Any],
    trace_callback: Optional[TraceCallback] = None,
) -> Dict[str, Any]:
    return call_attr(
        "asky.tools",
        "execute_get_url_details",
        args,
        trace_callback=trace_callback,
    )


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
        "list_sections": getattr(tools_module, "execute_list_sections"),
        "summarize_section": getattr(tools_module, "execute_summarize_section"),
        "save_finding": getattr(tools_module, "execute_save_finding"),
        "query_research_memory": getattr(tools_module, "execute_query_research_memory"),
    }


def _is_tool_enabled(tool_name: str, disabled_tools: Set[str]) -> bool:
    """Return True when a tool is not excluded by runtime CLI options."""
    return tool_name not in disabled_tools


def _executor_supports_trace_callback(executor: Callable[..., Any]) -> bool:
    """Return True when executor signature accepts trace_callback."""
    try:
        return "trace_callback" in inspect.signature(executor).parameters
    except (TypeError, ValueError):
        return False


def _apply_tool_prompt_overrides(
    tool_name: str,
    schema: Dict[str, Any],
) -> Dict[str, Any]:
    """Apply optional description/guideline overrides from config."""
    overrides = TOOL_PROMPT_OVERRIDES.get(tool_name, {})
    if not isinstance(overrides, dict):
        return schema

    patched = dict(schema)
    description = overrides.get("description")
    if isinstance(description, str) and description.strip():
        patched["description"] = description.strip()

    guideline = overrides.get("system_prompt_guideline")
    if isinstance(guideline, str) and guideline.strip():
        patched["system_prompt_guideline"] = guideline.strip()

    return patched


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
    tool_trace_callback: Optional[TraceCallback] = None,
    hook_registry: Optional[HookRegistry] = None,
) -> ToolRegistry:
    """Create a ToolRegistry with all default and custom tools."""
    registry = ToolRegistry(hook_registry=hook_registry)
    web_search_executor = execute_web_search_fn or _execute_web_search
    get_url_content_executor = execute_get_url_content_fn or _execute_get_url_content
    get_url_details_executor = execute_get_url_details_fn or _execute_get_url_details
    custom_tool_executor = execute_custom_tool_fn or _execute_custom_tool
    active_custom_tools = custom_tools if custom_tools is not None else CUSTOM_TOOLS
    excluded_tools = disabled_tools or set()

    if _is_tool_enabled("web_search", excluded_tools):
        web_search_schema = _apply_tool_prompt_overrides(
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
        )
        registry.register(
            "web_search",
            web_search_schema,
            (
                lambda args: web_search_executor(
                    args,
                    trace_callback=tool_trace_callback,
                )
                if tool_trace_callback
                and _executor_supports_trace_callback(web_search_executor)
                else web_search_executor(args)
            ),
        )

    def url_content_executor(
        args: Dict[str, Any],
        summarize: bool = False,
    ) -> Dict[str, Any]:
        if (
            tool_trace_callback
            and _executor_supports_trace_callback(get_url_content_executor)
        ):
            result = get_url_content_executor(
                args,
                trace_callback=tool_trace_callback,
            )
        else:
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
                        get_llm_msg_func=(
                            lambda model_id, msgs, **kwargs: get_llm_msg(
                                model_id,
                                msgs,
                                trace_callback=tool_trace_callback,
                                trace_context={
                                    "source": "summarization",
                                    "tool_name": "get_url_content",
                                    "url": url,
                                },
                                **kwargs,
                            )
                        ),
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
        get_url_content_schema = _apply_tool_prompt_overrides(
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
        )
        registry.register(
            "get_url_content",
            get_url_content_schema,
            url_content_executor,
        )

    if _is_tool_enabled("get_url_details", excluded_tools):
        get_url_details_schema = _apply_tool_prompt_overrides(
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
        )
        registry.register(
            "get_url_details",
            get_url_details_schema,
            (
                lambda args: get_url_details_executor(
                    args,
                    trace_callback=tool_trace_callback,
                )
                if tool_trace_callback
                and _executor_supports_trace_callback(get_url_details_executor)
                else get_url_details_executor(args)
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

    if _is_tool_enabled("save_memory", excluded_tools):
        from asky.memory.tools import MEMORY_TOOL_SCHEMA

        registry.register(
            "save_memory",
            _apply_tool_prompt_overrides("save_memory", MEMORY_TOOL_SCHEMA),
            lambda args: call_attr("asky.memory.tools", "execute_save_memory", args),
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

    if hook_registry is not None:
        hook_registry.invoke(
            TOOL_REGISTRY_BUILD,
            ToolRegistryBuildContext(
                mode="standard",
                registry=registry,
                disabled_tools=set(excluded_tools),
            ),
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
    preloaded_corpus_urls: Optional[list[str]] = None,
    research_source_mode: Optional[str] = None,
    summarization_tracker: Optional[UsageTracker] = None,
    tool_trace_callback: Optional[TraceCallback] = None,
    hook_registry: Optional[HookRegistry] = None,
) -> ToolRegistry:
    """Create a ToolRegistry with research mode tools."""
    registry = ToolRegistry(hook_registry=hook_registry)
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
        web_search_schema = _apply_tool_prompt_overrides(
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
        )
        registry.register(
            "web_search",
            web_search_schema,
            (
                lambda args: web_search_executor(
                    args,
                    trace_callback=tool_trace_callback,
                )
                if tool_trace_callback
                and _executor_supports_trace_callback(web_search_executor)
                else web_search_executor(args)
            ),
        )

    research_bindings = load_research_tool_bindings()
    schemas = research_bindings["schemas"]
    fallback_corpus_urls = [
        url for url in (preloaded_corpus_urls or []) if str(url).strip()
    ]
    normalized_source_mode = (
        str(research_source_mode).strip().lower()
        if isinstance(research_source_mode, str)
        else ""
    )

    def _execute_with_context(
        executor: ToolExecutor,
        *,
        include_corpus_url_fallback: bool = False,
        include_source_mode: bool = False,
    ) -> ToolExecutor:
        if (
            session_id is None
            and summarization_tracker is None
            and not include_corpus_url_fallback
            and not include_source_mode
        ):
            return executor

        def _wrapped(args: Dict[str, Any]) -> Dict[str, Any]:
            if (
                session_id is not None
                and "session_id" in args
                and summarization_tracker is None
                and not include_corpus_url_fallback
                and not include_source_mode
            ):
                return executor(args)
            enriched_args = dict(args)
            if session_id is not None and "session_id" not in enriched_args:
                enriched_args["session_id"] = session_id
            if summarization_tracker is not None:
                enriched_args["summarization_tracker"] = summarization_tracker
            if include_corpus_url_fallback and fallback_corpus_urls:
                existing_urls = enriched_args.get("urls")
                if not existing_urls:
                    enriched_args["corpus_urls"] = list(fallback_corpus_urls)
            if include_source_mode and normalized_source_mode:
                enriched_args["research_source_mode"] = normalized_source_mode
            return executor(enriched_args)

        return _wrapped

    for schema in schemas:
        tool_name = schema["name"]
        if (
            tool_name in LOCAL_CORPUS_ONLY_RESEARCH_TOOLS
            and normalized_source_mode not in {"local_only", "mixed"}
        ):
            continue
        if not _is_tool_enabled(tool_name, excluded_tools):
            continue
        schema_with_overrides = _apply_tool_prompt_overrides(tool_name, schema)
        if tool_name == "extract_links":
            registry.register(
                tool_name,
                schema_with_overrides,
                _execute_with_context(research_bindings["extract_links"]),
            )
        elif tool_name == "get_link_summaries":
            registry.register(
                tool_name,
                schema_with_overrides,
                _execute_with_context(research_bindings["get_link_summaries"]),
            )
        elif tool_name == "get_relevant_content":
            registry.register(
                tool_name,
                schema_with_overrides,
                _execute_with_context(
                    research_bindings["get_relevant_content"],
                    include_corpus_url_fallback=True,
                ),
            )
        elif tool_name == "get_full_content":
            registry.register(
                tool_name,
                schema_with_overrides,
                _execute_with_context(
                    research_bindings["get_full_content"],
                    include_corpus_url_fallback=True,
                ),
            )
        elif tool_name == "save_finding":
            registry.register(
                tool_name,
                schema_with_overrides,
                _execute_with_context(research_bindings["save_finding"]),
            )
        elif tool_name == "query_research_memory":
            registry.register(
                tool_name,
                schema_with_overrides,
                _execute_with_context(research_bindings["query_research_memory"]),
            )
        elif tool_name == "list_sections":
            registry.register(
                tool_name,
                schema_with_overrides,
                _execute_with_context(
                    research_bindings["list_sections"],
                    include_corpus_url_fallback=True,
                    include_source_mode=True,
                ),
            )
        elif tool_name == "summarize_section":
            registry.register(
                tool_name,
                schema_with_overrides,
                _execute_with_context(
                    research_bindings["summarize_section"],
                    include_corpus_url_fallback=True,
                    include_source_mode=True,
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

    if _is_tool_enabled("save_memory", excluded_tools):
        from asky.memory.tools import MEMORY_TOOL_SCHEMA

        registry.register(
            "save_memory",
            _apply_tool_prompt_overrides("save_memory", MEMORY_TOOL_SCHEMA),
            lambda args: call_attr("asky.memory.tools", "execute_save_memory", args),
        )

    if hook_registry is not None:
        hook_registry.invoke(
            TOOL_REGISTRY_BUILD,
            ToolRegistryBuildContext(
                mode="research",
                registry=registry,
                disabled_tools=set(excluded_tools),
            ),
        )

    return registry


def get_all_available_tool_names() -> List[str]:
    """Gather all tool names from default, research, custom, and push endpoints."""
    names: Set[str] = {
        "web_search",
        "get_url_content",
        "get_url_details",
        "save_memory",
    }

    # Research tools
    from asky.research.tools import RESEARCH_TOOL_SCHEMAS

    for schema in RESEARCH_TOOL_SCHEMAS:
        names.add(schema["name"])

    # Custom tools
    for tool_name, tool_data in CUSTOM_TOOLS.items():
        if tool_data.get("enabled", True):
            names.add(tool_name)

    # Push data tools
    try:
        from asky.push_data import get_enabled_endpoints

        for endpoint_name in get_enabled_endpoints():
            names.add(f"push_data_{endpoint_name}")
    except Exception:
        # Fallback if push_data module fails to load or similar
        pass

    return sorted(list(names))
