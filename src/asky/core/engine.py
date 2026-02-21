"""Main conversation orchestration engine."""

import json
import logging
import requests
import time
from typing import Any, Callable, Dict, List, Optional, Set

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
from asky.lazy_imports import call_attr
from asky.rendering import render_to_browser
from asky.core.api_client import get_llm_msg, count_tokens, UsageTracker
from asky.core.exceptions import ContextOverflowError
from asky.core.prompts import extract_calls
from asky.core.registry import ToolRegistry
from asky import summarization

logger = logging.getLogger(__name__)


def ResearchCache(*args, **kwargs):
    """Lazy constructor proxy retained for test patch compatibility."""
    return call_attr("asky.research.cache", "ResearchCache", *args, **kwargs)


def execute_web_search(args: Dict[str, Any]) -> Dict[str, Any]:
    return call_attr("asky.tools", "execute_web_search", args)


def execute_get_url_content(args: Dict[str, Any]) -> Dict[str, Any]:
    return call_attr("asky.tools", "execute_get_url_content", args)


def execute_get_url_details(args: Dict[str, Any]) -> Dict[str, Any]:
    return call_attr("asky.tools", "execute_get_url_details", args)


def _execute_custom_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    return call_attr("asky.tools", "_execute_custom_tool", name, args)


