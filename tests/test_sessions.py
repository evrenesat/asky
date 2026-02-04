import pytest
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock

from asky.storage.sqlite import SQLiteHistoryRepository
from asky.core.session_manager import SessionManager
from asky.core.api_client import UsageTracker


@pytest.fixture
def temp_db_path(tmp_path):
    return tmp_path / "test_sessions.db"


@pytest.fixture
def temp_repo(temp_db_path):
    with patch("asky.storage.sqlite.DB_PATH", temp_db_path):
        repo = SQLiteHistoryRepository()
        repo.init_db()
        yield repo


def test_session_lifecycle(temp_repo):
    """Test session creation, retrieval by ID/name, and listing."""
    # Create
    sid = temp_repo.create_session("model-a", name="test-ses")
    assert sid == 1

    # Get by ID
    s = temp_repo.get_session_by_id(sid)
    assert s.name == "test-ses"
    assert s.model == "model-a"

    # Get by Name
    s2 = temp_repo.get_session_by_name("test-ses")
    assert s2.id == sid

    # List
    sessions = temp_repo.list_sessions(10)
    assert len(sessions) == 1
    assert sessions[0].id == sid

    # Get all sessions by name
    all_matches = temp_repo.get_sessions_by_name("test-ses")
    assert len(all_matches) == 1


def test_session_messages(temp_repo):
    sid = temp_repo.create_session("model-a")
    temp_repo.save_message(sid, "user", "hello", "q_sum", 10)
    temp_repo.save_message(sid, "assistant", "hi", "a_sum", 5)

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


def test_session_manager_find(temp_repo):
    # Create a session in repo first
    sid = temp_repo.create_session("model-a", name="my-session")

    with patch(
        "asky.core.session_manager.SQLiteHistoryRepository", return_value=temp_repo
    ):
        mgr = SessionManager({"alias": "model-a", "context_size": 1000})

        # Find by name
        results = mgr.find_sessions("my-session")
        assert len(results) >= 1
        assert results[0].id == sid

        # Find by ID (S1) - legacy format
        results_s = mgr.find_sessions("S1")
        assert len(results_s) == 1
        assert results_s[0].id == sid

        # Find by numeric ID
        results_n = mgr.find_sessions("1")
        assert len(results_n) == 1
        assert results_n[0].id == sid

        # Partial Match
        results_p = mgr.find_sessions("my-ses")
        assert len(results_p) >= 1
        assert results_p[0].id == sid


def test_session_manager_build_context(temp_repo):
    sid = temp_repo.create_session("model-a")
    temp_repo.save_message(sid, "user", "ping", "p_sum", 5)
    temp_repo.save_message(sid, "assistant", "pong", "po_sum", 5)
    temp_repo.compact_session(sid, "Old Summary")

    with patch(
        "asky.core.session_manager.SQLiteHistoryRepository", return_value=temp_repo
    ):
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
    temp_repo.save_message(sid, "user", "long" * 10, "sum", 10)

    with patch(
        "asky.core.session_manager.SQLiteHistoryRepository", return_value=temp_repo
    ):
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
    temp_repo.save_message(sid, "user", "long text", "sum", 10)

    with patch(
        "asky.core.session_manager.SQLiteHistoryRepository", return_value=temp_repo
    ):
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
