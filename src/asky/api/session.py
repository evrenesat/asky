"""Session lifecycle orchestration for API callers."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Type

from asky.core import SessionManager, UsageTracker
from asky.core.session_manager import generate_session_name

from .types import SessionResolution

RESEARCH_SOURCE_MODES = {"web_only", "local_only", "mixed"}


def _serialize_session(session: Any) -> Dict[str, Any]:
    return {
        "id": int(session.id),
        "name": str(session.name or ""),
        "created_at": str(getattr(session, "created_at", "")),
    }


def _normalize_source_mode(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if not normalized or normalized not in RESEARCH_SOURCE_MODES:
        return None
    return normalized


def _normalize_local_corpus_paths(paths: Optional[List[str]]) -> List[str]:
    if not paths:
        return []
    normalized: List[str] = []
    for item in paths:
        path = str(item).strip()
        if path:
            normalized.append(path)
    return normalized


def _default_source_mode(local_paths: List[str]) -> str:
    return "local_only" if local_paths else "web_only"


def _profile_from_session(
    session: Any,
) -> tuple[bool, Optional[str], List[str]]:
    mode = bool(getattr(session, "research_mode", False))
    local_paths = _normalize_local_corpus_paths(
        getattr(session, "research_local_corpus_paths", []) or []
    )
    source_mode = _normalize_source_mode(getattr(session, "research_source_mode", None))
    if mode and source_mode is None:
        source_mode = _default_source_mode(local_paths)
    return mode, source_mode, local_paths


def _build_requested_profile(
    *,
    existing_session: Optional[Any],
    request_research_mode: bool,
    research_flag_provided: bool,
    replace_research_corpus: bool,
    requested_source_mode: Optional[str],
    requested_local_corpus_paths: Optional[List[str]],
) -> tuple[bool, Optional[str], List[str], bool]:
    """Resolve effective research profile and whether persistence is needed."""
    requested_source_mode = _normalize_source_mode(requested_source_mode)
    requested_paths = _normalize_local_corpus_paths(requested_local_corpus_paths)
    explicit_research_request = bool(
        request_research_mode
        or research_flag_provided
        or replace_research_corpus
        or requested_source_mode is not None
        or requested_paths
    )

    if existing_session is None:
        if not explicit_research_request:
            return False, None, [], False
        if replace_research_corpus:
            source_mode = requested_source_mode or _default_source_mode(requested_paths)
            return True, source_mode, requested_paths, True
        return True, _default_source_mode(requested_paths), requested_paths, True

    stored_mode, stored_source_mode, stored_paths = _profile_from_session(existing_session)

    if not explicit_research_request:
        if not stored_mode:
            return False, None, [], False
        return True, stored_source_mode, stored_paths, False

    if replace_research_corpus:
        source_mode = requested_source_mode or _default_source_mode(requested_paths)
        persist_needed = (
            not stored_mode
            or source_mode != stored_source_mode
            or requested_paths != stored_paths
        )
        return True, source_mode, requested_paths, persist_needed

    if stored_mode:
        return True, stored_source_mode, stored_paths, False

    source_mode = requested_source_mode or _default_source_mode(requested_paths)
    return True, source_mode, requested_paths, True


def _apply_session_runtime_flags(
    *,
    session_manager: SessionManager,
    resolution: SessionResolution,
    elephant_mode: bool,
    max_turns: Optional[int],
    shortlist_override: Optional[str] = None,
) -> None:
    session = session_manager.current_session
    if not session:
        return

    if elephant_mode and not session.memory_auto_extract:
        session_manager.repo.set_session_memory_auto_extract(int(session.id), True)
        session.memory_auto_extract = True
    resolution.memory_auto_extract = bool(session.memory_auto_extract)

    if max_turns is not None:
        session_manager.repo.update_session_max_turns(int(session.id), max_turns)
        session.max_turns = max_turns
        resolution.max_turns = max_turns
    else:
        resolution.max_turns = session.max_turns

    if shortlist_override in ("on", "off"):
        session_manager.repo.update_session_shortlist_override(int(session.id), shortlist_override)
        session.shortlist_override = shortlist_override
    elif shortlist_override == "reset":
        session_manager.repo.update_session_shortlist_override(int(session.id), None)
        session.shortlist_override = None
    resolution.shortlist_override = getattr(session, "shortlist_override", None)


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
    research_flag_provided: bool = False,
    research_source_mode: Optional[str] = None,
    replace_research_corpus: bool = False,
    requested_local_corpus_paths: Optional[List[str]] = None,
    elephant_mode: bool = False,
    max_turns: Optional[int] = None,
    shortlist_override: Optional[str] = None,
    set_shell_session_id_fn: Optional[Callable[[int], None]] = None,
    clear_shell_session_fn: Optional[Callable[[], None]] = None,
    session_manager_cls: Type[SessionManager] = SessionManager,
) -> tuple[Optional[SessionManager], SessionResolution]:
    """Resolve session state and return active manager plus resolution metadata."""
    resolution = SessionResolution()
    session_manager: Optional[SessionManager] = None
    session_command_only = False

    if sticky_session_name:
        session_manager = session_manager_cls(
            model_config,
            usage_tracker,
            summarization_tracker=summarization_tracker,
        )
        created_session = session_manager.create_session(
            sticky_session_name,
            memory_auto_extract=elephant_mode,
            max_turns=max_turns,
        )
        session_manager.repo.update_session_last_used(int(created_session.id))
        if set_shell_session_id_fn:
            set_shell_session_id_fn(int(created_session.id))
        resolution.session_id = int(created_session.id)
        resolution.event = "session_created"
        resolution.notices.append(
            f"Session {created_session.id} ('{created_session.name}') created and active"
        )
        if not query_text:
            session_command_only = True

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
        resolution.notices.append(
            f"Resumed session {resumed.id} ('{resumed.name or 'auto'}')"
        )
        if not query_text:
            session_command_only = True

    if not sticky_session_name and not resume_session_term and shell_session_id:
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
            resolution.notices.append(
                f"Resuming session {session.id} ({session.name or 'auto'})"
            )
        else:
            if clear_shell_session_fn:
                clear_shell_session_fn()
            session_manager = None
            resolution.event = "session_auto_resume_missing"
            resolution.notices.append("Cleared stale shell session lock")

    existing_session = (
        session_manager.current_session if session_manager else None
    )
    (
        effective_research_mode,
        effective_source_mode,
        effective_local_paths,
        persist_profile,
    ) = _build_requested_profile(
        existing_session=existing_session,
        request_research_mode=bool(research_mode),
        research_flag_provided=bool(research_flag_provided),
        replace_research_corpus=bool(replace_research_corpus),
        requested_source_mode=research_source_mode,
        requested_local_corpus_paths=requested_local_corpus_paths,
    )

    if effective_research_mode and (not session_manager or not session_manager.current_session):
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
            research_source_mode=effective_source_mode,
            research_local_corpus_paths=effective_local_paths,
        )
        if created:
            resolution.event = "research_session_created"
            resolution.notices.append(
                f"Research mode: started session {created.id} ('{created.name or 'auto'}')"
            )
            resolution.session_id = int(created.id)
            persist_profile = False
    if session_manager and session_manager.current_session:
        current_session = session_manager.current_session
        resolution.session_id = int(current_session.id)
        if persist_profile:
            session_manager.update_current_session_research_profile(
                research_mode=effective_research_mode,
                research_source_mode=effective_source_mode,
                research_local_corpus_paths=effective_local_paths,
            )
            current_session = session_manager.current_session or current_session
        session_manager.repo.update_session_last_used(int(current_session.id))
        _apply_session_runtime_flags(
            session_manager=session_manager,
            resolution=resolution,
            elephant_mode=elephant_mode,
            max_turns=max_turns,
            shortlist_override=shortlist_override,
        )
    else:
        resolution.memory_auto_extract = False
        resolution.max_turns = max_turns

    resolution.research_mode = effective_research_mode
    resolution.research_source_mode = (
        effective_source_mode if effective_research_mode else None
    )
    resolution.research_local_corpus_paths = (
        effective_local_paths if effective_research_mode else []
    )

    if session_command_only:
        resolution.halt_reason = "session_command_only"
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
    research_source_mode: Optional[str] = None,
    research_local_corpus_paths: Optional[List[str]] = None,
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
        session_name,
        memory_auto_extract=elephant_mode,
        max_turns=max_turns,
        research_mode=True,
        research_source_mode=research_source_mode or "web_only",
        research_local_corpus_paths=_normalize_local_corpus_paths(
            research_local_corpus_paths
        ),
    )
    if set_shell_session_id_fn:
        set_shell_session_id_fn(int(created_session.id))
    return active_manager, created_session
