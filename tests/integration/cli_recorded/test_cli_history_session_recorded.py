import pytest

from tests.integration.cli_recorded.helpers import (
    assert_output_contains_sentences,
    normalize_cli_output,
    run_cli_inprocess,
)

pytestmark = [pytest.mark.recorded_cli, pytest.mark.vcr]


def test_history_list_and_flags():
    """Test history list and flags."""
    run_cli_inprocess(["-off", "all", "--shortlist", "off", "What is the capital of France? Answer simply."])
    run_cli_inprocess(["-off", "all", "--shortlist", "off", "What is the capital of Japan? Answer simply."])

    # grouped `history list`
    result = run_cli_inprocess(["history", "list"])
    assert result.exit_code == 0
    normalized = normalize_cli_output(result.stdout)
    assert "france" in normalized.lower()
    assert "japan" in normalized.lower()

    # -H flag
    result2 = run_cli_inprocess(["-H", "2"])
    assert result2.exit_code == 0


def test_history_show_and_print_answer():
    """Test history show and print-answer."""
    run_cli_inprocess(["-off", "all", "--shortlist", "off", "Just say apple."])
    
    # history list to find ID (usually 1 if fresh)
    result_list = run_cli_inprocess(["history", "list", "1"])
    assert result_list.exit_code == 0
    
    # history show
    result_show = run_cli_inprocess(["history", "show", "1"])
    assert result_show.exit_code == 0
    assert "apple" in normalize_cli_output(result_show.stdout).lower()

    # -pa / --print-answer
    result_pa = run_cli_inprocess(["-pa", "1"])
    assert result_pa.exit_code == 0
    assert "apple" in normalize_cli_output(result_pa.stdout).lower()


def test_history_delete_and_all():
    """Test history deletion."""
    run_cli_inprocess(["-off", "all", "--shortlist", "off", "Turn 1"])
    run_cli_inprocess(["-off", "all", "--shortlist", "off", "Turn 2"])

    # delete single
    result = run_cli_inprocess(["history", "delete", "1"])
    assert result.exit_code == 0

    # --delete-messages --all
    result_all = run_cli_inprocess(["--delete-messages", "--all"])
    assert result_all.exit_code == 0
    assert "deleted all" in normalize_cli_output(result_all.stdout).lower()


def test_session_delete_all():
    """Test session deletion with --all."""
    run_cli_inprocess(["session", "create", "sess_to_del_1"])
    run_cli_inprocess(["session", "create", "sess_to_del_2"])
    
    # --delete-sessions --all
    result = run_cli_inprocess(["--delete-sessions", "--all"])
    assert result.exit_code == 0
    assert "deleted all" in normalize_cli_output(result.stdout).lower()


def test_session_from_message_and_reply():
    """Test --session-from-message and --reply."""
    run_cli_inprocess(["-off", "all", "--shortlist", "off", "I am a user query."])
    
    # --session-from-message
    result = run_cli_inprocess(["-sfm", "1"])
    assert result.exit_code == 0
    assert "converted message 1 to session" in normalize_cli_output(result.stdout).lower()

    # grouped `session from-message`
    run_cli_inprocess(["-off", "all", "--shortlist", "off", "Another turn."])
    result_grouped = run_cli_inprocess(["session", "from-message", "1"])
    assert result_grouped.exit_code == 0
    assert "converted message 1 to session" in normalize_cli_output(result_grouped.stdout).lower()

    # --reply
    run_cli_inprocess(["-off", "all", "--shortlist", "off", "Another query."])
    result_reply = run_cli_inprocess(["--reply", "Tell me more."])
    assert result_reply.exit_code == 0


def test_continue_chat():
    """Test -c / --continue-chat."""
    run_cli_inprocess(["-off", "all", "--shortlist", "off", "First message."])

    # continue last implicitly
    result = run_cli_inprocess(["-c", "Second message."])
    assert result.exit_code == 0
    assert "loaded context from ids" in normalize_cli_output(result.stdout).lower()

    # continue specific ID
    result2 = run_cli_inprocess(["-c", "1", "Third message."])
    assert result2.exit_code == 0
    assert "loaded context from ids: 1" in normalize_cli_output(result2.stdout).lower()


def test_prompts_list():
    """Test --prompts and grouped command."""
    # --prompts
    result = run_cli_inprocess(["--prompts"])
    assert result.exit_code == 0
    normalized = normalize_cli_output(result.stdout).lower()
    assert "user prompts" in normalized
    assert "/gn" in normalized

    # prompts list
    result2 = run_cli_inprocess(["prompts", "list"])
    assert result2.exit_code == 0
    normalized2 = normalize_cli_output(result2.stdout).lower()
    assert "user prompts" in normalized2
    assert "/wh" in normalized2
