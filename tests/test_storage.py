import pytest
import sqlite3
import os
from pathlib import Path
from unittest.mock import patch, MagicMock
from asky.storage import (
    init_db,
    save_interaction,
    get_history,
    get_interaction_context,
    delete_messages,
    delete_sessions,
    create_session,
    save_message,
    get_session_messages,
)


@pytest.fixture
def temp_db_path(tmp_path):
    # Create a temporary database path
    db_file = tmp_path / "test_history.db"
    return db_file


@pytest.fixture
def mock_db_path(temp_db_path):
    # Mock the DB_PATH constant in all storage modules
    with (
        patch("asky.storage.sqlite.DB_PATH", temp_db_path),
        patch("asky.config.DB_PATH", temp_db_path),
    ):
        # Re-instantiate the repository with the mocked path
        from asky.storage import _repo

        _repo.db_path = temp_db_path
        yield temp_db_path


def test_init_db(mock_db_path):
    init_db()
    assert mock_db_path.exists()

    conn = sqlite3.connect(mock_db_path)
    c = conn.cursor()
    # Check for new unified messages table
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'")
    assert c.fetchone() is not None
    # Check for sessions table
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'")
    assert c.fetchone() is not None
    conn.close()


def test_save_and_get_history(mock_db_path):
    init_db()
    save_interaction(
        query="test query",
        answer="test answer",
        model="test_model",
        query_summary="q sum",
        answer_summary="a sum",
    )

    rows = get_history(limit=1)
    assert len(rows) == 1

    # Access via attributes (Interaction dataclass)
    interaction = rows[0]
    assert interaction.session_id is None  # Non-session message
    assert interaction.role is None
    assert "test query" in interaction.content
    assert "test answer" in interaction.content
    # query_summary is removed from Interaction.
    # summary reflects the interaction summary (usually answer summary or last msg)
    assert interaction.summary == "a sum"
    assert interaction.model == "test_model"


def test_get_interaction_context(mock_db_path):
    init_db()
    # Use a query longer than the default threshold (160)
    save_interaction("q1" * 100, "a1", "m1", "qs1", "as1")

    # Get the ID of the inserted row
    rows = get_history(1)
    rid = rows[0].id

    context = get_interaction_context([rid])
    # Now that we use explicit message IDs, referencing the interaction ID (Answer ID)
    # might only return the answer context unless we expand logic.
    # But context usually implies Q+A.
    assert "Answer: as1" in context
    # We should expect Query too if smart expansion works.
    # If not, checks might need adjustment. For now keeping assertion conservative
    # or relying on get_interaction_context fix.
    assert "Query" in context

    context_full = get_interaction_context([rid], full=True)
    assert "a1" in context_full


def test_save_message(mock_db_path):
    init_db()
    session_id = create_session("model")
    save_message(session_id, "user", "test content", "test summary", 10)

    rows = get_session_messages(session_id)
    assert len(rows) == 1
    assert rows[0].content == "test content"
    assert rows[0].summary == "test summary"


def test_cleanup_db(mock_db_path, capsys):
    init_db()
    # Insert 3 records
    for i in range(3):
        save_interaction(f"q{i}", f"a{i}", "m")

    # Verify insert
    assert len(get_history(10)) == 3

    # Test deletion by ID
    rows = get_history(10)
    ids = [r.id for r in rows]
    target_id = ids[0]

    delete_messages(str(target_id))
    assert len(get_history(10)) == 2

    # Test delete all
    delete_messages(delete_all=True)
    assert len(get_history(10)) == 0


def test_cleanup_db_edge_cases(mock_db_path, capsys):
    init_db()
    ids = []
    for i in range(5):
        save_interaction(f"q{i}", f"a{i}", "m")

    rows = get_history(10)  # 5,4,3,2,1
    # Test reverse range 4-2
    # IDs are now likely 2, 4, 6, 8, 10
    # 4-2 deletes IDs 2, 3, 4.
    # 2=Interaction 1. 4=Interaction 2.
    # So 2 interactions deleted. 3 remaining.
    delete_messages("4-2")

    remaining = get_history(10)
    assert len(remaining) == 3

    # Test invalid range
    delete_messages("a-b")
    captured = capsys.readouterr()
    assert "Error: Invalid range format" in captured.out

    # Test invalid list
    delete_messages("1,a")
    captured = capsys.readouterr()
    assert "Error: Invalid list format" in captured.out

    # Test invalid ID
    delete_messages("abc")
    captured = capsys.readouterr()
    assert "Error: Invalid ID format" in captured.out


def test_delete_sessions(mock_db_path):
    from asky.storage.sqlite import SQLiteHistoryRepository

    repo = SQLiteHistoryRepository()
    init_db()

    # Create 3 sessions
    sid1 = repo.create_session("model", name="s1")
    sid2 = repo.create_session("model", name="s2")
    sid3 = repo.create_session("model", name="s3")

    # Add messages to sid1
    repo.save_message(sid1, "user", "hi", "hi", 10)

    # Verify messages exist
    assert len(repo.get_session_messages(sid1)) == 1

    # Test delete session 1
    delete_sessions(str(sid1))
    assert repo.get_session_by_id(sid1) is None
    assert len(repo.get_session_messages(sid1)) == 0

    # Test delete all
    delete_sessions(delete_all=True)
    assert repo.get_session_by_id(sid2) is None
    assert repo.get_session_by_id(sid3) is None


def test_session_research_profile_roundtrip(mock_db_path):
    from asky.storage.sqlite import SQLiteHistoryRepository

    repo = SQLiteHistoryRepository()
    init_db()

    sid = repo.create_session(
        "model",
        name="research",
        research_mode=True,
        research_source_mode="mixed",
        research_local_corpus_paths=["/books/a.epub", "/books/b.epub"],
    )
    loaded = repo.get_session_by_id(sid)
    assert loaded is not None
    assert loaded.research_mode is True
    assert loaded.research_source_mode == "mixed"
    assert loaded.research_local_corpus_paths == ["/books/a.epub", "/books/b.epub"]

    repo.update_session_research_profile(
        sid,
        research_mode=True,
        research_source_mode="web_only",
        research_local_corpus_paths=[],
    )
    updated = repo.get_session_by_id(sid)
    assert updated is not None
    assert updated.research_mode is True
    assert updated.research_source_mode == "web_only"
    assert updated.research_local_corpus_paths == []
