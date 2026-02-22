"""Programmatic client for asky conversation workflows."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Set, TYPE_CHECKING

from asky.config import MODELS
from asky.core import (
    ConversationEngine,
    UsageTracker,
    construct_research_system_prompt,
    construct_system_prompt,
    generate_summaries,
    SessionManager,
    append_research_guidance,
)
from asky.core.tool_registry_factory import (
    create_tool_registry,
    create_research_tool_registry,
)
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


@dataclass
class FinalizeResult:
    """Result of history finalization."""

    notices: List[str]
    saved_message_id: Optional[int] = None


STANDARD_SEED_DIRECT_ANSWER_DISABLED_TOOLS: FrozenSet[str] = frozenset(
    {"web_search", "get_url_content", "get_url_details"}
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
        preload: Optional[PreloadResolution] = None,
        local_kb_hint_enabled: bool = False,
    ) -> List[Dict[str, Any]]:
        """Build a message list for a single asky turn."""
        if self.config.system_prompt_override:
            system_prompt = self.config.system_prompt_override
        else:
            system_prompt = (
                construct_research_system_prompt()
                if self.config.research_mode
                else construct_system_prompt()
            )

        if self.config.research_mode:
            system_prompt = append_research_guidance(
                system_prompt,
                corpus_preloaded=preload.is_corpus_preloaded if preload else False,
                local_kb_hint_enabled=local_kb_hint_enabled,
            )

        messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]

        if preload and preload.memory_context:
            messages[0]["content"] += f"\n\n{preload.memory_context}"

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
        if preload and preload.combined_context:
            preload_instruction = (
                "Use this preloaded corpus as a starting point, then verify with tools before citing."
            )
            if preload.seed_url_direct_answer_ready:
                preload_instruction = (
                    "Seed URL content is already preloaded with full_content status. "
                    "Answer directly from that content and do NOT call get_url_content/"
                    "get_url_details for the same URL unless the user explicitly asks "
                    "for a fresh fetch or the provided content is clearly incomplete."
                )
            user_content = (
                f"{query_text}\n\n"
                f"Preloaded sources gathered before tool calls:\n"
                f"{preload.combined_context}\n\n"
                f"{preload_instruction}"
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

    def _should_use_seed_direct_answer_mode(
        self,
        *,
        request: AskyTurnRequest,
        preload: PreloadResolution,
    ) -> bool:
        """Return whether this turn should answer directly from preloaded seed content."""
        return (
            not self.config.research_mode
            and not request.lean
            and preload.seed_url_direct_answer_ready
        )

    def _resolve_run_turn_disabled_tools(
        self,
        *,
        request: AskyTurnRequest,
        preload: PreloadResolution,
    ) -> tuple[Optional[Set[str]], bool]:
        """Resolve turn-scoped tool disablement policy for run_turn."""
        if request.lean:
            from asky.core.tool_registry_factory import get_all_available_tool_names

            disabled = set(self.config.disabled_tools)
            disabled.update(get_all_available_tool_names())
            return disabled, False

        if self._should_use_seed_direct_answer_mode(request=request, preload=preload):
            disabled = set(self.config.disabled_tools)
            disabled.update(STANDARD_SEED_DIRECT_ANSWER_DISABLED_TOOLS)
            return disabled, True

        return None, False

    def run_messages(
        self,
        messages: List[Dict[str, Any]],
        *,
        session_manager: Optional[SessionManager] = None,
        research_session_id: Optional[str] = None,
        preload: Optional[PreloadResolution] = None,
        display_callback: Optional[
            Callable[[int, Optional[str], bool, Optional[str]], None]
        ] = None,
        verbose_output_callback: Optional[Callable[[Any], None]] = None,
        summarization_status_callback: Optional[Callable[[Optional[str]], None]] = None,
        event_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        lean: bool = False,
        disabled_tools: Optional[Set[str]] = None,
        max_turns: Optional[int] = None,
    ) -> str:
        """Run chat completion for prepared messages."""
        effective_disabled_tools = (
            disabled_tools if disabled_tools is not None else self.config.disabled_tools
        )

        if self.config.research_mode:
            registry = create_research_tool_registry(
                usage_tracker=self.usage_tracker,
                disabled_tools=effective_disabled_tools,
                session_id=research_session_id,
                corpus_preloaded=preload.is_corpus_preloaded if preload else False,
                summarization_tracker=self.summarization_tracker,
                tool_trace_callback=(
                    verbose_output_callback if self.config.verbose else None
                ),
            )
        else:
            registry = create_tool_registry(
                usage_tracker=self.usage_tracker,
                summarization_tracker=self.summarization_tracker,
                summarization_status_callback=summarization_status_callback,
                summarization_verbose_callback=(
                    verbose_output_callback if self.config.verbose else None
                ),
                disabled_tools=effective_disabled_tools,
                tool_trace_callback=(
                    verbose_output_callback if self.config.verbose else None
                ),
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
            double_verbose=self.config.double_verbose,
            usage_tracker=self.usage_tracker,
            open_browser=self.config.open_browser,
            session_manager=session_manager,
            verbose_output_callback=verbose_output_callback,
            event_callback=event_callback,
            lean=lean,
            max_turns=max_turns,
        )
        return engine.run(messages, display_callback=display_callback)

    def chat(
        self,
        *,
        query_text: str,
        context_str: str = "",
        session_manager: Optional[SessionManager] = None,
        research_session_id: Optional[str] = None,
        preload: Optional[PreloadResolution] = None,
        display_callback: Optional[Callable[..., None]] = None,
        verbose_output_callback: Optional[Callable[[Any], None]] = None,
        summarization_status_callback: Optional[Callable[[Optional[str]], None]] = None,
        event_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        lean: bool = False,
    ) -> AskyChatResult:
        """Run a simplified chat turn without session/preload orchestration."""
        messages = self.build_messages(
            query_text=query_text,
            context_str=context_str,
            session_manager=session_manager,
            preload=preload,
        )
        final_answer = self.run_messages(
            messages,
            session_manager=session_manager,
            research_session_id=research_session_id,
            preload=preload,
            display_callback=display_callback,
            verbose_output_callback=verbose_output_callback,
            summarization_status_callback=summarization_status_callback,
            event_callback=event_callback,
            lean=lean,
        )

        query_summary, answer_summary = ("", "")

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
        session_resolved_callback: Optional[Callable[[Any], None]] = None,
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
        initial_notice_callback: Optional[Callable[[str], None]] = None,
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
            elephant_mode=request.elephant_mode,
            max_turns=request.max_turns,
            set_shell_session_id_fn=set_shell_session_id_fn,
            clear_shell_session_fn=clear_shell_session_fn,
        )
        notices.extend(session_resolution.notices)

        if session_resolved_callback and session_manager:
            session_resolved_callback(session_manager)

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

        capture_global_memory = False
        effective_query_text = request.query_text

        if not request.lean:
            # Global Memory Trigger Detection
            from asky.config import USER_MEMORY_GLOBAL_TRIGGERS

            for trigger in USER_MEMORY_GLOBAL_TRIGGERS:
                if effective_query_text.lower().startswith(trigger.lower()):
                    # Strip trigger and whitespace
                    effective_query_text = effective_query_text[len(trigger) :].strip()
                    capture_global_memory = True
                    notices.append(f"Global memory trigger detected: '{trigger}'")
                    break

        if initial_notice_callback:
            for notice in notices:
                initial_notice_callback(notice)
            notices.clear()

        # Process preload with *potentially modified* query text
        preload = run_preload_pipeline(
            query_text=effective_query_text,
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
        # Preload pipeline might have used original query (if we didn't update it above, but we did)
        # However, run_preload_pipeline does its own things.
        # We need to make sure subsequent steps use effective_query_text.

        local_kb_hint_enabled = bool(local_targets) or bool(request.local_corpus_paths)
        if local_kb_hint_enabled:
            effective_query_text = call_attr(
                "asky.research.adapters",
                "redact_local_source_targets",
                effective_query_text,
            )
            if not effective_query_text.strip():
                effective_query_text = "Answer the user's request using the preloaded local knowledge base."

        messages = self.build_messages(
            query_text=effective_query_text,
            context_str=context.context_str,
            session_manager=session_manager,
            preload=preload,
            local_kb_hint_enabled=local_kb_hint_enabled,
        )
        if messages_prepared_callback:
            messages_prepared_callback(messages)

        effective_disabled_tools, seed_direct_mode_enabled = (
            self._resolve_run_turn_disabled_tools(
                request=request,
                preload=preload,
            )
        )
        if seed_direct_mode_enabled:
            direct_mode_notice = (
                "Direct-answer preload mode enabled: disabled web_search, "
                "get_url_content, and get_url_details for this turn."
            )
            if initial_notice_callback:
                initial_notice_callback(direct_mode_notice)
            else:
                notices.append(direct_mode_notice)

        import threading
        from asky.config import DB_PATH, RESEARCH_CHROMA_PERSIST_DIRECTORY, MAX_TURNS
        from asky.core.api_client import get_llm_msg

        effective_max_turns = (
            session_resolution.max_turns
            or request.max_turns
            or self.model_config.get("max_turns", MAX_TURNS)
        )

        final_answer = self.run_messages(
            messages,
            session_manager=session_manager,
            research_session_id=(
                str(session_manager.current_session.id)
                if session_manager and session_manager.current_session
                else None
            ),
            preload=preload,
            display_callback=display_callback,
            verbose_output_callback=verbose_output_callback,
            summarization_status_callback=summarization_status_callback,
            event_callback=event_callback,
            lean=request.lean,
            disabled_tools=effective_disabled_tools,
            max_turns=effective_max_turns,
        )

        if not request.lean:
            # Auto-extraction of facts

            # 1. Session-scoped extraction (Elephant Mode)
            if final_answer and session_resolution.memory_auto_extract:
                # We must pass the current session ID
                current_sid = (
                    session_manager.current_session.id
                    if session_manager and session_manager.current_session
                    else None
                )
                threading.Thread(
                    target=call_attr,
                    args=(
                        "asky.memory.auto_extract",
                        "extract_and_save_memories_from_turn",
                    ),
                    kwargs={
                        "query": effective_query_text,
                        "answer": final_answer,
                        "llm_client": get_llm_msg,
                        "model": self.model_config.get("model", ""),
                        "db_path": DB_PATH,
                        "chroma_dir": RESEARCH_CHROMA_PERSIST_DIRECTORY,
                        "session_id": current_sid,
                    },
                    daemon=True,
                ).start()

            # 2. Global extraction (Triggered)
            if final_answer and capture_global_memory:
                threading.Thread(
                    target=call_attr,
                    args=("asky.memory.auto_extract", "extract_global_facts_from_turn"),
                    kwargs={
                        "query": effective_query_text,
                        "answer": final_answer,
                        "llm_client": get_llm_msg,
                        "model": self.model_config.get("model", ""),
                        "db_path": DB_PATH,
                        "chroma_dir": RESEARCH_CHROMA_PERSIST_DIRECTORY,
                    },
                    daemon=True,
                ).start()

        query_summary, answer_summary = ("", "")
        if final_answer:
            if request.save_history:
                if session_manager:
                    session_manager.save_turn(
                        request.query_text,
                        final_answer,
                        query_summary,  # We now use lazy evaluate context time
                        answer_summary,
                    )
                    if not request.lean and session_manager.check_and_compact():
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

    def finalize_turn_history(
        self,
        request: "AskyTurnRequest",
        result: "AskyTurnResult",
        summarization_status_callback: Optional[Callable[[str], None]] = None,
        pre_reserved_message_ids: Optional[tuple[int, int]] = None,
    ) -> FinalizeResult:
        """Save interaction/session history and perform compaction if needed.

        This can be called manually by clients who set request.save_history = False
        to defer saving until after rendering operations.
        """
        notices = []
        saved_message_id = None
        if not result.final_answer:
            return FinalizeResult(notices=notices)

        from asky.storage import save_interaction, update_interaction
        from asky.core.session_manager import SessionManager

        if result.session_id:
            session_manager = SessionManager(
                model_config=self.model_config,
                usage_tracker=self.usage_tracker,
                summarization_tracker=self.summarization_tracker,
            )
            session_manager.current_session = getattr(
                result.session,
                "current_session",
                session_manager.repo.get_session_by_id(int(result.session_id)),
            )

            if summarization_status_callback:
                summarization_status_callback("Saving session message...")

            saved_message_id = session_manager.save_turn(
                request.query_text,
                result.final_answer,
                result.query_summary,
                result.answer_summary,
            )
            if not request.lean:
                if summarization_status_callback:
                    summarization_status_callback("Checking context limits...")
                if session_manager.check_and_compact():
                    notices.append("Session context compacted")
        else:
            if pre_reserved_message_ids:
                if summarization_status_callback:
                    summarization_status_callback("Updating reserved interaction...")
                user_id, assistant_id = pre_reserved_message_ids
                update_interaction(
                    user_id,
                    assistant_id,
                    request.query_text,
                    result.final_answer,
                    self.config.model_alias,
                    result.query_summary,
                    result.answer_summary,
                )
                saved_message_id = assistant_id
            else:
                if summarization_status_callback:
                    summarization_status_callback("Saving interaction...")
                saved_message_id = save_interaction(
                    request.query_text,
                    result.final_answer,
                    self.config.model_alias,
                    result.query_summary,
                    result.answer_summary,
                )

        return FinalizeResult(notices=notices, saved_message_id=saved_message_id)

    def cleanup_session_research_data(self, session_id: str) -> dict:
        """Delete research findings and vectors for a session.

        Returns {"deleted": int} — count of findings/vectors removed.
        """
        from asky.research.vector_store import VectorStore

        vector_store = VectorStore()
        # VectorStore handles both ChromaDB embeddings and SQLite row deletion
        deleted = vector_store.delete_findings_by_session(str(session_id))

        return {"deleted": deleted}
