"""Programmatic client for asky conversation workflows."""

from __future__ import annotations

import copy
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
from asky.lazy_imports import call_attr
from asky.storage import save_interaction

from .context import load_context_from_history
from .preload import (
    build_shortlist_stats,
    format_local_ingestion_context,
    format_shortlist_context,
    preload_local_research_sources,
    run_preload_pipeline,
    shortlist_prompt_sources,
)
from .session import resolve_session_for_turn
from .types import (
    AskyChatResult,
    AskyConfig,
    AskyTurnRequest,
    AskyTurnResult,
    ContextResolution,
    PreloadResolution,
    SessionResolution,
)


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
        base_model_config = copy.deepcopy(MODELS[config.model_alias])
        merged_parameters = {
            **(base_model_config.get("parameters") or {}),
            **dict(config.model_parameters_override or {}),
        }
        if merged_parameters:
            base_model_config["parameters"] = merged_parameters
        self.model_config = base_model_config
        self.usage_tracker = usage_tracker or UsageTracker()
        self.summarization_tracker = summarization_tracker or UsageTracker()

    def build_messages(
        self,
        *,
        query_text: str,
        context_str: str = "",
        session_manager: Optional[SessionManager] = None,
        source_shortlist_context: Optional[str] = None,
        local_kb_hint_enabled: bool = False,
    ) -> List[Dict[str, str]]:
        """Build a message list for a single asky turn."""
        system_prompt = (
            construct_research_system_prompt()
            if self.config.research_mode
            else construct_system_prompt()
        )
        if local_kb_hint_enabled and self.config.research_mode:
            system_prompt = (
                f"{system_prompt}\n\n"
                "Local Knowledge Base Guidance:\n"
                "- Local corpus sources were preloaded from configured document roots.\n"
                "- Do not ask the user for local filesystem paths.\n"
                "- Start by calling `query_research_memory` with the user's question to retrieve local knowledge base findings."
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
        messages[0]["content"] = f"{messages[0].get('content', '')}\n" + "\n".join(
            guideline_lines
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

    def run_turn(
        self,
        request: AskyTurnRequest,
        *,
        display_callback: Optional[Callable[..., None]] = None,
        verbose_output_callback: Optional[Callable[[Any], None]] = None,
        summarization_status_callback: Optional[Callable[[Optional[str]], None]] = None,
        event_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        preload_status_callback: Optional[Callable[[str], None]] = None,
        messages_prepared_callback: Optional[
            Callable[[List[Dict[str, Any]]], None]
        ] = None,
        set_shell_session_id_fn: Optional[Callable[[int], None]] = None,
        clear_shell_session_fn: Optional[Callable[[], None]] = None,
        shortlist_executor: Optional[Callable[..., Dict[str, Any]]] = None,
        shortlist_formatter: Optional[Callable[[Dict[str, Any]], str]] = None,
        shortlist_stats_builder: Optional[
            Callable[[Dict[str, Any], float], Dict[str, Any]]
        ] = None,
        local_ingestion_executor: Optional[Callable[..., Dict[str, Any]]] = None,
        local_ingestion_formatter: Optional[
            Callable[[Dict[str, Any]], Optional[str]]
        ] = None,
    ) -> AskyTurnResult:
        """Run a full API-orchestrated turn including context/session/preload."""
        notices: List[str] = []
        context = ContextResolution()

        if request.continue_ids:
            context = load_context_from_history(
                request.continue_ids,
                request.summarize_context,
            )
            if context.resolved_ids:
                notices.append(
                    "Loaded context from IDs: "
                    + ", ".join(str(item) for item in context.resolved_ids)
                )

        session_manager, session_resolution = resolve_session_for_turn(
            model_config=self.model_config,
            usage_tracker=self.usage_tracker,
            summarization_tracker=self.summarization_tracker,
            query_text=request.query_text,
            sticky_session_name=request.sticky_session_name,
            resume_session_term=request.resume_session_term,
            shell_session_id=request.shell_session_id,
            research_mode=self.config.research_mode,
            set_shell_session_id_fn=set_shell_session_id_fn,
            clear_shell_session_fn=clear_shell_session_fn,
        )
        notices.extend(session_resolution.notices)

        if self.config.research_mode:
            notices.insert(
                0, "Research mode enabled - using link extraction and RAG tools"
            )

        halted = bool(session_resolution.halt_reason)
        if halted:
            return AskyTurnResult(
                final_answer="",
                query_summary="",
                answer_summary="",
                messages=[],
                model_alias=self.config.model_alias,
                session_id=(
                    str(session_resolution.session_id)
                    if session_resolution.session_id is not None
                    else None
                ),
                halted=True,
                halt_reason=session_resolution.halt_reason,
                notices=notices,
                context=context,
                session=session_resolution,
                preload=PreloadResolution(),
            )

        preload = run_preload_pipeline(
            query_text=request.query_text,
            research_mode=self.config.research_mode,
            model_config=self.model_config,
            lean=request.lean,
            preload_local_sources=request.preload_local_sources,
            preload_shortlist=request.preload_shortlist,
            additional_source_context=request.additional_source_context,
            local_corpus_paths=request.local_corpus_paths,
            status_callback=preload_status_callback,
            shortlist_executor=shortlist_executor or shortlist_prompt_sources,
            shortlist_formatter=shortlist_formatter or format_shortlist_context,
            shortlist_stats_builder=shortlist_stats_builder or build_shortlist_stats,
            local_ingestion_executor=(
                local_ingestion_executor or preload_local_research_sources
            ),
            local_ingestion_formatter=(
                local_ingestion_formatter or format_local_ingestion_context
            ),
        )

        local_targets = preload.local_payload.get("targets") or []
        effective_query_text = request.query_text
        local_kb_hint_enabled = bool(local_targets) or bool(request.local_corpus_paths)
        if local_kb_hint_enabled:
            effective_query_text = call_attr(
                "asky.research.adapters",
                "redact_local_source_targets",
                request.query_text,
            )
            if not effective_query_text.strip():
                effective_query_text = "Answer the user's request using the preloaded local knowledge base."

        messages = self.build_messages(
            query_text=effective_query_text,
            context_str=context.context_str,
            session_manager=session_manager,
            source_shortlist_context=preload.combined_context,
            local_kb_hint_enabled=local_kb_hint_enabled,
        )
        if messages_prepared_callback:
            messages_prepared_callback(messages)

        final_answer = self.run_messages(
            messages,
            session_manager=session_manager,
            research_session_id=(
                str(session_manager.current_session.id)
                if session_manager and session_manager.current_session
                else None
            ),
            display_callback=display_callback,
            verbose_output_callback=verbose_output_callback,
            summarization_status_callback=summarization_status_callback,
            event_callback=event_callback,
        )

        query_summary, answer_summary = ("", "")
        if final_answer:
            query_summary, answer_summary = generate_summaries(
                request.query_text,
                final_answer,
                usage_tracker=self.summarization_tracker,
            )
            if request.save_history:
                if session_manager:
                    session_manager.save_turn(
                        request.query_text,
                        final_answer,
                        query_summary,
                        answer_summary,
                    )
                    if session_manager.check_and_compact():
                        notices.append("Session context compacted")
                else:
                    save_interaction(
                        request.query_text,
                        final_answer,
                        self.config.model_alias,
                        query_summary,
                        answer_summary,
                    )

        return AskyTurnResult(
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
            halted=False,
            halt_reason=None,
            notices=notices,
            context=context,
            session=session_resolution,
            preload=preload,
        )
