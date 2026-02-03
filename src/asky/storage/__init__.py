"""Storage package for asky."""

from typing import Optional, Union
from asky.config import DB_PATH
from asky.storage.interface import Interaction, HistoryRepository
from asky.storage.sqlite import SQLiteHistoryRepository

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
) -> None:
    """Save an interaction using the default repository."""
    _repo.save_interaction(query, answer, model, query_summary, answer_summary)


def get_history(limit: int):
    """Get history using the default repository."""
    # Convert to legacy dict format if needed?
    # Actually, let's keep it returning Interaction objects and see if cli needs update.
    # Looking at cli.py, it expects the rows to behave like dicts or have attributes.
    return _repo.get_history(limit)


def get_interaction_context(ids: list[int], full: bool = False) -> str:
    """Get context using the default repository."""
    return _repo.get_interaction_context(ids, full=full)


def cleanup_db(
    days: Optional[Union[int, str]] = None,
    delete_all: bool = False,
    ids: Optional[str] = None,
) -> int:
    """Cleanup using the default repository."""
    return _repo.cleanup_db(days=days, delete_all=delete_all, ids=ids)


def get_db_record_count() -> int:
    """Get count using the default repository."""
    return _repo.get_db_record_count()
