import pytest

from tests.integration.cli_recorded.helpers import (
    assert_output_contains_sentences,
    normalize_cli_output,
    run_cli_inprocess,
)

pytestmark = [pytest.mark.recorded_cli, pytest.mark.vcr]


def test_session_create_with_query():
    """Start session and query in one shot."""
    run_cli_inprocess(["-ss", "test_sess_1"])
    result = run_cli_inprocess(["-off", "all", "--shortlist", "off", "What is 2+2? Answer simply."])
    assert result.exit_code == 0
    assert_output_contains_sentences(result.stdout, ["4"])


def test_session_query_flag():
    """Explicit --session flag for auto-named one-off sessions."""
    result = run_cli_inprocess(["-off", "all", "--shortlist", "off", "--session", "What is the capital of Japan?"])
    assert result.exit_code == 0
    assert_output_contains_sentences(result.stdout, ["tokyo"])


def test_session_follow_up_continuity():
    """Follow-up turn in same session."""
    run_cli_inprocess(["-ss", "test_sess_2"])
    run_cli_inprocess(["-off", "all", "--shortlist", "off", "My favorite color is blue."])

    result = run_cli_inprocess(["-off", "all", "--shortlist", "off", "What is my favorite color? Answer simply."])
    assert result.exit_code == 0
    assert_output_contains_sentences(result.stdout, ["blue"])


def test_session_resume_and_use():
    """Resume session by name/alias."""
    # Test -rs flag
    run_cli_inprocess(["-ss", "test_sess_resume"])
    run_cli_inprocess(["-off", "all", "--shortlist", "off", "Just say banana."])
    result = run_cli_inprocess(["-rs", "test_sess_resume", "-off", "all", "--shortlist", "off", "Just say banana again."])
    assert result.exit_code == 0
    assert_output_contains_sentences(result.stdout, ["banana"])

    # Test grouped `session use`
    result_use = run_cli_inprocess(["session", "use", "test_sess_resume"])
    assert result_use.exit_code == 0
    assert "resumed session" in normalize_cli_output(result_use.stdout).lower()


def test_session_grouped_create():
    """Test grouped `session create`."""
    result = run_cli_inprocess(["session", "create", "test_sess_grouped"])
    assert result.exit_code == 0
    assert "created and active" in normalize_cli_output(result.stdout).lower()


def test_session_show_and_history():
    """Session show/print session behavior."""
    run_cli_inprocess(["-ss", "test_sess_3"])
    res = run_cli_inprocess(["-off", "all", "--shortlist", "off", "Just say apple."])
    assert res.exit_code == 0, res.stderr

    # --print-session
    result = run_cli_inprocess(["--print-session", "test_sess_3"])
    assert result.exit_code == 0
    normalized = normalize_cli_output(result.stdout)
    assert "apple" in normalized.lower()

    # -ps alias
    result_ps = run_cli_inprocess(["-ps", "test_sess_3"])
    assert result_ps.exit_code == 0
    assert "apple" in normalize_cli_output(result_ps.stdout).lower()

    # `session show`
    result_show = run_cli_inprocess(["session", "show", "test_sess_3"])
    assert result_show.exit_code == 0
    assert "apple" in normalize_cli_output(result_show.stdout).lower()

    # -sh / --session-history (lists sessions)
    result_sh = run_cli_inprocess(["-sh", "10"])
    assert result_sh.exit_code == 0
    assert "test_sess_3" in normalize_cli_output(result_sh.stdout).lower()

    # grouped `session list`
    result_list = run_cli_inprocess(["session", "list", "5"])
    assert result_list.exit_code == 0
    assert "test_sess_3" in normalize_cli_output(result_list.stdout).lower()


def test_session_end_aliases():
    """Test session ending via various aliases."""
    run_cli_inprocess(["-ss", "to_be_ended_2"])
    result2 = run_cli_inprocess(["session", "end"])
    assert result2.exit_code == 0
    assert "detached from session" in normalize_cli_output(result2.stdout).lower()
    status2 = run_cli_inprocess(["session"])
    assert "no active session" in normalize_cli_output(status2.stdout).lower()

    # -se / --session-end
    run_cli_inprocess(["-ss", "to_be_ended_3"])
    result3 = run_cli_inprocess(["-se"])
    assert result3.exit_code == 0
    assert "detached from session" in normalize_cli_output(result3.stdout).lower()
    status3 = run_cli_inprocess(["session"])
    assert "no active session" in normalize_cli_output(status3.stdout).lower()


def test_session_delete_and_clean():
    """Test session deletion and research cleanup."""
    run_cli_inprocess(["session", "create", "to_delete"])
    
    # delete by name (relying on my fix in sqlite.py)
    result = run_cli_inprocess(["session", "delete", "to_delete"])
    assert result.exit_code == 0
    
    # verify gone
    result_list = run_cli_inprocess(["session", "list"])
    assert "to_delete" not in normalize_cli_output(result_list.stdout).lower()

    # session clean-research
    run_cli_inprocess(["session", "create", "to_clean"])
    result_clean = run_cli_inprocess(["session", "clean-research", "to_clean"])
    assert result_clean.exit_code == 0
    assert "cleaned research data" in normalize_cli_output(result_clean.stdout).lower()


def test_grouped_command_strictness():
    """Grouped command strictness error behavior in session context."""
    result = run_cli_inprocess(["session", "banana"])
    normalized = normalize_cli_output(result.stdout).lower()
    assert "unknown subcommand" in normalized
