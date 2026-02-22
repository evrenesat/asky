"""Session lifecycle orchestration for API callers."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Type

from asky.core import SessionManager, UsageTracker
from asky.core.session_manager import generate_session_name

from .types import SessionResolution


def _serialize_session(session: Any) -> Dict[str, Any]:
    return {
        "id": int(session.id),
        "name": str(session.name or ""),
        "created_at": str(getattr(session, "created_at", "")),
    }


def resolve_session_for_turn(
    *,
    model_config: Dict[str, Any],
    usage_tracker: UsageTracker,
    summarization_tracker: UsageTracker,
    query_text: str,
    sticky_session_name: Optional[str] = None,
    resume_session_term: Optional[str] = None,
    shell_session_id: Optional[int] = None,
    research_mode: bool = False,
    elephant_mode: bool = False,
    max_turns: Optional[int] = None,
    set_shell_session_id_fn: Optional[Callable[[int], None]] = None,
    clear_shell_session_fn: Optional[Callable[[], None]] = None,
    session_manager_cls: Type[SessionManager] = SessionManager,
) -> tuple[Optional[SessionManager], SessionResolution]:
    """Resolve session state and return active manager plus resolution metadata."""
    resolution = SessionResolution()
    session_manager: Optional[SessionManager] = None

    if sticky_session_name:
        session_manager = session_manager_cls(
            model_config,
            usage_tracker,
            summarization_tracker=summarization_tracker,
        )
        created_session = session_manager.create_session(
            sticky_session_name, memory_auto_extract=elephant_mode, max_turns=max_turns
        )
        session_manager.repo.update_session_last_used(int(created_session.id))
        if set_shell_session_id_fn:
            set_shell_session_id_fn(int(created_session.id))
        resolution.session_id = int(created_session.id)
        resolution.event = "session_created"
        resolution.memory_auto_extract = bool(created_session.memory_auto_extract)
        resolution.max_turns = created_session.max_turns
        resolution.notices.append(
            f"Session {created_session.id} ('{created_session.name}') created and active"
        )
        if not query_text:
            resolution.halt_reason = "session_command_only"
        return session_manager, resolution

    if resume_session_term:
        session_manager = session_manager_cls(
            model_config,
            usage_tracker,
            summarization_tracker=summarization_tracker,
        )
        matches = session_manager.find_sessions(resume_session_term)
        if not matches:
            resolution.event = "session_resume_not_found"
            resolution.halt_reason = "session_not_found"
            resolution.notices.append(
                f"No sessions found matching '{resume_session_term}'"
            )
            return None, resolution
        if len(matches) > 1:
            resolution.event = "session_resume_ambiguous"
            resolution.halt_reason = "session_ambiguous"
            resolution.matched_sessions = [_serialize_session(s) for s in matches]
            resolution.notices.append(
                f"Multiple sessions found for '{resume_session_term}'"
            )
            return None, resolution

        resumed = matches[0]
        session_manager.current_session = resumed
        session_manager.repo.update_session_last_used(int(resumed.id))
        if set_shell_session_id_fn:
            set_shell_session_id_fn(int(resumed.id))
        resolution.session_id = int(resumed.id)
        resolution.event = "session_resumed"

        if elephant_mode and not resumed.memory_auto_extract:
            session_manager.repo.set_session_memory_auto_extract(int(resumed.id), True)
            resolution.memory_auto_extract = True
        else:
            resolution.memory_auto_extract = bool(resumed.memory_auto_extract)

        if max_turns is not None:
            session_manager.repo.update_session_max_turns(int(resumed.id), max_turns)
            resumed.max_turns = max_turns
            resolution.max_turns = max_turns
        else:
            resolution.max_turns = resumed.max_turns

        resolution.notices.append(
            f"Resumed session {resumed.id} ('{resumed.name or 'auto'}')"
        )
        if not query_text:
            resolution.halt_reason = "session_command_only"
        return session_manager, resolution

    if shell_session_id:
        session_manager = session_manager_cls(
            model_config,
            usage_tracker,
            summarization_tracker=summarization_tracker,
        )
        session = session_manager.repo.get_session_by_id(shell_session_id)
        if session:
            session_manager.current_session = session
            session_manager.repo.update_session_last_used(int(session.id))
            resolution.session_id = int(session.id)
            resolution.event = "session_auto_resumed"
            resolution.memory_auto_extract = bool(session.memory_auto_extract)

            if max_turns is not None:
                session_manager.repo.update_session_max_turns(
                    int(session.id), max_turns
                )
                session.max_turns = max_turns
                resolution.max_turns = max_turns
            else:
                resolution.max_turns = session.max_turns

            resolution.notices.append(
                f"Resuming session {session.id} ({session.name or 'auto'})"
            )
        else:
            if clear_shell_session_fn:
                clear_shell_session_fn()
            session_manager = None
            resolution.event = "session_auto_resume_missing"
            resolution.notices.append("Cleared stale shell session lock")

    if research_mode:
        session_manager, created = ensure_research_session(
            session_manager=session_manager,
            model_config=model_config,
            usage_tracker=usage_tracker,
            summarization_tracker=summarization_tracker,
            query_text=query_text,
            elephant_mode=elephant_mode,
            max_turns=max_turns,
            set_shell_session_id_fn=set_shell_session_id_fn,
            session_manager_cls=session_manager_cls,
        )
        if created:
            resolution.event = "research_session_created"
            resolution.memory_auto_extract = bool(created.memory_auto_extract)
            resolution.max_turns = created.max_turns
            resolution.notices.append(
                f"Research mode: started session {created.id} ('{created.name or 'auto'}')"
            )
            resolution.session_id = int(created.id)
        elif session_manager and session_manager.current_session:
            resolution.session_id = int(session_manager.current_session.id)
            if elephant_mode:
                # propagate elephant mode to existing research session
                if not session_manager.current_session.memory_auto_extract:
                    session_manager.repo.set_session_memory_auto_extract(
                        int(session_manager.current_session.id), True
                    )
                resolution.memory_auto_extract = True
            else:
                resolution.memory_auto_extract = bool(
                    session_manager.current_session.memory_auto_extract
                )

            if max_turns is not None:
                session_manager.repo.update_session_max_turns(
                    int(session_manager.current_session.id), max_turns
                )
                session_manager.current_session.max_turns = max_turns
                resolution.max_turns = max_turns

            session_manager.repo.update_session_last_used(
                int(session_manager.current_session.id)
            )
        else:
            resolution.max_turns = session_manager.current_session.max_turns

    return session_manager, resolution


def ensure_research_session(
    *,
    session_manager: Optional[SessionManager],
    model_config: Dict[str, Any],
    usage_tracker: UsageTracker,
    summarization_tracker: UsageTracker,
    query_text: str,
    elephant_mode: bool = False,
    max_turns: Optional[int] = None,
    set_shell_session_id_fn: Optional[Callable[[int], None]] = None,
    session_manager_cls: Type[SessionManager] = SessionManager,
) -> tuple[SessionManager, Optional[Any]]:
    """Ensure a research session exists and return optional created session."""
    if session_manager and session_manager.current_session:
        return session_manager, None

    active_manager = session_manager or session_manager_cls(
        model_config,
        usage_tracker,
        summarization_tracker=summarization_tracker,
    )
    session_name = generate_session_name(query_text or "research")
    created_session = active_manager.create_session(
        session_name, memory_auto_extract=elephant_mode, max_turns=max_turns
    )
    if set_shell_session_id_fn:
        set_shell_session_id_fn(int(created_session.id))
    return active_manager, created_session
