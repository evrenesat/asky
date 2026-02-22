"""Storage package for asky."""

from typing import Optional, Union
from asky.config import DB_PATH
from asky.storage.interface import Interaction, HistoryRepository
from asky.storage.sqlite import SQLiteHistoryRepository, Session

# Default repository instance
_repo = SQLiteHistoryRepository()


def init_db() -> None:
    """Initialize the default database."""
    _repo.init_db()


def save_interaction(
    query: str,
    answer: str,
    model: str,
    query_summary: str = "",
    answer_summary: str = "",
) -> int:
    """Save an interaction using the default repository. Returns the assistant message ID."""
    return _repo.save_interaction(query, answer, model, query_summary, answer_summary)


def reserve_interaction(model: str) -> tuple[int, int]:
    """Pre-insert placeholder user and assistant messages to get stable IDs.

    Returns (user_id, assistant_id).
    """
    return _repo.reserve_interaction(model)


def update_interaction(
    user_id: int,
    assistant_id: int,
    query: str,
    answer: str,
    model: str,
    query_summary: str = "",
    answer_summary: str = "",
) -> None:
    """Update previously reserved placeholder messages with real content."""
    _repo.update_interaction(
        user_id, assistant_id, query, answer, model, query_summary, answer_summary
    )


def get_history(limit: int):
    """Get history using the default repository."""
    # Convert to legacy dict format if needed?
    # Actually, let's keep it returning Interaction objects and see if cli needs update.
    # Looking at cli.py, it expects the rows to behave like dicts or have attributes.
    return _repo.get_history(limit)


def get_interaction_context(ids: list[int], full: bool = False) -> str:
    """Get context using the default repository."""
    return _repo.get_interaction_context(ids, full=full)


def delete_messages(
    ids: Optional[str] = None,
    delete_all: bool = False,
) -> int:
    """Delete message history records."""
    return _repo.delete_messages(ids=ids, delete_all=delete_all)


def delete_sessions(
    ids: Optional[str] = None,
    delete_all: bool = False,
) -> int:
    """Delete session records and their messages."""
    return _repo.delete_sessions(ids=ids, delete_all=delete_all)


def get_db_record_count() -> int:
    """Get count using the default repository."""
    return _repo.get_db_record_count()


def get_total_session_count() -> int:
    """Get total session count using the default repository."""
    return _repo.count_sessions()


def create_session(
    model: str,
    name: Optional[str] = None,
    memory_auto_extract: bool = False,
    max_turns: Optional[int] = None,
    research_mode: bool = False,
    research_source_mode: Optional[str] = None,
    research_local_corpus_paths: Optional[list[str]] = None,
) -> int:
    return _repo.create_session(
        model=model,
        name=name,
        memory_auto_extract=memory_auto_extract,
        max_turns=max_turns,
        research_mode=research_mode,
        research_source_mode=research_source_mode,
        research_local_corpus_paths=research_local_corpus_paths,
    )


def get_sessions_by_name(name: str) -> list[Session]:
    """Get all sessions with the given name (for duplicate handling)."""
    return _repo.get_sessions_by_name(name)


def get_session_by_id(session_id: int) -> Optional[Session]:
    return _repo.get_session_by_id(session_id)


def get_session_by_name(name: str) -> Optional[Session]:
    return _repo.get_session_by_name(name)


def save_message(
    session_id: int, role: str, content: str, summary: str, token_count: int
) -> int:
    return _repo.save_message(session_id, role, content, summary, token_count)


def get_session_messages(session_id: int) -> list[Interaction]:
    return _repo.get_session_messages(session_id)


def compact_session(session_id: int, compacted_summary: str) -> None:
    _repo.compact_session(session_id, compacted_summary)


def list_sessions(limit: int) -> list[Session]:
    return _repo.list_sessions(limit)


def get_first_message_preview(session_id: int, max_chars: int = 50) -> str:
    """Get the first user message preview from a session."""
    return _repo.get_first_message_preview(session_id, max_chars)
