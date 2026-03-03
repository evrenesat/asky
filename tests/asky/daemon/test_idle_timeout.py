import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
from asky.cli.chat import _check_idle_session_timeout
from asky.storage.interface import Session


@pytest.fixture
def mock_repo():
    with patch("asky.storage.sqlite.SQLiteHistoryRepository") as mock:
        yield mock.return_value


@pytest.fixture
def mock_console():
    return MagicMock()


def test_idle_timeout_disabled_when_zero(mock_console):
    with patch("asky.cli.chat.SESSION_IDLE_TIMEOUT_MINUTES", 0):
        result = _check_idle_session_timeout(1, mock_console)
        assert result == "continue"
        mock_console.print.assert_not_called()


def test_idle_timeout_no_session(mock_repo, mock_console):
    with patch("asky.cli.chat.SESSION_IDLE_TIMEOUT_MINUTES", 5):
        mock_repo.get_session_by_id.return_value = None
        result = _check_idle_session_timeout(1, mock_console)
        assert result == "continue"


def test_idle_timeout_fresh_session(mock_repo, mock_console):
    with patch("asky.cli.chat.SESSION_IDLE_TIMEOUT_MINUTES", 5):
        now = datetime.now()
        session = Session(
            id=1,
            name="test",
            model="test-model",
            created_at=now.isoformat(),
            compacted_summary=None,
            last_used_at=now.isoformat(),
        )
        mock_repo.get_session_by_id.return_value = session
        result = _check_idle_session_timeout(1, mock_console)
        assert result == "continue"


@patch("rich.prompt.Prompt.ask")
def test_idle_timeout_stale_session_continue(mock_ask, mock_repo, mock_console):
    with patch("asky.cli.chat.SESSION_IDLE_TIMEOUT_MINUTES", 5):
        # 10 minutes ago
        last_used = datetime.now() - timedelta(minutes=10)
        session = Session(
            id=1,
            name="test",
            model="test-model",
            created_at=last_used.isoformat(),
            compacted_summary=None,
            last_used_at=last_used.isoformat(),
        )
        mock_repo.get_session_by_id.return_value = session

        mock_ask.return_value = "c"
        result = _check_idle_session_timeout(1, mock_console)
        assert result == "continue"
        assert mock_console.print.called


@patch("rich.prompt.Prompt.ask")
def test_idle_timeout_stale_session_new(mock_ask, mock_repo, mock_console):
    with patch("asky.cli.chat.SESSION_IDLE_TIMEOUT_MINUTES", 5):
        last_used = datetime.now() - timedelta(minutes=10)
        session = Session(
            id=1,
            name="test",
            model="test-model",
            created_at=last_used.isoformat(),
            compacted_summary=None,
            last_used_at=last_used.isoformat(),
        )
        mock_repo.get_session_by_id.return_value = session

        mock_ask.return_value = "n"
        result = _check_idle_session_timeout(1, mock_console)
        assert result == "new"


@patch("rich.prompt.Prompt.ask")
def test_idle_timeout_stale_session_oneoff(mock_ask, mock_repo, mock_console):
    with patch("asky.cli.chat.SESSION_IDLE_TIMEOUT_MINUTES", 5):
        last_used = datetime.now() - timedelta(minutes=10)
        session = Session(
            id=1,
            name="test",
            model="test-model",
            created_at=last_used.isoformat(),
            compacted_summary=None,
            last_used_at=last_used.isoformat(),
        )
        mock_repo.get_session_by_id.return_value = session

        mock_ask.return_value = "o"
        result = _check_idle_session_timeout(1, mock_console)
        assert result == "oneoff"
