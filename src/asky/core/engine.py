"""Main conversation orchestration engine."""

import json
import logging
import time
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.markdown import Markdown

from asky.config import (
    DEFAULT_CONTEXT_SIZE,
    MAX_TURNS,
    CUSTOM_TOOLS,
    SUMMARIZE_ANSWER_PROMPT_TEMPLATE,
    ANSWER_SUMMARY_MAX_CHARS,
    SUMMARIZE_QUERY_PROMPT_TEMPLATE,
    QUERY_SUMMARY_MAX_CHARS,
)
from asky.html import strip_think_tags
from asky.rendering import render_to_browser
from asky.core.api_client import get_llm_msg, count_tokens, UsageTracker
from asky.core.prompts import extract_calls, is_markdown
from asky.core.registry import ToolRegistry
from asky.tools import (
    _execute_custom_tool,
    execute_get_date_time,
    execute_get_url_content,
    execute_get_url_details,
    execute_web_search,
)
from asky import summarization

logger = logging.getLogger(__name__)


class ConversationEngine:
    """Orchestrates multi-turn LLM conversations with tool execution."""

    def __init__(
        self,
        model_config: Dict[str, Any],
        tool_registry: ToolRegistry,
        summarize: bool = False,
        verbose: bool = False,
        usage_tracker: Optional[UsageTracker] = None,
        open_browser: bool = False,
    ):
        self.model_config = model_config
        self.tool_registry = tool_registry
        self.summarize = summarize
        self.verbose = verbose
        self.usage_tracker = usage_tracker
        self.open_browser = open_browser
        self.start_time: float = 0
        self.final_answer: str = ""

    def run(self, messages: List[Dict[str, Any]]) -> str:
        """Run the multi-turn conversation loop."""
        turn = 0
        self.start_time = time.perf_counter()
        original_system_prompt = (
            messages[0]["content"]
            if messages and messages[0]["role"] == "system"
            else ""
        )

        try:
            while turn < MAX_TURNS:
                turn += 1
                logger.info(f"Starting turn {turn}/{MAX_TURNS}")

                # Token & Turn Tracking
                total_tokens = count_tokens(messages)
                context_size = self.model_config.get(
                    "context_size", DEFAULT_CONTEXT_SIZE
                )
                turns_left = MAX_TURNS - turn + 1

                status_msg = (
                    f"\n\n[SYSTEM UPDATE]:\n"
                    f"- Context Used: {total_tokens / context_size * 100:.2f}%"
                    f"- Turns Remaining: {turns_left} (out of {MAX_TURNS})\n"
                    f"Please manage your context usage efficiently."
                )
                if messages and messages[0]["role"] == "system":
                    messages[0]["content"] = original_system_prompt + status_msg

                msg = get_llm_msg(
                    self.model_config["id"],
                    messages,
                    use_tools=True,
                    verbose=self.verbose,
                    model_alias=self.model_config.get("alias"),
                    usage_tracker=self.usage_tracker,
                    # Pass schemas from registry
                    tool_schemas=self.tool_registry.get_schemas(),
                )

                calls = extract_calls(msg, turn)
                if not calls:
                    self.final_answer = strip_think_tags(msg.get("content", ""))
                    console = Console()
                    if is_markdown(self.final_answer):
                        console.print(Markdown(self.final_answer))
                    else:
                        console.print(self.final_answer)

                    if self.open_browser:
                        render_to_browser(self.final_answer)
                    break

                messages.append(msg)
                for call in calls:
                    logger.debug(f"Tool call [{len(str(call))} chrs]: {str(call)}")
                    result = self.tool_registry.dispatch(
                        call, self.summarize, self.usage_tracker
                    )
                    logger.debug(
                        f"Tool result [{len(str(result))} chrs]: {str(result)}"
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": json.dumps(result),
                        }
                    )

            if turn >= MAX_TURNS:
                logger.info("Error: Max turns reached.")

        except Exception as e:
            logger.info(f"Error: {str(e)}")
            logger.exception("Engine failure")
        finally:
            logger.info(
                f"\nQuery completed in {time.perf_counter() - self.start_time:.2f} seconds"
            )

        return self.final_answer


