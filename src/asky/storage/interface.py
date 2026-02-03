"""Storage interfaces and data models for asky."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Union


@dataclass
class Interaction:
    """Represents a single conversation turn in history."""

    id: Optional[int]
    timestamp: str
    query: str
    query_summary: str
    answer_summary: str
    answer: str
    model: str

    def __getitem__(self, idx):
        return (
            self.id,
            self.timestamp,
            self.query,
            self.query_summary,
            self.answer_summary,
            self.answer,
            self.model,
        )[idx]

    def __iter__(self):
        return iter(
            (
                self.id,
                self.timestamp,
                self.query,
                self.query_summary,
                self.answer_summary,
                self.answer,
                self.model,
            )
        )


class HistoryRepository(ABC):
    """Abstract interface for history storage."""

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
    def cleanup_db(
        self,
        days: Optional[int] = None,
        delete_all: bool = False,
        ids: Optional[str] = None,
    ) -> int:
        """Delete records based on days, all, or specific IDs."""
        pass

    @abstractmethod
    def get_db_record_count(self) -> int:
        """Return total number of records."""
        pass
