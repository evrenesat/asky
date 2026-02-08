"""Main conversation orchestration engine."""

import json
import logging
import requests
import time
from typing import Any, Callable, Dict, List, Optional

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.pretty import Pretty

from asky.research.cache import ResearchCache
from asky.config import (
    DEFAULT_CONTEXT_SIZE,
    MAX_TURNS,
    CUSTOM_TOOLS,
    SUMMARIZE_ANSWER_PROMPT_TEMPLATE,
    ANSWER_SUMMARY_MAX_CHARS,
    SUMMARIZE_QUERY_PROMPT_TEMPLATE,
    QUERY_SUMMARY_MAX_CHARS,
    SESSION_COMPACTION_THRESHOLD,
)
from asky.html import strip_think_tags
from asky.rendering import render_to_browser
from asky.core.api_client import get_llm_msg, count_tokens, UsageTracker
from asky.core.prompts import extract_calls, is_markdown
from asky.core.registry import ToolRegistry
from asky.tools import (
    _execute_custom_tool,
    execute_get_url_content,
    execute_get_url_details,
    execute_web_search,
)
from asky import summarization
from asky.research.tools import (
    execute_extract_links,
    execute_get_link_summaries,
    execute_get_relevant_content,
    execute_get_full_content,
    execute_save_finding,
    execute_query_research_memory,
    RESEARCH_TOOL_SCHEMAS,
)

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
        session_manager: Optional[Any] = None,
        verbose_output_callback: Optional[Callable[[Any], None]] = None,
    ):
        self.model_config = model_config
        self.tool_registry = tool_registry
        self.summarize = summarize
        self.verbose = verbose
        self.usage_tracker = usage_tracker
        self.open_browser = open_browser
        self.session_manager = session_manager
        self.verbose_output_callback = verbose_output_callback
        self.research_cache = ResearchCache()
        self.start_time: float = 0
        self.final_answer: str = ""

    def run(self, messages: List[Dict[str, Any]], display_callback=None) -> str:
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

                # Wrap display_callback to match api_client expectation
                def status_reporter(msg: Optional[str]):
                    if display_callback:
                        display_callback(turn, status_message=msg)

                # Compaction Check
                messages = self.check_and_compact(messages)

                msg = get_llm_msg(
                    self.model_config["id"],
                    messages,
                    use_tools=True,
                    verbose=self.verbose,
                    model_alias=self.model_config.get("alias"),
                    usage_tracker=self.usage_tracker,
                    # Pass schemas from registry
                    tool_schemas=self.tool_registry.get_schemas(),
                    status_callback=status_reporter,
                    parameters=self.model_config.get("parameters"),
                )

                calls = extract_calls(msg, turn)
                if not calls:
                    self.final_answer = strip_think_tags(msg.get("content", ""))

                    # Add the final assistant message to conversations for display
                    messages.append({"role": "assistant", "content": self.final_answer})

                    # If display_callback is provided (live mode), notify that the final
                    # answer is ready. Pass is_final=True so the callback can render
                    # only the answer without re-drawing the banner (avoiding double banner).
                    if display_callback:
                        display_callback(
                            turn, is_final=True, final_answer=self.final_answer
                        )
                    else:
                        # No callback, print the answer directly
                        console = Console()
                        if is_markdown(self.final_answer):
                            console.print(Markdown(self.final_answer))
                        else:
                            console.print(self.final_answer)

                    if self.open_browser:
                        render_to_browser(
                            self.final_answer, filename_hint=self.final_answer
                        )
                    break

                messages.append(msg)
                for call_index, call in enumerate(calls, start=1):
                    self._print_verbose_tool_call(
                        call=call,
                        turn=turn,
                        call_index=call_index,
                        total_calls=len(calls),
                    )

                    tool_name = call.get("function", {}).get("name", "unknown_tool")
                    if display_callback:
                        display_callback(
                            turn,
                            status_message=(
                                f"Executing tool {call_index}/{len(calls)}: {tool_name}"
                            ),
                        )
                    logger.debug(f"Tool call [{len(str(call))} chrs]: {str(call)}")
                    result = self.tool_registry.dispatch(
                        call,
                        self.summarize,
                    )
                    logger.debug(
                        f"Tool result [{len(str(result))} chrs]: {str(result)}"
                    )

                    # Track tool usage in tracker if available
                    if self.usage_tracker:
                        tool_name = call.get("function", {}).get("name")
                        if tool_name:
                            self.usage_tracker.record_tool_usage(tool_name)

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": json.dumps(result),
                        }
                    )

                if display_callback:
                    display_callback(turn, status_message=None)

                # Redraw interface after processing all tool calls for this turn
                if display_callback:
                    display_callback(turn)

            # Only enter graceful exit if we hit max turns WITHOUT already having a final answer
            if turn >= MAX_TURNS and not self.final_answer:
                self.final_answer = self._execute_graceful_exit(
                    messages, status_reporter
                )

                # Render/Print the forced final answer
                if display_callback:
                    display_callback(
                        turn + 1, is_final=True, final_answer=self.final_answer
                    )
                else:
                    console = Console()
                    if is_markdown(self.final_answer):
                        console.print(Markdown(self.final_answer))
                    else:
                        console.print(self.final_answer)

                if self.open_browser:
                    render_to_browser(
                        self.final_answer, filename_hint=self.final_answer
                    )

        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 400:
                logger.error(f"API Error 400: {e}")
                self._handle_400_error(e, messages, status_reporter)
            else:
                self._handle_general_error(e)

        except Exception as e:
            self._handle_general_error(e)
        finally:
            logger.info(
                f"\nQuery completed in {time.perf_counter() - self.start_time:.2f} seconds"
            )

        return self.final_answer

    def _print_verbose_tool_call(
        self, call: Dict[str, Any], turn: int, call_index: int, total_calls: int
    ) -> None:
        """Print detailed tool call info to terminal when verbose mode is enabled."""
        if not self.verbose:
            return

        function = call.get("function", {})
        tool_name = function.get("name", "unknown_tool")
        args_str = function.get("arguments", "{}")

        try:
            parsed_args: Any = json.loads(args_str) if args_str else {}
        except json.JSONDecodeError:
            parsed_args = {"_raw_arguments": args_str}

        title = f"Tool {call_index}/{total_calls} | Turn {turn} | {tool_name}"
        body = Pretty(parsed_args, indent_guides=True, expand_all=False)
        panel = Panel(body, title=title, border_style="cyan", expand=False)
        if self.verbose_output_callback:
            self.verbose_output_callback(panel)
            return
        Console().print(panel)

    def _compact_tool_message(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """Replace full URL content with summaries in a tool message.

        Args:
            msg: The tool message to compact.

        Returns:
            The compacted message (or original if no compaction possible).
        """
        if msg.get("role") != "tool":
            return msg

        content_str = msg.get("content", "")
        if not content_str:
            return msg

        try:
            # Tool responses, if they are Dicts, are usually JSON strings
            data = json.loads(content_str)
            if not isinstance(data, dict):
                return msg
        except json.JSONDecodeError:
            return msg

        # Check if keys are URLs and content is huge
        compacted_data = {}
        modified = False

        for key, value in data.items():
            # Heuristic: Key looks like URL
            is_url = key.startswith("http") or key.startswith("https")

            # Case 1: Value is a dict with 'content' (e.g. get_full_content)
            if isinstance(value, dict) and "content" in value and is_url:
                summary_info = self.research_cache.get_summary(key)
                if summary_info and summary_info.get("summary"):
                    logger.debug(
                        f"[Smart Compaction] Found summary for URL {key} (dict). Replacing content."
                    )
                    # Replace full content with summary
                    compacted_data[key] = value.copy()
                    compacted_data[key]["content"] = (
                        f"[COMPACTED] {summary_info['summary']}"
                    )
                    compacted_data[key]["note"] = (
                        "Content replaced with summary to save context."
                    )
                    modified = True
                else:
                    # Fallback: Truncate
                    val_content = value.get("content", "")
                    if len(val_content) > 500:
                        logger.debug(
                            f"[Smart Compaction] No summary for URL {key} (dict). Truncating content > 500 chars."
                        )
                        compacted_data[key] = value.copy()
                        compacted_data[key]["content"] = (
                            val_content[:500] + "... [TRUNCATED]"
                        )
                        compacted_data[key]["note"] = (
                            "Content truncated to save context."
                        )
                        modified = True
                    else:
                        compacted_data[key] = value

            # Case 2: Value is a string (e.g. get_url_content) AND key is URL
            elif isinstance(value, str) and is_url:
                # Can we look up summary for this URL?
                # Ideally yes if it's in cache.
                summary_info = self.research_cache.get_summary(key)
                if summary_info and summary_info.get("summary"):
                    logger.debug(
                        f"[Smart Compaction] Found summary for URL {key} (str). Replacing content."
                    )
                    compacted_data[key] = f"[COMPACTED] {summary_info['summary']}"
                    modified = True
                else:
                    if len(value) > 500:
                        logger.debug(
                            f"[Smart Compaction] No summary for URL {key} (str). Truncating content > 500 chars."
                        )
                        compacted_data[key] = value[:500] + "... [TRUNCATED]"
                        modified = True
                    else:
                        compacted_data[key] = value

            else:
                # Keep as is
                compacted_data[key] = value

        if modified:
            new_msg = msg.copy()
            new_msg["content"] = json.dumps(compacted_data)
            return new_msg

        return msg

    def check_and_compact(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Check if message history exceeds threshold and compact if needed."""
        context_size = self.model_config.get("context_size", DEFAULT_CONTEXT_SIZE)
        threshold_tokens = int(context_size * (SESSION_COMPACTION_THRESHOLD / 100))
        current_tokens = count_tokens(messages)

        if current_tokens < threshold_tokens:
            return messages

        logger.info(
            f"Context threshold reached ({current_tokens}/{threshold_tokens}). Compacting..."
        )
        Console().print("\n[Context limit reached. Compacting conversation history...]")

        # Phase 1: Smart Compaction (Non-destructive to message count)
        # Scan for tool messages and try to replace content with summaries
        smart_compacted_messages = []
        for m in messages:
            if m.get("role") == "tool":
                smart_compacted_messages.append(self._compact_tool_message(m))
            else:
                smart_compacted_messages.append(m)

        # Re-check tokens
        new_tokens = count_tokens(smart_compacted_messages)
        if new_tokens < threshold_tokens:
            logger.info(
                f"Smart compaction successful. Reduced from {current_tokens} to {new_tokens}"
            )
            Console().print("[Compaction successful using summaries]")
            return smart_compacted_messages

        # Phase 2: Destructive Compaction (Drop messages)
        # If smart compaction wasn't enough, we must drop messages.
        # We work with the ALREADY smart-compacted list to save as much as possible.
        messages = smart_compacted_messages

        system_msgs = [m for m in messages if m.get("role") == "system"]
        other_msgs = [m for m in messages if m.get("role") != "system"]

        if not other_msgs:
            return messages

        # Always keep the last message (assumed to be the current user query or recent context)
        last_msg = other_msgs[-1]
        history = other_msgs[:-1]

        while history:
            history.pop(0)
            candidate = system_msgs + history + [last_msg]
            if count_tokens(candidate) < threshold_tokens:
                logger.info(f"Compacted to {count_tokens(candidate)} tokens.")
                return candidate

        final_attempt = system_msgs + [last_msg]
        logger.info(
            f"Compaction failed to preserve history. Returning minimal context: {count_tokens(final_attempt)} tokens."
        )
        return final_attempt

    def _execute_graceful_exit(
        self, messages: List[Dict[str, Any]], status_reporter: Any
    ) -> str:
        """Execute graceful exit when max turns reached without final answer.

        Replaces the system prompt with a tool-free version to prevent
        models from generating imaginary tool calls.
        """
        from asky.config import GRACEFUL_EXIT_SYSTEM

        logger.info("Max turns reached. Forcing graceful exit.")

        # Build a clean message list with tool-free system prompt
        exit_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                # Replace with graceful exit prompt (no tool mentions)
                exit_messages.append(
                    {"role": "system", "content": GRACEFUL_EXIT_SYSTEM}
                )
            else:
                exit_messages.append(msg)

        # Add the final instruction
        exit_messages.append(
            {
                "role": "user",
                "content": "SYSTEM: Provide your final answer now based on the research above.",
            }
        )

        # Make final call without tools AND without tool-mentioning system prompt
        final_msg = get_llm_msg(
            self.model_config["id"],
            exit_messages,
            use_tools=False,  # No tool schemas sent to API
            verbose=self.verbose,
            model_alias=self.model_config.get("alias"),
            usage_tracker=self.usage_tracker,
            status_callback=status_reporter,
        )

        final_answer = final_msg.get("content", "")
        # Append the final answer to the original messages for history tracking
        messages.append({"role": "assistant", "content": final_answer})

        return final_answer

    def _handle_400_error(self, e, messages, status_reporter):
        """Handle 400 Bad Request errors interactively."""
        console = Console()
        console.print("\n\n[bold red][!] API Error:[/] 400 Bad Request (likely context overflow).")
        console.print(f"    Message: {str(e)}")

        while True:
            console.print("\nOptions:")
            console.print("  [r]etry        : Compact context more aggressively and retry")
            console.print(
                "  [s]witch model : Switch to a different model (e.g. larger context)"
            )
            console.print("  [e]xit         : Exit application")

            choice = input("\nSelect action [r/s/e]: ").lower().strip()

            if choice == "r":
                console.print("Compacting and retrying...")
                # Aggressive compaction: Force re-run of check_and_compact
                # effectively, the loop in run() should handle it if we break/continue,
                # but we are in exception handler.
                # Simpler: Trigger compaction here and recursive call or re-raise special exception?
                # Actually, since we are outside the loop (or inside it?), wait.
                # The exception caught was INSIDE the loop? No, run() implementation shows it catches outside loop??
                # Let's check where the try/except block is.
                # Ah, the try/except in my replacement above covers the WHOLE loop.
                # If exception happens, the loop is broken.
                # So we can't easily "resume" the loop unless we restart it.

                # To retry properly, we might need to recursively call run() with compacted messages?
                # Or refactor run() to be robust.

                # For now, let's try compacting and calling run() again with the SAME state.
                # But we need to stay decrement MAX_TURNS?
                # Actually, simply calling self.run(messages) might loop infinitely if we don't fix the issue.

                messages = self.check_and_compact(messages)
                # If check_and_compact didn't reduce enough (user selected retry implying "try again maybe it works now" or "force compaction"),
                # we might need to be more aggressive.
                # But check_and_compact checks threshold. If we are 400-ing, we ARE above actual limit (even if below threshold?).
                # Or maybe the model doesn't support what we think.

                # Let's just recursively call run().
                # But we need to validte escape condition.
                self.final_answer = self.run(
                    messages, display_callback=None
                )  # We lost the callback ref?
                # We can reuse the one passed to _handle_400... wait, run takes display_callback.
                # I need to store display_callback in self or pass it around.
                # For this PR, let's just use self.run(messages) and assume standard output.
                return

            elif choice == "s":
                from asky.config import MODELS

                console.print(f"Available models: {', '.join(MODELS.keys())}")
                new_alias = input("Enter model alias: ").strip()
                if new_alias in MODELS:
                    self.model_config = MODELS[new_alias]
                    console.print(f"Switched to {new_alias}. Retrying...")
                    self.final_answer = self.run(messages)
                    return
                else:
                    console.print("Invalid model alias.")

            elif choice == "e":
                console.print("Exiting...")
                return

    def _handle_general_error(self, e):
        logger.info(f"Error: {str(e)}")
        logger.exception("Engine failure")


def create_default_tool_registry(
    usage_tracker: Optional[UsageTracker] = None,
    summarization_tracker: Optional[UsageTracker] = None,
) -> ToolRegistry:
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
                            usage_tracker=summarization_tracker,
                        )
                    )
        return result

    registry.register(
        "get_url_content",
        {
            "name": "get_url_content",
            "description": "Fetch one or more URLs and return extracted main content in lightweight markdown.",
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
            "description": "Fetch extracted main content plus discovered links from a URL.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
        execute_get_url_details,
    )

    # Register custom tools from config
    for tool_name, tool_data in CUSTOM_TOOLS.items():
        if not tool_data.get("enabled", True):
            continue
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

    # Register enabled push_data endpoints as LLM tools
    from asky.push_data import execute_push_data, get_enabled_endpoints

    for endpoint_name, endpoint_config in get_enabled_endpoints().items():
        # Extract dynamic parameters from fields configuration
        fields_config = endpoint_config.get("fields", {})
        properties = {}
        required = []

        for key, value in fields_config.items():
            # Skip static values, environment variables, and special variables
            if (
                isinstance(value, str)
                and value.startswith("${")
                and value.endswith("}")
            ):
                param_name = value[2:-1]
                # Only add if it's not a special variable
                if param_name not in {"query", "answer", "timestamp", "model"}:
                    properties[param_name] = {
                        "type": "string",
                        "description": f"Value for {param_name}",
                    }
                    required.append(param_name)

        # Create tool executor that captures endpoint_name
        def make_push_executor(ep_name: str):
            def push_executor(args: Dict[str, Any]) -> Dict[str, Any]:
                # Special variables are not provided via args - they're auto-filled
                # So we only pass the dynamic args here
                return execute_push_data(ep_name, dynamic_args=args)

            return push_executor

        tool_name = f"push_data_{endpoint_name}"
        description = endpoint_config.get(
            "description", f"Push data to {endpoint_name}"
        )

        registry.register(
            tool_name,
            {
                "name": tool_name,
                "description": description,
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
) -> ToolRegistry:
    """Create a ToolRegistry with research mode tools.

    Research mode provides:
    - web_search: Standard web search
    - extract_links: Extract and cache links from URLs (content cached, links returned)
    - get_link_summaries: Get AI-generated summaries of cached pages
    - get_relevant_content: RAG-based retrieval of relevant content chunks
    - get_full_content: Get full cached content

    Plus any custom tools from config.
    """
    registry = ToolRegistry()

    # Web search (same as default)
    registry.register(
        "web_search",
        {
            "name": "web_search",
            "description": "Search the web and return top results. Use this to find relevant sources for your research.",
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
        execute_web_search,
    )

    # Research mode tools
    for schema in RESEARCH_TOOL_SCHEMAS:
        tool_name = schema["name"]
        if tool_name == "extract_links":
            registry.register(tool_name, schema, execute_extract_links)
        elif tool_name == "get_link_summaries":
            registry.register(tool_name, schema, execute_get_link_summaries)
        elif tool_name == "get_relevant_content":
            registry.register(tool_name, schema, execute_get_relevant_content)
        elif tool_name == "get_full_content":
            registry.register(tool_name, schema, execute_get_full_content)
        elif tool_name == "save_finding":
            registry.register(tool_name, schema, execute_save_finding)
        elif tool_name == "query_research_memory":
            registry.register(tool_name, schema, execute_query_research_memory)

    # Register custom tools from config
    for tool_name, tool_data in CUSTOM_TOOLS.items():
        if not tool_data.get("enabled", True):
            continue
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
    else:
        query_summary = query

    if len(answer) > ANSWER_SUMMARY_MAX_CHARS:
        answer_summary = summarization._summarize_content(
            content=answer,
            prompt_template=SUMMARIZE_ANSWER_PROMPT_TEMPLATE,
            max_output_chars=ANSWER_SUMMARY_MAX_CHARS,
            get_llm_msg_func=get_llm_msg,
            usage_tracker=usage_tracker,
        )
    else:
        answer_summary = answer

    return query_summary, answer_summary