def create_default_tool_registry() -> ToolRegistry:
    """Create a ToolRegistry with all default and custom tools."""
    registry = ToolRegistry()

    registry.register(
        "web_search",
        {
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
        execute_web_search,
    )

    def url_content_executor(
        args: Dict[str, Any],
        summarize: bool = False,
        usage_tracker: Optional[UsageTracker] = None,
    ) -> Dict[str, Any]:
        result = execute_get_url_content(args)
        # LLM can override the global summarize flag in its tool call
        effective_summarize = args.get("summarize", summarize)
        if effective_summarize:
            for url, content in result.items():
                if not content.startswith("Error:"):
                    result[url] = (
                        f"Summary of {url}:\n"
                        + summarization._summarize_content(
                            content=content,
                            prompt_template=SUMMARIZE_ANSWER_PROMPT_TEMPLATE,
                            max_output_chars=ANSWER_SUMMARY_MAX_CHARS,
                            get_llm_msg_func=get_llm_msg,
                            usage_tracker=usage_tracker,
                        )
                    )
        return result

    registry.register(
        "get_url_content",
        {
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
        url_content_executor,
    )

    registry.register(
        "get_url_details",
        {
            "name": "get_url_details",
            "description": "Fetch content and extract links from a URL. Use this in deep dive mode.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
        execute_get_url_details,
    )

    registry.register(
        "get_date_time",
        {
            "name": "get_date_time",
            "description": "Return the current date and time.",
            "parameters": {"type": "object", "properties": {}},
        },
        lambda _: execute_get_date_time(),
    )

    # Register custom tools from config
    for tool_name, tool_data in CUSTOM_TOOLS.items():
        registry.register(
            tool_name,
            {
                "name": tool_name,
                "description": tool_data.get(
                    "description", f"Custom tool: {tool_name}"
                ),
                "parameters": tool_data.get(
                    "parameters", {"type": "object", "properties": {}}
                ),
            },
            lambda args, name=tool_name: _execute_custom_tool(name, args),
        )

    return registry


def run_conversation_loop(
    model_config: Dict[str, Any],
    messages: List[Dict[str, Any]],
    summarize: bool,
    verbose: bool = False,
    usage_tracker: Optional[UsageTracker] = None,
    open_browser: bool = False,
) -> str:
    """Legacy wrapper for ConversationEngine.run()."""
    registry = create_default_tool_registry()
    engine = ConversationEngine(
        model_config=model_config,
        tool_registry=registry,
        summarize=summarize,
        verbose=verbose,
        usage_tracker=usage_tracker,
        open_browser=open_browser,
    )
    return engine.run(messages)


def dispatch_tool_call(
    call: Dict[str, Any],
    summarize: bool = False,
    usage_tracker: Optional[UsageTracker] = None,
) -> Dict[str, Any]:
    """Legacy standalone tool dispatcher."""
    registry = create_default_tool_registry()
    return registry.dispatch(call, summarize, usage_tracker)


def generate_summaries(
    query: str, answer: str, usage_tracker: Optional[UsageTracker] = None
) -> tuple[str, str]:
    """Generate summaries for query and answer for history storage."""
    query_summary = ""
    if len(query) > QUERY_SUMMARY_MAX_CHARS:
        query_summary = summarization._summarize_content(
            content=query,
            prompt_template=SUMMARIZE_QUERY_PROMPT_TEMPLATE,
            max_output_chars=QUERY_SUMMARY_MAX_CHARS,
            get_llm_msg_func=get_llm_msg,
            usage_tracker=usage_tracker,
        )

    answer_summary = summarization._summarize_content(
        content=answer,
        prompt_template=SUMMARIZE_ANSWER_PROMPT_TEMPLATE,
        max_output_chars=ANSWER_SUMMARY_MAX_CHARS,
        get_llm_msg_func=get_llm_msg,
        usage_tracker=usage_tracker,
    )
    return query_summary, answer_summary
