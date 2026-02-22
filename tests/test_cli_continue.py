import argparse
from unittest.mock import patch, MagicMock
from asky.cli.main import parse_args, main


def test_parse_args_continue_no_value():
    """Verify that -c/--continue-chat with no value sets the sentinel."""
    with patch("sys.argv", ["asky", "question", "-c"]):
        args = parse_args()
        assert args.continue_ids == "__last__"
        assert args.query == ["question"]


def test_parse_args_continue_with_value():
    """Verify that -c/--continue-chat with a value sets that value."""
    with patch("sys.argv", ["asky", "-c", "1,2", "question"]):
        args = parse_args()
        assert args.continue_ids == "1,2"
        assert args.query == ["question"]


def test_parse_args_continue_plaintext_recovery():
    """Verify that if continue_ids is plaintext (not a selector), it's recovered into the query and continue falls back to ~1."""
    with patch("sys.argv", ["asky", "-c", "Tell", "me", "more"]):
        args = parse_args()
        # After argparse: continue_ids="Tell", query=["me", "more"]
        # After main() resolution: continue_ids="~1", query=["Tell", "me", "more"]
        # Note: parse_args() alone doesn't run the resolution logic, main() does.
        # So here we just verify the raw parse.
        assert args.continue_ids == "Tell"
        assert args.query == ["me", "more"]


@patch("asky.cli.main.parse_args")
@patch("asky.cli.main.chat.run_chat")
@patch("asky.cli.main.init_db")
@patch("asky.cli.main.SQLiteHistoryRepository")
@patch("asky.api.context.load_context_from_history")
@patch("asky.cli.main.get_shell_session_id")
def test_main_continue_resolves_sentinel_and_converts_session(
    mock_get_shell_sid,
    mock_load_ctx,
    mock_repo_cls,
    mock_init_db,
    mock_run_chat,
    mock_parse_args,
):
    """Verify main() resolves sentinel to ~1 and triggers session conversion."""
    mock_get_shell_sid.return_value = None

    mock_args = MagicMock(spec=argparse.Namespace)
    mock_args.continue_ids = "__last__"
    mock_args.query = ["hello"]
    mock_args.model = "gf"
    mock_args.verbose = False
    mock_args.completion_script = None
    mock_args.add_model = False
    mock_args.edit_model = None
    mock_args.prompts = False
    mock_args.list_tools = False
    mock_args.list_memories = False
    mock_args.delete_memory = None
    mock_args.clear_memories = False
    mock_args.history = None
    mock_args.delete_messages = None
    mock_args.delete_sessions = None
    mock_args.print_session = None
    mock_args.print_ids = None
    mock_args.session_history = None
    mock_args.session_end = False
    mock_args.reply = False
    mock_args.session_from_message = None
    mock_args.terminal_lines = None
    mock_args.sticky_session = None
    mock_args.resume_session = None
    mock_args.open = False
    mock_args.mail_recipients = None
    mock_args.subject = None
    mock_args.summarize = False

    mock_parse_args.return_value = mock_args

    # Mock context resolution
    mock_res = MagicMock()
    mock_res.resolved_ids = [42]
    mock_load_ctx.return_value = mock_res

    # Mock repo
    mock_repo = mock_repo_cls.return_value
    mock_repo.convert_history_to_session.return_value = 101

    main()

    assert mock_args.continue_ids == "~1"
    assert mock_args.resume_session == ["101"]
    mock_repo.convert_history_to_session.assert_called_once_with(42)
    mock_run_chat.assert_called_once()
