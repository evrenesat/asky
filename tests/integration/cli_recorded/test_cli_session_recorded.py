import pytest

from tests.integration.cli_recorded.helpers import (
    assert_output_contains_sentences,
    normalize_cli_output,
    run_cli_inprocess,
)

pytestmark = [pytest.mark.recorded_cli, pytest.mark.vcr]


def test_session_create_with_query():
    """Create session and run first query."""
    run_cli_inprocess(["-ss", "test_sess_1"])
    result = run_cli_inprocess(["-L", "What is 2+2? Answer simply."])
    assert result.exit_code == 0
    assert_output_contains_sentences(result.stdout, ["4"])


def test_session_follow_up_continuity():
    """Follow-up turn in same session."""
    run_cli_inprocess(["-ss", "test_sess_2"])
    run_cli_inprocess(["-L", "My favorite color is blue."])

    result = run_cli_inprocess(["-L", "What is my favorite color? Answer simply."])
    assert result.exit_code == 0
    assert_output_contains_sentences(result.stdout, ["blue"])


def test_session_show_empty_session_message():
    """Session show prints deterministic output for a new empty session."""
    run_cli_inprocess(["-ss", "test_sess_3"])

    result = run_cli_inprocess(["--print-session", "test_sess_3"])
    assert result.exit_code == 0
    normalized = normalize_cli_output(result.stdout)
    assert "Session 1 is empty." in normalized


def test_session_end_behavior():
    """Session end behavior."""
    run_cli_inprocess(["-ss", "test_sess_4"])

    result = run_cli_inprocess(["session", "end"])
    assert result.exit_code == 0

    result_show = run_cli_inprocess(["session", "list"])
    assert result_show.exit_code == 0
    assert "test_sess_4" in normalize_cli_output(result_show.stdout)


def test_grouped_command_strictness():
    """Grouped command strictness error behavior in session context."""
    result = run_cli_inprocess(["session", "banana"])
    normalized = normalize_cli_output(result.stdout).lower()
    assert "unknown subcommand" in normalized
