"""Programmatic client for asky conversation workflows."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from asky.config import MODELS
from asky.core import (
    ConversationEngine,
    UsageTracker,
    construct_research_system_prompt,
    construct_system_prompt,
    create_default_tool_registry,
    create_research_tool_registry,
    generate_summaries,
)
from asky.core.session_manager import SessionManager

from .types import AskyChatResult, AskyConfig


class AskyClient:
    """Library entry point for running asky chats without CLI coupling."""

    def __init__(
        self,
        config: AskyConfig,
        *,
        usage_tracker: Optional[UsageTracker] = None,
        summarization_tracker: Optional[UsageTracker] = None,
    ) -> None:
        if config.model_alias not in MODELS:
            raise ValueError(f"Unknown model alias: {config.model_alias}")
        self.config = config
        self.model_config = MODELS[config.model_alias]
        self.usage_tracker = usage_tracker or UsageTracker()
        self.summarization_tracker = summarization_tracker or UsageTracker()

    def build_messages(
        self,
        *,
        query_text: str,
        context_str: str = "",
        session_manager: Optional[SessionManager] = None,
        source_shortlist_context: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """Build a message list for a single asky turn."""
        system_prompt = (
            construct_research_system_prompt()
            if self.config.research_mode
            else construct_system_prompt()
        )
        messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]

        if session_manager:
            messages.extend(session_manager.build_context_messages())
        elif context_str:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Context from previous queries:\n"
                        f"{context_str}\n\n"
                        "My new query is below."
                    ),
                }
            )

        user_content = query_text
        if source_shortlist_context:
            user_content = (
                f"{query_text}\n\n"
                "Preloaded sources gathered before tool calls:\n"
                f"{source_shortlist_context}\n\n"
                "Use this preloaded corpus as a starting point, then verify with tools before citing."
            )

        messages.append({"role": "user", "content": user_content})
        return messages

    def _append_enabled_tool_guidelines(
        self, messages: List[Dict[str, str]], tool_guidelines: List[str]
    ) -> None:
        if not tool_guidelines:
            return
        if not messages or messages[0].get("role") != "system":
            return

        guideline_lines = [
            "",
            "Enabled Tool Guidelines:",
            *[f"- {guideline}" for guideline in tool_guidelines],
        ]
        messages[0]["content"] = (
            f"{messages[0].get('content', '')}\n" + "\n".join(guideline_lines)
        )

    def run_messages(
        self,
        messages: List[Dict[str, Any]],
        *,
        session_manager: Optional[SessionManager] = None,
        research_session_id: Optional[str] = None,
        display_callback: Optional[Callable[..., None]] = None,
        verbose_output_callback: Optional[Callable[[Any], None]] = None,
        summarization_status_callback: Optional[Callable[[Optional[str]], None]] = None,
        event_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> str:
        """Run chat completion for prepared messages."""
        if self.config.research_mode:
            registry = create_research_tool_registry(
                usage_tracker=self.usage_tracker,
                disabled_tools=set(self.config.disabled_tools),
                session_id=research_session_id,
            )
        else:
            registry = create_default_tool_registry(
                usage_tracker=self.usage_tracker,
                summarization_tracker=self.summarization_tracker,
                summarization_status_callback=summarization_status_callback,
                summarization_verbose_callback=(
                    verbose_output_callback if self.config.verbose else None
                ),
                disabled_tools=set(self.config.disabled_tools),
            )

        self._append_enabled_tool_guidelines(
            messages,
            registry.get_system_prompt_guidelines(),
        )

        engine = ConversationEngine(
            model_config=self.model_config,
            tool_registry=registry,
            summarize=self.config.summarize,
            verbose=self.config.verbose,
            usage_tracker=self.usage_tracker,
            open_browser=self.config.open_browser,
            session_manager=session_manager,
            verbose_output_callback=verbose_output_callback,
            event_callback=event_callback,
        )
        return engine.run(messages, display_callback=display_callback)

    def chat(
        self,
        *,
        query_text: str,
        context_str: str = "",
        session_manager: Optional[SessionManager] = None,
        research_session_id: Optional[str] = None,
        source_shortlist_context: Optional[str] = None,
        display_callback: Optional[Callable[..., None]] = None,
        verbose_output_callback: Optional[Callable[[Any], None]] = None,
        summarization_status_callback: Optional[Callable[[Optional[str]], None]] = None,
        event_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> AskyChatResult:
        """Run a complete chat turn and return structured result data."""
        messages = self.build_messages(
            query_text=query_text,
            context_str=context_str,
            session_manager=session_manager,
            source_shortlist_context=source_shortlist_context,
        )
        final_answer = self.run_messages(
            messages,
            session_manager=session_manager,
            research_session_id=research_session_id,
            display_callback=display_callback,
            verbose_output_callback=verbose_output_callback,
            summarization_status_callback=summarization_status_callback,
            event_callback=event_callback,
        )
        query_summary, answer_summary = ("", "")
        if final_answer:
            query_summary, answer_summary = generate_summaries(
                query_text,
                final_answer,
                usage_tracker=self.summarization_tracker,
            )
        return AskyChatResult(
            final_answer=final_answer,
            query_summary=query_summary,
            answer_summary=answer_summary,
            messages=messages,
            model_alias=self.config.model_alias,
            session_id=(
                str(session_manager.current_session.id)
                if session_manager and session_manager.current_session
                else None
            ),
        )
