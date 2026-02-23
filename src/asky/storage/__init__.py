"""Storage package for asky."""

from typing import Optional, Union
from asky.config import DB_PATH
from asky.storage.interface import (
    ImageTranscriptRecord,
    Interaction,
    HistoryRepository,
    RoomSessionBinding,
    SessionOverrideFile,
    TranscriptRecord,
)
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


def create_transcript(
    *,
    session_id: int,
    jid: str,
    audio_url: str,
    audio_path: str,
    status: str,
    transcript_text: str = "",
    error: str = "",
    duration_seconds: float | None = None,
) -> TranscriptRecord:
    """Create a transcript row for daemon voice ingestion."""
    return _repo.create_transcript(
        session_id=session_id,
        jid=jid,
        audio_url=audio_url,
        audio_path=audio_path,
        status=status,
        transcript_text=transcript_text,
        error=error,
        duration_seconds=duration_seconds,
    )


def update_transcript(
    *,
    session_id: int,
    session_transcript_id: int,
    status: str,
    transcript_text: str | None = None,
    error: str | None = None,
    duration_seconds: float | None = None,
    used: bool | None = None,
) -> TranscriptRecord | None:
    """Update transcript fields."""
    return _repo.update_transcript(
        session_id=session_id,
        session_transcript_id=session_transcript_id,
        status=status,
        transcript_text=transcript_text,
        error=error,
        duration_seconds=duration_seconds,
        used=used,
    )


def list_transcripts(*, session_id: int, limit: int = 20) -> list[TranscriptRecord]:
    """List transcript rows for one session."""
    return _repo.list_transcripts(session_id=session_id, limit=limit)


def get_transcript(
    *,
    session_id: int,
    session_transcript_id: int,
) -> TranscriptRecord | None:
    """Get one transcript row by session-scoped transcript ID."""
    return _repo.get_transcript(
        session_id=session_id,
        session_transcript_id=session_transcript_id,
    )


def prune_transcripts(*, session_id: int, keep: int) -> list[TranscriptRecord]:
    """Prune oldest transcript rows for one session."""
    return _repo.prune_transcripts(session_id=session_id, keep=keep)


def create_image_transcript(
    *,
    session_id: int,
    jid: str,
    image_url: str,
    image_path: str,
    status: str,
    transcript_text: str = "",
    error: str = "",
    duration_seconds: float | None = None,
) -> ImageTranscriptRecord:
    """Create an image transcript row for daemon image ingestion."""
    return _repo.create_image_transcript(
        session_id=session_id,
        jid=jid,
        image_url=image_url,
        image_path=image_path,
        status=status,
        transcript_text=transcript_text,
        error=error,
        duration_seconds=duration_seconds,
    )


def update_image_transcript(
    *,
    session_id: int,
    session_image_id: int,
    status: str,
    transcript_text: str | None = None,
    error: str | None = None,
    duration_seconds: float | None = None,
    used: bool | None = None,
) -> ImageTranscriptRecord | None:
    """Update image transcript fields."""
    return _repo.update_image_transcript(
        session_id=session_id,
        session_image_id=session_image_id,
        status=status,
        transcript_text=transcript_text,
        error=error,
        duration_seconds=duration_seconds,
        used=used,
    )


def list_image_transcripts(
    *,
    session_id: int,
    limit: int = 20,
) -> list[ImageTranscriptRecord]:
    """List image transcript rows for one session."""
    return _repo.list_image_transcripts(session_id=session_id, limit=limit)


def get_image_transcript(
    *,
    session_id: int,
    session_image_id: int,
) -> ImageTranscriptRecord | None:
    """Get one image transcript row by session-scoped image ID."""
    return _repo.get_image_transcript(
        session_id=session_id,
        session_image_id=session_image_id,
    )


def prune_image_transcripts(
    *,
    session_id: int,
    keep: int,
) -> list[ImageTranscriptRecord]:
    """Prune oldest image transcript rows for one session."""
    return _repo.prune_image_transcripts(session_id=session_id, keep=keep)


def set_room_session_binding(*, room_jid: str, session_id: int) -> None:
    """Create or update persistent room -> session mapping."""
    _repo.set_room_session_binding(room_jid=room_jid, session_id=session_id)


def get_room_session_binding(*, room_jid: str) -> RoomSessionBinding | None:
    """Get one room -> session mapping."""
    return _repo.get_room_session_binding(room_jid=room_jid)


def list_room_session_bindings() -> list[RoomSessionBinding]:
    """List all persistent room -> session mappings."""
    return _repo.list_room_session_bindings()


def save_session_override_file(
    *,
    session_id: int,
    filename: str,
    content: str,
) -> None:
    """Create or replace one session-scoped override file snapshot."""
    _repo.save_session_override_file(
        session_id=session_id,
        filename=filename,
        content=content,
    )


def get_session_override_file(
    *,
    session_id: int,
    filename: str,
) -> SessionOverrideFile | None:
    """Fetch one session-scoped override file snapshot."""
    return _repo.get_session_override_file(session_id=session_id, filename=filename)


def list_session_override_files(*, session_id: int) -> list[SessionOverrideFile]:
    """List session-scoped override file snapshots."""
    return _repo.list_session_override_files(session_id=session_id)


def copy_session_override_files(
    *,
    source_session_id: int,
    target_session_id: int,
) -> int:
    """Copy all override file snapshots from source to target session."""
    return _repo.copy_session_override_files(
        source_session_id=source_session_id,
        target_session_id=target_session_id,
    )
