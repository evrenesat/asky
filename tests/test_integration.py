"""Integration tests for CLI commands.

These tests exercise actual CLI commands to ensure end-to-end functionality.
"""

import os
import sys
import tempfile
import pytest
from asky.storage import save_interaction, delete_messages, delete_sessions
from asky.storage.sqlite import SQLiteHistoryRepository
from asky.cli.main import parse_args, main
from unittest.mock import patch
from pathlib import Path


@pytest.fixture
def temp_integration_db():
    """Create a temporary database for integration testing."""
    db_dir = tempfile.mkdtemp()
    db_file = Path(db_dir) / "test_integration.db"
    yield db_file
    # Cleanup
    if db_file.exists():
        db_file.unlink()
    os.rmdir(db_dir)


@pytest.fixture
def setup_test_data(temp_integration_db):
    """Setup test data in database."""
    with patch("asky.storage.sqlite.DB_PATH", temp_integration_db):
        # Ensure global _repo uses the mocked path BEFORE any operations
        from asky.storage import _repo

        _repo.db_path = temp_integration_db

        # Ensure the repository uses the mocked path
        repo = SQLiteHistoryRepository()
        repo.db_path = temp_integration_db
        repo.init_db()  # Call init_db on the repo instance

        # Add history records
        save_interaction("query1", "answer1", "model")
        save_interaction("query2", "answer2", "model")
        save_interaction("query3", "answer3", "model")

        # Add sessions
        sid1 = repo.create_session("model", name="test_session_1")
        sid2 = repo.create_session("model", name="test_session_2")
        repo.save_message(sid1, "user", "hello", "hello", 10)
        repo.save_message(sid1, "assistant", "hi", "hi there", 20)

        yield {
            "db_path": temp_integration_db,
            "session_ids": [sid1, sid2],
        }


def test_delete_messages_integration(setup_test_data, capsys):
    """Test message deletion via CLI."""
    db_path = setup_test_data["db_path"]

    with patch("asky.storage.sqlite.DB_PATH", db_path):
        # Ensure global _repo uses the mocked path
        from asky.storage import _repo

        _repo.db_path = db_path

        # Delete single message by ID
        count = delete_messages(ids="2")
        assert count == 1

        # Delete range
        count = delete_messages(ids="1-3")
        assert count == 2  # Only 1 and 3 remain after deleting 2

        # Add more and delete all
        save_interaction("q4", "a4", "m")
        count = delete_messages(delete_all=True)
        assert count == 1


def test_delete_sessions_integration(setup_test_data):
    """Test session deletion via CLI with cascade."""
    db_path = setup_test_data["db_path"]
    session_ids = setup_test_data["session_ids"]

    with patch("asky.storage.sqlite.DB_PATH", db_path):
        # Ensure global _repo uses the mocked path
        from asky.storage import _repo

        _repo.db_path = db_path

        repo = SQLiteHistoryRepository()
        repo.db_path = db_path

        # Verify session 1 has messages
        assert len(repo.get_session_messages(session_ids[0])) == 2

        # Delete session 1
        count = delete_sessions(ids=str(session_ids[0]))
        assert count == 1

        # Verify session and messages are gone
        assert repo.get_session_by_id(session_ids[0]) is None
        assert len(repo.get_session_messages(session_ids[0])) == 0

        # Delete all remaining sessions
        count = delete_sessions(delete_all=True)
        assert count == 1
        assert repo.get_session_by_id(session_ids[1]) is None


def test_cli_args_parsing():
    """Test that new CLI arguments parse correctly."""

    # Test delete-messages
    with patch.object(sys, "argv", ["asky", "--delete-messages", "5", "query"]):
        args = parse_args()
        assert args.delete_messages == "5"

    # Test delete-sessions
    with patch.object(sys, "argv", ["asky", "--delete-sessions", "1-10", "query"]):
        args = parse_args()
        assert args.delete_sessions == "1-10"

    # Test print-session
    with patch.object(sys, "argv", ["asky", "--print-session", "3", "query"]):
        args = parse_args()
        assert args.print_session == "3"

    # Test --all flag
    with patch.object(sys, "argv", ["asky", "--delete-messages", "--all", "query"]):
        args = parse_args()
        assert args.all is True
