import pytest
from unittest.mock import patch
from pathlib import Path

from tests.integration.cli_recorded.helpers import (
    assert_output_contains_fragments,
    normalize_cli_output,
    run_cli_inprocess,
)

pytestmark = [pytest.mark.recorded_cli, pytest.mark.vcr]


def test_chat_control_model_alias():
    """Test -m / --model alias selection."""
    result = run_cli_inprocess(["-m", "gf", "-off", "all", "--shortlist", "off", "Just say apple."])
    assert result.exit_code == 0
    assert_output_contains_fragments(result.stdout, ["main model", "gf"])


def test_chat_control_summarize():
    """Test -s / --summarize flag."""
    # We trust VCR to match the summarization request if recorded
    result = run_cli_inprocess(["-s", "-off", "all", "--shortlist", "off", "Summarize https://example.com"])
    assert result.exit_code == 0


def test_chat_control_turns():
    """Test -t / --turns flag."""
    result = run_cli_inprocess(["-t", "5", "-off", "all", "--shortlist", "off", "Just say apple."])
    assert result.exit_code == 0
    # Banner shows turns
    assert "turns: 1/5" in normalize_cli_output(result.stdout).lower()


def test_chat_control_lean():
    """Test -L / --lean flag."""
    result = run_cli_inprocess(["-L", "Just say apple."])
    assert result.exit_code == 0
    # Lean mode suppresses the banner
    assert "main model" not in normalize_cli_output(result.stdout).lower()
    assert "apple" in normalize_cli_output(result.stdout).lower()


def test_chat_control_shortlist():
    """Test --shortlist on/off/reset."""
    run_cli_inprocess(["-ss", "shortlist_test"])
    # Set shortlist off (defaults only)
    run_cli_inprocess(["-rs", "shortlist_test", "--shortlist", "off"])
    
    # Verify persisted in next turn
    result = run_cli_inprocess(["-rs", "shortlist_test", "-off", "all", "Query 2"])
    assert result.exit_code == 0


def test_chat_control_tools_overrides():
    """Test --tools off and --list-tools."""
    # --list-tools
    result = run_cli_inprocess(["--list-tools"])
    assert result.exit_code == 0
    assert "available" in normalize_cli_output(result.stdout).lower()

    # --tools off (persisted)
    run_cli_inprocess(["-ss", "tools_test"])
    run_cli_inprocess(["-rs", "tools_test", "--tools", "off"])
    
    # Verify persisted
    result = run_cli_inprocess(["-rs", "tools_test", "Just say apple."])
    assert result.exit_code == 0


def test_chat_control_system_prompt():
    """Test -sp / --system-prompt override."""
    # We trust VCR matching for the exact prompt
    result = run_cli_inprocess(["-sp", "You are a pirate.", "-off", "all", "--shortlist", "off", "Just say apple."])
    assert result.exit_code == 0


@patch("asky.cli.terminal.get_terminal_context", return_value="LAST_TERMINAL_LINE")
def test_chat_control_terminal_lines(mock_get_term):
    """Test -tl / --terminal-lines flag."""
    result = run_cli_inprocess(["-tl", "5", "-off", "all", "--shortlist", "off", "What is above?"])
    assert result.exit_code == 0


def test_chat_control_verbose():
    """Test -v and -vv flags."""
    # -v
    result = run_cli_inprocess(["-v", "-off", "all", "--shortlist", "off", "Just say apple."])
    assert result.exit_code == 0
    # Verbose shows preloaded context panel
    assert "preloaded context" in normalize_cli_output(result.stdout).lower()

    # -vv
    result_vv = run_cli_inprocess(["-vv", "-off", "all", "--shortlist", "off", "Just say apple."])
    assert result_vv.exit_code == 0
    assert "main model" in normalize_cli_output(result_vv.stdout).lower()


def test_chat_control_completion_script():
    """Test --completion-script flag."""
    result = run_cli_inprocess(["--completion-script", "bash"])
    assert result.exit_code == 0
    assert "python_argcomplete" in result.stdout


@patch("webbrowser.open")
def test_chat_control_open(mock_open):
    """Test -o / --open flag."""
    result = run_cli_inprocess(["-o", "-off", "all", "--shortlist", "off", "Just say apple."])
    assert result.exit_code == 0
    assert mock_open.called
    assert "open in browser" in normalize_cli_output(result.stdout).lower()