def _get_research_cache():
    """Lazy-load research cache to avoid startup import overhead."""
    return ResearchCache()


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
        event_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        lean: bool = False,
        max_turns: Optional[int] = None,
    ):
        self.model_config = model_config
        self.tool_registry = tool_registry
        self.summarize = summarize
        self.verbose = verbose
        self.usage_tracker = usage_tracker
        self.open_browser = open_browser
        self.session_manager = session_manager
        self.verbose_output_callback = verbose_output_callback
        self.event_callback = event_callback
        self.lean = lean
        self.max_turns = max_turns or MAX_TURNS
        self._research_cache = None
        self.start_time: float = 0
        self.final_answer: str = ""

    @property
    def research_cache(self):
        if self._research_cache is None:
            self._research_cache = _get_research_cache()
        return self._research_cache

    def _emit_event(self, name: str, **payload: Any) -> None:
        """Emit a structured runtime event when a callback is configured."""
        if self.event_callback is None:
            return
        self.event_callback(name, payload)

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
            while turn < self.max_turns:
                turn += 1
                logger.info(f"Starting turn {turn}/{self.max_turns}")
                self._emit_event("turn_start", turn=turn, max_turns=self.max_turns)

                # Token & Turn Tracking
                total_tokens = count_tokens(messages)
                context_size = self.model_config.get(
                    "context_size", DEFAULT_CONTEXT_SIZE
                )
                turns_left = self.max_turns - turn + 1

                status_msg = (
                    f"\n\n[SYSTEM UPDATE]:\n"
                    f"- Context Used: {total_tokens / context_size * 100:.2f}%"
                    f"- Turns Remaining: {turns_left} (out of {self.max_turns})\n"
                    f"Please manage your context usage efficiently."
                )
                # In lean mode, we suppress these system updates to keep the context clean
                # and avoid "nagging" the model, as requested by power users.
                if not self.lean and messages and messages[0]["role"] == "system":
                    messages[0]["content"] = original_system_prompt + status_msg

                # Wrap display_callback to match api_client expectation
                def status_reporter(msg: Optional[str]):
                    if display_callback:
                        display_callback(turn, status_message=msg)
                    self._emit_event(
                        "llm_status",
                        turn=turn,
                        status_message=msg,
                    )

                # Compaction Check
                messages = self.check_and_compact(messages)
                tool_schemas = self.tool_registry.get_schemas()
                use_tools = bool(tool_schemas)

                # Initialize tracking for all available tools so they appear with 0 usage
                if (
                    getattr(self, "_tools_initialized", False) is False
                    and use_tools
                    and self.usage_tracker
                ):
                    available_tools = [
                        s.get("function", {}).get("name")
                        for s in tool_schemas
                        if s.get("type") == "function"
                    ]
                    self.usage_tracker.init_tools([t for t in available_tools if t])
                    self._tools_initialized = True
                self._emit_event(
                    "llm_start",
                    turn=turn,
                    use_tools=use_tools,
                    message_count=len(messages),
                )

                msg = get_llm_msg(
                    self.model_config["id"],
                    messages,
                    use_tools=use_tools,
                    verbose=self.verbose,
                    model_alias=self.model_config.get("alias"),
                    usage_tracker=self.usage_tracker,
                    # Pass schemas from registry
                    tool_schemas=tool_schemas,
                    status_callback=status_reporter,
                    parameters=self.model_config.get("parameters"),
                )
                self._emit_event(
                    "llm_end",
                    turn=turn,
                    has_tool_calls=bool(msg.get("tool_calls")),
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
                    self._emit_event(
                        "final_answer",
                        turn=turn,
                        final_answer=self.final_answer,
                    )

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
                    tool_arguments = call.get("function", {}).get("arguments")
                    self._emit_event(
                        "tool_start",
                        turn=turn,
                        call_index=call_index,
                        total_calls=len(calls),
                        tool_name=tool_name,
                        tool_arguments=tool_arguments,
                    )
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
                    self._emit_event(
                        "tool_end",
                        turn=turn,
                        call_index=call_index,
                        total_calls=len(calls),
                        tool_name=tool_name,
                        result=result,
                    )

                    # Track tool usage in tracker if available
                    if self.usage_tracker:
                        tool_name = call.get("function", {}).get("name")
                        if tool_name:
                            self.usage_tracker.record_tool_usage(tool_name)

                    raw_tool_message = {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": json.dumps(result),
                    }
                    compacted_tool_message = self._compact_tool_message(
                        raw_tool_message
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": compacted_tool_message.get("content", ""),
                        }
                    )

                if display_callback:
                    display_callback(turn, status_message=None)

                # Redraw interface after processing all tool calls for this turn
                if display_callback:
                    display_callback(turn)

            # Only enter graceful exit if we hit max turns WITHOUT already having a final answer
            if turn >= self.max_turns and not self.final_answer:
                self.final_answer = self._execute_graceful_exit(
                    messages, status_reporter
                )

                # Render/Print the forced final answer
                if display_callback:
                    display_callback(
                        turn + 1, is_final=True, final_answer=self.final_answer
                    )
                self._emit_event(
                    "final_answer",
                    turn=turn + 1,
                    final_answer=self.final_answer,
                    graceful_exit=True,
                )

                if self.open_browser:
                    render_to_browser(
                        self.final_answer, filename_hint=self.final_answer
                    )

        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 400:
                logger.error(f"API Error 400: {e}")
                self._handle_400_error(e, messages)
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
        """Emit detailed tool call info when verbose mode is enabled."""
        if not self.verbose:
            return

        function = call.get("function", {})
        tool_name = function.get("name", "unknown_tool")
        args_str = function.get("arguments", "{}")

        try:
            parsed_args: Any = json.loads(args_str) if args_str else {}
        except json.JSONDecodeError:
            parsed_args = {"_raw_arguments": args_str}

        payload = {
            "turn": turn,
            "call_index": call_index,
            "total_calls": total_calls,
            "tool_name": tool_name,
            "arguments": parsed_args,
        }
        if self.verbose_output_callback:
            self.verbose_output_callback(payload)
            return
        logger.info(
            "Tool %s/%s | Turn %s | %s | args=%s",
            call_index,
            total_calls,
            turn,
            tool_name,
            parsed_args,
        )

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
                    val_content = value.get("content", "")
                    if len(val_content) > 500:
                        summary = self._summarize_and_cache(key, val_content)
                        compacted_data[key] = value.copy()
                        compacted_data[key]["content"] = f"[COMPACTED] {summary}"
                        compacted_data[key]["note"] = (
                            "Content replaced with on-demand summary to save context."
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
                        summary = self._summarize_and_cache(key, value)
                        compacted_data[key] = f"[COMPACTED] {summary}"
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

    def _summarize_and_cache(self, url: str, content: str) -> str:
        """Summarize URL content on demand and persist the result to the research cache.

        Returns the generated summary, or a truncated fallback if summarization fails.
        """
        from asky.summarization import _summarize_content
        from asky.config import SUMMARIZE_PAGE_PROMPT

        SUMMARY_INPUT_CHARS = 24000
        SUMMARY_MAX_OUTPUT_CHARS = 800

        logger.debug(f"[Smart Compaction] Generating on-demand summary for {url}")
        try:
            summary = _summarize_content(
                content=content[:SUMMARY_INPUT_CHARS],
                prompt_template=SUMMARIZE_PAGE_PROMPT,
                max_output_chars=SUMMARY_MAX_OUTPUT_CHARS,
                usage_tracker=self.usage_tracker,
            )
            cache_id = self.research_cache.get_cache_id(url)
            if cache_id is not None:
                self.research_cache._save_summary(cache_id, summary)
                logger.debug(f"[Smart Compaction] Summary saved to cache for {url}")
            return summary
        except Exception as exc:
            logger.warning(
                f"[Smart Compaction] On-demand summarization failed for {url}: {exc}. Falling back to truncation."
            )
            return content[:SUMMARY_MAX_OUTPUT_CHARS] + "... [TRUNCATED]"

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
        self._emit_event(
            "context_compaction_start",
            current_tokens=current_tokens,
            threshold_tokens=threshold_tokens,
        )

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
            self._emit_event(
                "context_compaction_success",
                strategy="smart",
                previous_tokens=current_tokens,
                new_tokens=new_tokens,
            )
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
                self._emit_event(
                    "context_compaction_success",
                    strategy="drop_history",
                    previous_tokens=current_tokens,
                    new_tokens=count_tokens(candidate),
                )
                return candidate

        final_attempt = system_msgs + [last_msg]
        self._emit_event(
            "context_compaction_success",
            strategy="minimal_context",
            previous_tokens=current_tokens,
            new_tokens=count_tokens(final_attempt),
        )
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

    def _handle_400_error(
        self, error: requests.exceptions.HTTPError, messages: List[Dict[str, Any]]
    ) -> None:
        """Raise a non-interactive overflow error for callers to handle."""
        compacted_messages = self.check_and_compact(messages)
        self._emit_event(
            "context_overflow",
            message=str(error),
            compacted_message_count=len(compacted_messages),
        )
        raise ContextOverflowError(
            str(error),
            model_alias=self.model_config.get("alias"),
            model_id=self.model_config.get("id"),
            compacted_messages=compacted_messages,
        ) from error

    def _handle_general_error(self, e):
        logger.info(f"Error: {str(e)}")
        logger.exception("Engine failure")


def create_tool_registry(
    usage_tracker: Optional[UsageTracker] = None,
    summarization_tracker: Optional[UsageTracker] = None,
    summarization_status_callback: Optional[Callable[[Optional[str]], None]] = None,
    summarization_verbose_callback: Optional[Callable[[Any], None]] = None,
    disabled_tools: Optional[Set[str]] = None,
) -> ToolRegistry:
    """Create a ToolRegistry with all default and custom tools."""
    return call_attr(
        "asky.core.tool_registry_factory",
        "create_tool_registry",
        usage_tracker=usage_tracker,
        summarization_tracker=summarization_tracker,
        summarization_status_callback=summarization_status_callback,
        summarization_verbose_callback=summarization_verbose_callback,
        execute_web_search_fn=execute_web_search,
        execute_get_url_content_fn=execute_get_url_content,
        execute_get_url_details_fn=execute_get_url_details,
        execute_custom_tool_fn=_execute_custom_tool,
        custom_tools=CUSTOM_TOOLS,
        disabled_tools=disabled_tools,
    )


def create_research_tool_registry(
    usage_tracker: Optional[UsageTracker] = None,
    disabled_tools: Optional[Set[str]] = None,
    session_id: Optional[str] = None,
    summarization_tracker: Optional[UsageTracker] = None,
) -> ToolRegistry:
    """Create a ToolRegistry with research mode tools."""
    return call_attr(
        "asky.core.tool_registry_factory",
        "create_research_tool_registry",
        usage_tracker=usage_tracker,
        summarization_tracker=summarization_tracker,
        execute_web_search_fn=execute_web_search,
        execute_custom_tool_fn=_execute_custom_tool,
        custom_tools=CUSTOM_TOOLS,
        disabled_tools=disabled_tools,
        session_id=session_id,
    )


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
