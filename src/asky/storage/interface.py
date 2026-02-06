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
    def create_session(self, model: str, name: Optional[str] = None) -> int:
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
