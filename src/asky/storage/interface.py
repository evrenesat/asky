"""Storage interfaces and data models for asky."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Union
from datetime import datetime


@dataclass
class Interaction:
    """Represents a single conversation turn in history or a session message."""

    id: Optional[int]
    timestamp: str

    # Session fields (nullable for non-session messages)
    session_id: Optional[int]
    role: Optional[str]  # 'user' or 'assistant' for session messages, None for history

    # Content fields
    content: str = ""  # For session messages (or general message content)
    query: str = ""  # For history interactions (User message)
    answer: str = ""  # For history interactions (Assistant message)

    summary: Optional[str] = None

    # Metadata
    model: str = ""
    token_count: Optional[int] = None

    def __getitem__(self, idx):
        return (
            self.id,
            self.timestamp,
            self.session_id,
            self.role,
            self.content,
            self.query,
            self.answer,
            self.summary,
            self.model,
            self.token_count,
        )[idx]

    def __iter__(self):
        return iter(
            (
                self.id,
                self.timestamp,
                self.session_id,
                self.role,
                self.content,
                self.query,
                self.answer,
                self.summary,
                self.model,
                self.token_count,
            )
        )


@dataclass
class Session:
    """Represents a conversation session.

    Sessions are persistent conversation threads that never end.
    A shell attaches to a session via lock file, not DB state.
    """

    id: int
    name: Optional[str]
    model: str
    created_at: str
    compacted_summary: Optional[str]
    memory_auto_extract: bool = False
    max_turns: Optional[int] = None
    last_used_at: Optional[str] = None
    research_mode: bool = False
    research_source_mode: Optional[str] = None
    research_local_corpus_paths: List[str] | None = None


@dataclass
class TranscriptRecord:
    """Represents one persisted voice transcript for daemon sessions."""

    id: int
    session_id: int
    session_transcript_id: int
    jid: str
    created_at: str
    status: str
    audio_url: str
    audio_path: str
    transcript_text: str
    error: str
    duration_seconds: Optional[float]
    used: bool = False


@dataclass
class ImageTranscriptRecord:
    """Represents one persisted image transcript for daemon sessions."""

    id: int
    session_id: int
    session_image_id: int
    jid: str
    created_at: str
    status: str
    image_url: str
    image_path: str
    transcript_text: str
    error: str
    duration_seconds: Optional[float]
    used: bool = False


@dataclass
class RoomSessionBinding:
    """Represents one persistent group-room to session mapping."""

    room_jid: str
    session_id: int
    updated_at: str


@dataclass
class SessionOverrideFile:
    """Represents one persisted session-scoped override TOML file."""

    session_id: int
    filename: str
    content: str
    updated_at: str


class HistoryRepository(ABC):
    """Abstract interface for message and session storage."""

    @abstractmethod
    def init_db(self) -> None:
        """Initialize the storage backend."""
        pass

    @abstractmethod
    def save_interaction(
        self,
        query: str,
        answer: str,
        model: str,
        query_summary: str = "",
        answer_summary: str = "",
    ) -> None:
        """Save a new interaction."""
        pass

    @abstractmethod
    def get_history(self, limit: int) -> List[Interaction]:
        """Retrieve recent history."""
        pass

    @abstractmethod
    def get_interaction_context(self, ids: List[int], full: bool = False) -> str:
        """Retrieve context (full or summary) for specific interaction IDs."""
        pass

    @abstractmethod
    def delete_messages(
        self,
        ids: Optional[str] = None,
        delete_all: bool = False,
    ) -> int:
        """Delete message history records by ID, range, list, or all."""
        pass

    @abstractmethod
    def get_db_record_count(self) -> int:
        """Return total number of records."""
        pass

    @abstractmethod
    def count_sessions(self) -> int:
        """Return total number of sessions."""
        pass

    @abstractmethod
    def delete_sessions(
        self,
        ids: Optional[str] = None,
        delete_all: bool = False,
    ) -> int:
        """Delete session records and their messages."""
        pass

    # Session management methods
    @abstractmethod
    def create_session(
        self,
        model: str,
        name: Optional[str] = None,
        memory_auto_extract: bool = False,
        max_turns: Optional[int] = None,
        research_mode: bool = False,
        research_source_mode: Optional[str] = None,
        research_local_corpus_paths: Optional[List[str]] = None,
    ) -> int:
        """Create a new session and return its ID."""
        pass

    @abstractmethod
    def get_session_by_id(self, session_id: int):
        """Look up a session by ID."""
        pass

    @abstractmethod
    def get_session_by_name(self, name: str):
        """Look up a session by name."""
        pass

    @abstractmethod
    def get_sessions_by_name(self, name: str) -> list:
        """Return all sessions matching the given name."""
        pass

    @abstractmethod
    def save_message(
        self, session_id: int, role: str, content: str, summary: str, token_count: int
    ) -> None:
        """Save a message to a session."""
        pass

    @abstractmethod
    def get_session_messages(self, session_id: int) -> List[Interaction]:
        """Retrieve all messages for a session."""
        pass

    @abstractmethod
    def compact_session(self, session_id: int, compacted_summary: str) -> None:
        """Replace session message history with a compacted summary."""
        pass

    @abstractmethod
    def list_sessions(self, limit: int) -> list:
        """List recently created sessions."""
        pass

    @abstractmethod
    def set_session_memory_auto_extract(self, session_id: int, enabled: bool) -> None:
        """Enable or disable auto memory extraction for a session."""
        pass

    @abstractmethod
    def update_session_max_turns(self, session_id: int, max_turns: int) -> None:
        """Update the maximum turns explicitly set for a session."""
        pass

    @abstractmethod
    def update_session_last_used(self, session_id: int) -> None:
        """Update the last used timestamp for a session."""
        pass

    @abstractmethod
    def update_session_research_profile(
        self,
        session_id: int,
        *,
        research_mode: bool,
        research_source_mode: Optional[str],
        research_local_corpus_paths: Optional[List[str]],
    ) -> None:
        """Update persisted research profile metadata for a session."""
        pass

    @abstractmethod
    def create_transcript(
        self,
        *,
        session_id: int,
        jid: str,
        audio_url: str,
        audio_path: str,
        status: str,
        transcript_text: str = "",
        error: str = "",
        duration_seconds: Optional[float] = None,
    ) -> TranscriptRecord:
        """Create and return a transcript record."""
        pass

    @abstractmethod
    def update_transcript(
        self,
        *,
        session_id: int,
        session_transcript_id: int,
        status: str,
        transcript_text: Optional[str] = None,
        error: Optional[str] = None,
        duration_seconds: Optional[float] = None,
        used: Optional[bool] = None,
    ) -> Optional[TranscriptRecord]:
        """Update transcript fields and return updated record."""
        pass

    @abstractmethod
    def list_transcripts(
        self,
        *,
        session_id: int,
        limit: int = 20,
    ) -> List[TranscriptRecord]:
        """List transcript records for one session (newest first)."""
        pass

    @abstractmethod
    def get_transcript(
        self,
        *,
        session_id: int,
        session_transcript_id: int,
    ) -> Optional[TranscriptRecord]:
        """Retrieve one transcript by session-scoped transcript ID."""
        pass

    @abstractmethod
    def prune_transcripts(
        self,
        *,
        session_id: int,
        keep: int,
    ) -> List[TranscriptRecord]:
        """Prune old transcripts for a session and return deleted records."""
        pass

    @abstractmethod
    def create_image_transcript(
        self,
        *,
        session_id: int,
        jid: str,
        image_url: str,
        image_path: str,
        status: str,
        transcript_text: str = "",
        error: str = "",
        duration_seconds: Optional[float] = None,
    ) -> ImageTranscriptRecord:
        """Create and return an image transcript record."""
        pass

    @abstractmethod
    def update_image_transcript(
        self,
        *,
        session_id: int,
        session_image_id: int,
        status: str,
        transcript_text: Optional[str] = None,
        error: Optional[str] = None,
        duration_seconds: Optional[float] = None,
        used: Optional[bool] = None,
    ) -> Optional[ImageTranscriptRecord]:
        """Update image transcript fields and return updated record."""
        pass

    @abstractmethod
    def list_image_transcripts(
        self,
        *,
        session_id: int,
        limit: int = 20,
    ) -> List[ImageTranscriptRecord]:
        """List image transcript records for one session (newest first)."""
        pass

    @abstractmethod
    def get_image_transcript(
        self,
        *,
        session_id: int,
        session_image_id: int,
    ) -> Optional[ImageTranscriptRecord]:
        """Retrieve one image transcript by session-scoped image ID."""
        pass

    @abstractmethod
    def prune_image_transcripts(
        self,
        *,
        session_id: int,
        keep: int,
    ) -> List[ImageTranscriptRecord]:
        """Prune old image transcripts for a session and return deleted records."""
        pass

    @abstractmethod
    def set_room_session_binding(self, *, room_jid: str, session_id: int) -> None:
        """Create or update persistent room -> session binding."""
        pass

    @abstractmethod
    def get_room_session_binding(self, *, room_jid: str) -> Optional[RoomSessionBinding]:
        """Fetch one room binding by room JID."""
        pass

    @abstractmethod
    def list_room_session_bindings(self) -> List[RoomSessionBinding]:
        """List all persisted room bindings."""
        pass

    @abstractmethod
    def save_session_override_file(
        self,
        *,
        session_id: int,
        filename: str,
        content: str,
    ) -> None:
        """Create or replace one session-scoped override file snapshot."""
        pass

    @abstractmethod
    def get_session_override_file(
        self,
        *,
        session_id: int,
        filename: str,
    ) -> Optional[SessionOverrideFile]:
        """Fetch one session-scoped override file snapshot."""
        pass

    @abstractmethod
    def list_session_override_files(self, *, session_id: int) -> List[SessionOverrideFile]:
        """List override file snapshots for a session."""
        pass

    @abstractmethod
    def copy_session_override_files(
        self,
        *,
        source_session_id: int,
        target_session_id: int,
    ) -> int:
        """Copy all override file snapshots from source session to target session."""
        pass
