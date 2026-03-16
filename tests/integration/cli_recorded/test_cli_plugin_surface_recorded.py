import pytest
from unittest.mock import patch

from tests.integration.cli_recorded.helpers import (
    CliRunResult,
    normalize_cli_output,
    run_cli_inprocess,
)

pytestmark = [pytest.mark.recorded_cli, pytest.mark.vcr]


def run_cli_inprocess_with_status(argv: list[str]) -> CliRunResult:
    """Helper for one-shot plugin invocations that require a full answer."""
    return run_cli_inprocess(argv)

@pytest.mark.with_plugins(["email_sender"])
@patch("asky.plugins.email_sender.sender.send_email")
def test_plugin_email_sender(mock_send):
    """Test --sendmail and --subject flags."""
    result = run_cli_inprocess_with_status([
        "--sendmail", "test@example.com",
        "--subject", "Integration Test",
        "-off", "all", "--shortlist", "off", "Just say apple."
    ])
    assert result.exit_code == 0
    assert mock_send.called
    args, kwargs = mock_send.call_args
    assert "test@example.com" in args[0]
    assert args[1] == "Integration Test"

@pytest.mark.with_plugins(["push_data"])
@patch("asky.plugins.push_data.executor.execute_push_data")
def test_plugin_push_data(mock_push):
    """Test --push-data flag."""
    result = run_cli_inprocess_with_status([
        "--push-data", "notion?title=Test",
        "-off", "all", "--shortlist", "off", "Just say apple."
    ])
    assert mock_push.called
    # Check if endpoint was passed correctly (using keyword or positional)
    mock_push.assert_called()
    call_args = mock_push.call_args
    # First arg is endpoint_name
    assert "notion" in str(call_args)
    # Check if params were parsed correctly
    assert "{'title': 'Test'}" in str(call_args)


@pytest.mark.with_plugins(["playwright_browser"])
@patch("asky.plugins.playwright_browser.plugin.PlaywrightBrowserPlugin.run_login_session")
def test_plugin_browser_dispatch(mock_login):
    """Test --browser flag dispatch."""
    result = run_cli_inprocess_with_status(["--browser", "https://example.com"])
    assert result.exit_code == 0
    assert mock_login.called


@pytest.mark.with_plugins(["xmpp_daemon"])
@patch("asky.daemon.launcher.spawn_background_child")
def test_plugin_daemon_dispatch(mock_daemon_run):
    """Test --daemon flag dispatches to background spawn by default."""
    result = run_cli_inprocess(["--daemon"])
    assert result.exit_code == 0
    assert mock_daemon_run.called

@pytest.mark.with_plugins(["xmpp_daemon"])
@patch("asky.daemon.service.run_daemon_foreground")
def test_plugin_daemon_foreground_dispatch(mock_daemon_run):
    """Test --daemon --foreground flag dispatches to foreground service."""
    result = run_cli_inprocess(["--daemon", "--foreground"])
    assert result.exit_code == 0
    assert mock_daemon_run.called
