import pytest
from unittest.mock import MagicMock, patch
from asky.storage.sqlite import SQLiteHistoryRepository


@pytest.fixture
def repo(tmp_path):
    # Patch DB_PATH to use a temp file
    db_file = tmp_path / "test_history.db"

    with patch("asky.storage.sqlite.DB_PATH", db_file):
        repo = SQLiteHistoryRepository()
        repo.init_db()
        yield repo


def test_convert_history_to_session(repo):
    # Setup: Create history interaction
    repo.save_interaction("User Query", "Assistant Answer", "gpt-4")

    # Get the interaction ID (it's the answer ID usually, or last ID)
    last = repo.get_last_interaction()
    assert last is not None
    assert last.session_id is None

    # Test Conversion
    new_sid = repo.convert_history_to_session(last.id)

    # Verify Session Created
    session = repo.get_session_by_id(new_sid)
    assert session is not None
    assert "User Query" in (session.name or "")

    # Verify Messages Copied
    msgs = repo.get_session_messages(new_sid)
    assert len(msgs) == 2
    assert msgs[0].role == "user"
    assert msgs[0].content == "User Query"
    assert msgs[1].role == "assistant"
    assert msgs[1].content == "Assistant Answer"


def test_reply_to_last_history(repo):
    # Setup: Create history interaction
    repo.save_interaction("History Q", "History A", "gpt-4")

    # Verify get_last_interaction returns it
    last = repo.get_last_interaction()
    assert last.content == "History A"
    assert last.session_id is None

    # Simulate --reply logic: get last, convert
    new_sid = repo.convert_history_to_session(last.id)

    # Verify session
    session = repo.get_session_by_id(new_sid)
    assert session is not None
    msgs = repo.get_session_messages(new_sid)
    assert len(msgs) == 2
    assert msgs[1].content == "History A"


def test_reply_to_existing_session(repo):
    # Setup: Create a session and add messages
    sid = repo.create_session("gpt-4", "My Session")
    repo.save_message(sid, "user", "Session Q", "", 0)
    repo.save_message(sid, "assistant", "Session A", "", 0)

    # Verify get_last_interaction returns session msg
    last = repo.get_last_interaction()
    assert last.content == "Session A"
    assert last.session_id == sid

    # Simulate --reply logic: verify convert returns existing ID
    returned_sid = repo.convert_history_to_session(last.id)
    assert returned_sid == sid


def test_convert_invalid_id(repo):
    with pytest.raises(ValueError):
        repo.convert_history_to_session(99999)
