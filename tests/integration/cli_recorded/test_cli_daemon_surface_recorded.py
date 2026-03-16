import pytest
from unittest.mock import patch

from tests.integration.cli_recorded.helpers import (
    run_cli_inprocess,
)

pytestmark = [pytest.mark.recorded_cli, pytest.mark.vcr]


@patch("asky.daemon.launcher.spawn_background_child")
def test_daemon_dispatch(mock_daemon_run):
    """Test --daemon flag dispatches to background spawn by default."""
    result = run_cli_inprocess(["--daemon"])
    assert result.exit_code == 0
    assert mock_daemon_run.called

@patch("asky.daemon.service.run_daemon_foreground")
def test_daemon_foreground_dispatch(mock_daemon_run):
    """Test --daemon --foreground flag dispatches to foreground service."""
    result = run_cli_inprocess(["--daemon", "--foreground"])
    assert result.exit_code == 0
    assert mock_daemon_run.called

@patch("asky.daemon.launcher.spawn_background_child")
def test_daemon_no_tray_dispatch(mock_daemon_run):
    """Test --daemon --no-tray flag dispatches to background spawn."""
    result = run_cli_inprocess(["--daemon", "--no-tray"])
    assert result.exit_code == 0
    assert mock_daemon_run.called
