import pytest
import sqlite3
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from asky.storage.session import SessionRepository, Session, SessionMessage
from asky.core.session_manager import SessionManager
from asky.config import DB_PATH


@pytest.fixture
def temp_repo(tmp_path):
    # Use a temporary database for testing
    db_file = tmp_path / "test_sessions.db"

    # Initialize DB (copying schema from sqlite.py or just running it)
    from asky.storage.sqlite import SQLiteHistoryRepository

    with patch("asky.storage.sqlite.DB_PATH", db_file):
        repo = SQLiteHistoryRepository()
        repo.init_db()

    with patch("asky.storage.session.DB_PATH", db_file):
        session_repo = SessionRepository()
        yield session_repo


def test_session_lifecycle(temp_repo):
    # Create
    sid = temp_repo.create_session("model-a", name="test-ses")
    assert sid == 1

    # Get by ID
    s = temp_repo.get_session_by_id(sid)
    assert s.name == "test-ses"
    assert s.is_active == 1

    # Get by Name
    s2 = temp_repo.get_session_by_name("test-ses")
    assert s2.id == sid

    # List
    sessions = temp_repo.list_sessions(10)
    assert len(sessions) == 1

    # End
    temp_repo.end_session(sid)
    s_ended = temp_repo.get_session_by_id(sid)
    assert s_ended.is_active == 0
    assert s_ended.ended_at is not None


def test_session_messages(temp_repo):
    sid = temp_repo.create_session("model-a")
    temp_repo.add_message(sid, "user", "hello", "q_sum", 10)
    temp_repo.add_message(sid, "assistant", "hi", "a_sum", 5)

    msgs = temp_repo.get_session_messages(sid)
    assert len(msgs) == 2
    assert msgs[0].role == "user"
    assert msgs[0].content == "hello"
    assert msgs[1].role == "assistant"
    assert msgs[1].content == "hi"


def test_compaction_storage(temp_repo):
    sid = temp_repo.create_session("model-a")
    temp_repo.compact_session(sid, "Compacted Summary Here")

    s = temp_repo.get_session_by_id(sid)
    assert s.compacted_summary == "Compacted Summary Here"


def test_session_manager_resume(temp_repo):
    # Create a session in repo first
    sid = temp_repo.create_session("model-a", name="my-session")

    with patch("asky.core.session_manager.SessionRepository", return_value=temp_repo):
        mgr = SessionManager({"alias": "model-a", "context_size": 1000})

        # Resume by name
        s = mgr.start_or_resume("my-session")
        assert s.id == sid

        # Resume by ID (S1)
        s_id = mgr.start_or_resume("S1")
        assert s_id.id == sid


def test_session_manager_auto_resume(temp_repo):
    # Create an active session
    sid = temp_repo.create_session("model-a")

    with patch("asky.core.session_manager.SessionRepository", return_value=temp_repo):
        mgr = SessionManager({"alias": "model-a", "context_size": 1000})
        s = mgr.start_or_resume()  # Should pick active one
        assert s.id == sid


def test_session_manager_build_context(temp_repo):
    sid = temp_repo.create_session("model-a")
    temp_repo.add_message(sid, "user", "ping", "p_sum", 5)
    temp_repo.add_message(sid, "assistant", "pong", "po_sum", 5)
    temp_repo.compact_session(sid, "Old Summary")

    with patch("asky.core.session_manager.SessionRepository", return_value=temp_repo):
        mgr = SessionManager({"alias": "model-a"})
        mgr.current_session = temp_repo.get_session_by_id(sid)

        messages = mgr.build_context_messages()
        # Should have: [summary-user, summary-assistant, ping, pong]
        assert len(messages) == 4
        assert "Old Summary" in messages[0]["content"]
        assert messages[2]["content"] == "ping"


def test_compaction_logic_threshold(temp_repo):
    sid = temp_repo.create_session("model-a")
    # 10 tokens total
    temp_repo.add_message(sid, "user", "long" * 10, "sum", 10)

    with patch("asky.core.session_manager.SessionRepository", return_value=temp_repo):
        # Set threshold low to trigger
        with patch("asky.core.session_manager.SESSION_COMPACTION_THRESHOLD", 50):
            mgr = SessionManager(
                {"alias": "model-a", "context_size": 10}
            )  # threshold is 5 tokens
            mgr.current_session = temp_repo.get_session_by_id(sid)

            # This should trigger compaction
            triggered = mgr.check_and_compact()
            assert triggered is True

            s = temp_repo.get_session_by_id(sid)
            assert s.compacted_summary is not None


def test_compaction_llm_strategy(temp_repo):
    sid = temp_repo.create_session("model-a")
    temp_repo.add_message(sid, "user", "long text", "sum", 10)

    with patch("asky.core.session_manager.SessionRepository", return_value=temp_repo):
        mgr = SessionManager({"alias": "model-a"})
        mgr.current_session = temp_repo.get_session_by_id(sid)

        with patch(
            "asky.core.session_manager.SESSION_COMPACTION_STRATEGY", "llm_summary"
        ):
            with patch(
                "asky.core.session_manager._summarize_content",
                return_value="LLM COMPACTED",
            ) as mock_sum:
                mgr._perform_compaction()
                mock_sum.assert_called_once()
                s = temp_repo.get_session_by_id(sid)
                assert s.compacted_summary == "LLM COMPACTED"
