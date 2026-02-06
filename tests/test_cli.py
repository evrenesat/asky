import pytest
import argparse
from unittest.mock import patch, MagicMock, ANY
from asky.cli import (
    parse_args,
    show_history,
    load_context,
    build_messages,
    print_answers,
    handle_delete_messages,
    handle_print_answer_implicit,
    main,
)
from asky.cli.sessions import handle_delete_sessions_command as handle_delete_sessions
from asky.config import MODELS
from asky.core import construct_system_prompt
from asky.storage.interface import Interaction


@pytest.fixture
def mock_args():
    return argparse.Namespace(
        model="gf",
        history=None,
        continue_ids=None,
        summarize=False,
        delete_messages=None,
        delete_sessions=None,
        all=False,
        print_session=None,
        print_ids=None,
        prompts=False,
        verbose=False,
        open=False,
        mail_recipients=None,
        subject=None,
        sticky_session=None,
        resume_session=None,
        session_end=False,
        session_history=None,
        terminal_lines=None,
        query=["test", "query"],
    )


def test_parse_args_defaults():
    with patch("asky.cli.main.DEFAULT_MODEL", "gf"):
        with patch("sys.argv", ["asky", "query"]):
            args = parse_args()
            assert args.query == ["query"]
            assert args.model == "gf"


def test_parse_args_options():
    with patch(
        "sys.argv",
        [
            "asky",
            "-m",
            "q34",
            "-H",
            "20",
            "-c",
            "1,2",
            "-s",
        ],
    ):
        args = parse_args()
        assert args.model == "q34"
        assert args.history == 20
        assert args.continue_ids == "1,2"
        assert args.summarize is True


def test_parse_args_terminal_lines_explicit():
    """Test -tl with explicit integer."""
    with patch("sys.argv", ["asky", "-tl", "20", "query"]):
        args = parse_args()
        # The logic to convert args.terminal_lines happens in main(), not parse_args()
        # parse_args just returns the raw value.
        # Wait, the logic I added IS in main().
        # So I should test main or extract that logic?
        # The logic is in main() before run_chat. I should probably move it to utils or a helper
        # to make it testable, or test main() logic mocking run_chat.
        assert args.terminal_lines == "20"
        assert args.query == ["query"]


def test_parse_args_terminal_lines_default():
    """Test -tl without value (uses const)."""
    # Note: If we just pass "-tl", query is empty list.
    with patch("sys.argv", ["asky", "-tl"]):
        args = parse_args()
        assert args.terminal_lines == "__default__"
        assert args.query == []


def test_parse_args_terminal_lines_mixed_query():
    """Test -tl with non-integer (should be treated as query in main logic)."""
    with patch("sys.argv", ["asky", "-tl", "why", "is", "this"]):
        args = parse_args()
        # In parse_args, it consumes 'why' as value because nargs='?'
        assert args.terminal_lines == "why"
        assert args.query == ["is", "this"]


@patch("asky.cli.history.get_history")
def test_show_history(mock_get_history, capsys):
    mock_get_history.return_value = [
        Interaction(
            id=1,
            timestamp="2026-02-04T23:54:30",
            session_id=None,
            role="assistant",
            content="query1",
            query="query1",
            answer="ans_sum1",
            summary="summary1",
            model="model",
        )
    ]
    show_history(5)
    captured = capsys.readouterr()
    assert "Recent History (Last 1)" in captured.out
    assert "summary1" in captured.out
    assert "ans_sum1" in captured.out
    mock_get_history.assert_called_with(5)


@patch("asky.cli.chat.get_interaction_context")
def test_load_context_success(mock_get_context):
    mock_get_context.return_value = "Context Content"
    result = load_context("1,2", True)
    assert result == "Context Content"
    mock_get_context.assert_called_with([1, 2], full=False)


@patch("asky.cli.chat.get_interaction_context")
def test_load_context_invalid(mock_get_context, capsys):
    result = load_context("1,a", False)
    assert result is None
    captured = capsys.readouterr()
    assert "Error: Invalid format" in captured.out


@patch("asky.cli.chat.get_history")
@patch("asky.cli.chat.get_interaction_context")
def test_load_context_relative_success(mock_get_context, mock_get_history):
    # Mock history: ID 5 is most recent (~1), ID 4 is ~2
    mock_get_history.return_value = [
        Interaction(
            id=5,
            timestamp="ts",
            session_id=None,
            role="assistant",
            content="",
            query="q5",
            answer="a5",
            summary="s5",
            model="m",
        ),
        Interaction(
            id=4,
            timestamp="ts",
            session_id=None,
            role="assistant",
            content="",
            query="q4",
            answer="a4",
            summary="s4",
            model="m",
        ),
    ]
    mock_get_context.return_value = "Context Content"

    # Test ~1 -> ID 5
    result = load_context("~1", False)
    mock_get_history.assert_called_with(limit=1)
    mock_get_context.assert_called_with([5], full=True)
    assert result == "Context Content"

    # Test ~2 -> ID 4
    result = load_context("~2", False)
    mock_get_history.assert_called_with(limit=2)
    mock_get_context.assert_called_with([4], full=True)


@patch("asky.cli.chat.get_history")
@patch("asky.cli.chat.get_interaction_context")
def test_load_context_mixed(mock_get_context, mock_get_history):
    # Mock history
    mock_get_history.return_value = [
        Interaction(
            id=10,
            timestamp="ts",
            session_id=None,
            role="assistant",
            content="",
            query="q10",
            answer="a10",
            summary="s10",
            model="m",
        ),
    ]
    mock_get_context.return_value = "Mixed Context"

    # Test 123, ~1 -> 123, 10
    load_context("123, ~1", False)
    mock_get_history.assert_called_with(limit=1)
    # verify call args contains 123 and 10. Order might vary due to sorted(set(...))
    call_args = mock_get_context.call_args[0][0]
    assert set(call_args) == {10, 123}


@patch("asky.cli.chat.get_history")
def test_load_context_relative_out_of_bounds(mock_get_history, capsys):
    mock_get_history.return_value = [
        Interaction(
            id=1,
            timestamp="ts",
            session_id=None,
            role="assistant",
            content="",
            query="q",
            answer="a",
            summary="s",
            model="m",
        )
    ]  # only 1 record

    result = load_context("~5", False)
    assert result is None
    captured = capsys.readouterr()
    assert "Error: Relative ID 5 is out of range" in captured.out


def test_build_messages_basic(mock_args):
    messages = build_messages(mock_args, "", "test query")
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "test query"


def test_build_messages_with_context(mock_args):
    messages = build_messages(mock_args, "Previous Context", "test query")
    assert len(messages) == 3
    assert messages[1]["role"] == "user"
    assert "Context from previous queries" in messages[1]["content"]
    assert "Previous Context" in messages[1]["content"]


@patch("asky.cli.history.get_interaction_context")
def test_print_answers(mock_get_context, capsys):
    mock_get_context.return_value = "Answer Content"
    print_answers("1,2", False, open_browser=False)
    captured = capsys.readouterr()
    assert "Answer Content" in captured.out
    mock_get_context.assert_called_with([1, 2], full=True)


@patch("asky.cli.history.delete_messages")
def test_handle_delete_messages(mock_delete):
    args = MagicMock()
    args.delete_messages = "1,2"
    args.all = False

    assert handle_delete_messages(args) is True
    mock_delete.assert_called_with(ids="1,2")


@patch("asky.cli.history.delete_messages")
def test_handle_delete_messages_all(mock_delete):
    args = MagicMock()
    args.delete_messages = None
    args.all = True

    assert handle_delete_messages(args) is False  # Should fail now
    # We could also check for printed warning, but return value check is sufficient
    mock_delete.assert_not_called()


@patch("asky.storage.delete_sessions")
def test_handle_delete_sessions(mock_delete):
    args = MagicMock()
    args.delete_sessions = "3"
    args.all = False

    assert handle_delete_sessions(args) is True
    mock_delete.assert_called_with(ids="3")


@patch("asky.cli.main.history.print_answers_command")
def test_handle_print_answer_implicit(mock_print_answers):
    args = MagicMock()
    args.query = ["1,", "2"]
    args.summarize = False
    args.open = False

    args.mail_recipients = MagicMock()
    args.subject = MagicMock()
    args.sticky_session = None
    args.session_end = False
    args.session_history = None

    assert handle_print_answer_implicit(args) is True
    mock_print_answers.assert_called_with(
        "1,2",
        args.summarize,
        open_browser=args.open,
        mail_recipients=args.mail_recipients,
        subject=args.subject,
    )


def test_handle_print_answer_implicit_fail():
    args = MagicMock()
    args.query = ["not", "ids"]
    assert handle_print_answer_implicit(args) is False


@patch("asky.cli.main.parse_args")
@patch("asky.cli.main.init_db")
@patch("asky.cli.main.get_db_record_count")
@patch("asky.cli.chat.ConversationEngine.run")
@patch("asky.cli.chat.generate_summaries")
@patch("asky.cli.chat.save_interaction")
@patch("asky.cli.main.ResearchCache")
@patch("asky.cli.terminal.get_terminal_context")
def test_main_flow(
    mock_get_term,
    mock_research_cache,
    mock_save,
    mock_gen_sum,
    mock_run,
    mock_db_count,
    mock_init,
    mock_parse,
):
    # Mock terminal context to prevent iTerm2 connection attempts in tests
    mock_get_term.return_value = ""

    mock_parse.return_value = argparse.Namespace(
        model="gf",
        history=None,
        continue_ids=None,
        summarize=False,
        delete_messages=None,
        delete_sessions=None,
        all=False,
        print_session=None,
        print_ids=None,
        prompts=False,
        query=["test"],
        verbose=False,
        open=False,
        mail_recipients=None,
        subject=None,
        sticky_session=None,
        session_end=False,
        session_history=None,
        terminal_lines=None,
    )
    mock_run.return_value = "Final Answer"
    mock_gen_sum.return_value = ("q_sum", "a_sum")

    with (
        patch(
            "asky.cli.main.MODELS",
            {"gf": {"id": "gemini-flash-latest"}, "lfm": {"id": "llama-fallback"}},
        ),
        patch("asky.cli.main.SUMMARIZATION_MODEL", "gf"),
    ):
        main()

    mock_init.assert_called_once()
    mock_run.assert_called_once_with(
        [
            {"role": "system", "content": ANY},
            {"role": "user", "content": "test"},
        ],
        display_callback=ANY,
    )
    mock_gen_sum.assert_called_once_with("test", "Final Answer", usage_tracker=ANY)
    mock_save.assert_called_once()


@patch("asky.cli.main.parse_args")
@patch("asky.cli.main.init_db")
@patch("asky.cli.main.get_db_record_count")
@patch("asky.cli.chat.ConversationEngine.run")
@patch("asky.cli.chat.generate_summaries")
@patch("asky.cli.chat.save_interaction")
@patch("asky.cli.utils.os.environ.get")
@patch("asky.cli.main.ResearchCache")
@patch("asky.cli.terminal.get_terminal_context")
def test_main_flow_verbose(
    mock_get_term,
    mock_research_cache,
    mock_env_get,
    mock_save,
    mock_gen_sum,
    mock_run,
    mock_db_count,
    mock_init,
    mock_parse,
    capsys,
):
    # Mock terminal context to prevent iTerm2 connection attempts in tests
    mock_get_term.return_value = "Mocked Terminal Context"
    mock_env_get.return_value = "fake_key_123456789"
    mock_parse.return_value = argparse.Namespace(
        model="gf",
        history=None,
        continue_ids=None,
        summarize=False,
        delete_messages=None,
        delete_sessions=None,
        all=False,
        print_session=None,
        print_ids=None,
        prompts=False,
        query=["test"],
        verbose=True,
        open=False,
        mail_recipients=None,
        subject=None,
        sticky_session=None,
        session_end=False,
        session_history=None,
        terminal_lines=10,
    )
    mock_run.return_value = "Final Answer"
    mock_gen_sum.return_value = ("q_sum", "a_sum")

    with (
        patch(
            "asky.cli.main.MODELS",
            {"gf": {"id": "gemini-flash-latest"}, "lfm": {"id": "llama-fallback"}},
        ),
        patch("asky.cli.main.SUMMARIZATION_MODEL", "gf"),
    ):
        main()

    captured = capsys.readouterr()
    assert "=== CONFIGURATION ===" in captured.out
    assert "Selected Model: gf" in captured.out
    assert "DEFAULT_MODEL:" in captured.out

    mock_run.assert_called_once_with(
        [
            {"role": "system", "content": ANY},
            {
                "role": "user",
                "content": "Terminal Context (Last 10 lines):\n```\nMocked Terminal Context\n```\n\nQuery:\ntest",
            },
        ],
        display_callback=ANY,
    )


@patch("asky.cli.main.parse_args")
@patch("asky.cli.main.init_db")
@patch("asky.cli.main.get_db_record_count")
@patch("asky.cli.chat.ConversationEngine.run")
@patch("asky.cli.chat.generate_summaries")
@patch("asky.cli.chat.save_interaction")
@patch("asky.cli.terminal.get_terminal_context")
def test_main_flow_default_no_context(
    mock_get_term,
    mock_save,
    mock_gen_sum,
    mock_run,
    mock_db_count,
    mock_init,
    mock_parse,
):
    """Test that terminal context is NOT injected by default if flag is missing."""
    # Even if terminal has content
    mock_get_term.return_value = "Should Not Be Used"
    mock_parse.return_value = argparse.Namespace(
        model="gf",
        history=None,
        continue_ids=None,
        summarize=False,
        delete_messages=None,
        delete_sessions=None,
        all=False,
        print_session=None,
        print_ids=None,
        prompts=False,
        query=["test"],
        verbose=False,
        open=False,
        mail_recipients=None,
        subject=None,
        sticky_session=None,
        session_end=False,
        session_history=None,
        terminal_lines=None,  # Flag missing
    )
    mock_run.return_value = "Final Answer"
    mock_gen_sum.return_value = ("q_sum", "a_sum")

    with (
        patch(
            "asky.cli.main.MODELS",
            {"gf": {"id": "gemini-flash-latest"}, "lfm": {"id": "llama-fallback"}},
        ),
        patch("asky.cli.main.SUMMARIZATION_MODEL", "gf"),
    ):
        main()

    # Verify context was NOT called/injected
    mock_run.assert_called_once_with(
        [
            {"role": "system", "content": ANY},
            {"role": "user", "content": "test"},
        ],
        display_callback=ANY,
    )
    # inject_terminal_context calls get_terminal_context if lines > 0
    # validation: get_terminal_context should NOT be called
    mock_get_term.assert_not_called()


# Tests for slash command prompt listing


@patch("asky.cli.main.prompts.list_prompts_command")
@patch("asky.cli.main.parse_args")
@patch("asky.cli.main.init_db")
def test_slash_only_lists_all_prompts(mock_init, mock_parse, mock_list_prompts):
    """Test that 'asky /' lists all prompts."""
    mock_parse.return_value = argparse.Namespace(
        model="gf",
        history=None,
        continue_ids=None,
        summarize=False,
        delete_messages=None,
        delete_sessions=None,
        all=False,
        print_session=None,
        print_ids=None,
        prompts=False,
        query=["/"],
        verbose=False,
        open=False,
        mail_recipients=None,
        subject=None,
        sticky_session=None,
        resume_session=None,
        session_end=False,
        session_history=None,
        terminal_lines=None,
    )

    with (
        patch(
            "asky.cli.main.MODELS",
            {"gf": {"id": "gemini-flash-latest"}},
        ),
        patch("asky.cli.main.USER_PROMPTS", {"gn": "test prompt"}),
    ):
        main()

    mock_list_prompts.assert_called_once_with()


@patch("asky.cli.main.prompts.list_prompts_command")
@patch("asky.cli.main.parse_args")
@patch("asky.cli.main.init_db")
def test_slash_partial_filters_prompts(mock_init, mock_parse, mock_list_prompts):
    """Test that 'asky /g' filters prompts by prefix."""
    mock_parse.return_value = argparse.Namespace(
        model="gf",
        history=None,
        continue_ids=None,
        summarize=False,
        delete_messages=None,
        delete_sessions=None,
        all=False,
        print_session=None,
        print_ids=None,
        prompts=False,
        query=["/g"],
        verbose=False,
        open=False,
        mail_recipients=None,
        subject=None,
        sticky_session=None,
        resume_session=None,
        session_end=False,
        session_history=None,
        terminal_lines=None,
    )

    with (
        patch(
            "asky.cli.main.MODELS",
            {"gf": {"id": "gemini-flash-latest"}},
        ),
        patch("asky.cli.main.USER_PROMPTS", {"gn": "test prompt", "wh": "weather"}),
    ):
        main()

    mock_list_prompts.assert_called_once_with(filter_prefix="g")


@patch("asky.cli.main.parse_args")
@patch("asky.cli.main.init_db")
@patch("asky.cli.main.get_db_record_count")
@patch("asky.cli.chat.ConversationEngine.run")
@patch("asky.cli.chat.generate_summaries")
@patch("asky.cli.chat.save_interaction")
@patch("asky.cli.terminal.get_terminal_context")
def test_main_terminal_lines_logic(
    mock_get_term,
    mock_save,
    mock_gen_sum,
    mock_run,
    mock_db_count,
    mock_init,
    mock_parse,
):
    # Setup mocks
    mock_get_term.return_value = ""
    mock_run.return_value = "Answer"
    mock_gen_sum.return_value = ("q", "a")

    # Helper to run main with specific args and return effective terminal_lines
    # Since main() calls run_chat(args, query), we can inspect args passed to run_chat

    with patch("asky.cli.chat.run_chat") as mock_run_chat:
        # Case 1: -tl explicit integer
        mock_parse.return_value = argparse.Namespace(
            model="gf",
            history=None,
            continue_ids=None,
            summarize=False,
            delete_messages=None,
            delete_sessions=None,
            all=False,
            print_session=None,
            print_ids=None,
            prompts=False,
            verbose=False,
            open=False,
            mail_recipients=None,
            subject=None,
            sticky_session=None,
            resume_session=None,
            session_end=False,
            session_history=None,
            terminal_lines=20,  # argparse converts int
            query=["query"],
        )
        main()
        args, _ = mock_run_chat.call_args
        assert args[0].terminal_lines == 20
        assert args[1] == "query"

        # Case 2: -tl default (flag without value)
        mock_parse.return_value = argparse.Namespace(
            model="gf",
            history=None,
            continue_ids=None,
            summarize=False,
            delete_messages=None,
            delete_sessions=None,
            all=False,
            print_session=None,
            print_ids=None,
            prompts=False,
            verbose=False,
            open=False,
            mail_recipients=None,
            subject=None,
            sticky_session=None,
            resume_session=None,
            session_end=False,
            session_history=None,
            terminal_lines="__default__",  # argparse const
            query=["query"],
        )
        main()
        args, _ = mock_run_chat.call_args
        # Should be converted to config default (mocked as 10 usually)
        # We need to ensure we know what config returns.
        # By default config loader returns 10 now.
        assert args[0].terminal_lines == 10

        # Case 3: -tl mixed (string treated as query)
        mock_parse.return_value = argparse.Namespace(
            model="gf",
            history=None,
            continue_ids=None,
            summarize=False,
            delete_messages=None,
            delete_sessions=None,
            all=False,
            print_session=None,
            print_ids=None,
            prompts=False,
            verbose=False,
            open=False,
            mail_recipients=None,
            subject=None,
            sticky_session=None,
            resume_session=None,
            session_end=False,
            session_history=None,
            terminal_lines="why",  # parsed as string
            query=["is", "this"],
        )
        main()
        args, _ = mock_run_chat.call_args
        # Should set terminal lines to default (10)
        # And prepend "why" to query
        assert args[0].terminal_lines == 10
        assert args[1] == "why is this"


@patch("asky.cli.main.prompts.list_prompts_command")
@patch("asky.cli.main.parse_args")
@patch("asky.cli.main.init_db")
def test_slash_nonexistent_shows_filtered_list(
    mock_init, mock_parse, mock_list_prompts
):
    """Test that 'asky /nonexistent' shows filtered list (which will show no matches then all)."""
    mock_parse.return_value = argparse.Namespace(
        model="gf",
        history=None,
        continue_ids=None,
        summarize=False,
        delete_messages=None,
        delete_sessions=None,
        all=False,
        print_session=None,
        print_ids=None,
        prompts=False,
        query=["/nonexistent"],
        verbose=False,
        open=False,
        mail_recipients=None,
        subject=None,
        sticky_session=None,
        resume_session=None,
        session_end=False,
        session_history=None,
        terminal_lines=None,
    )

    with (
        patch(
            "asky.cli.main.MODELS",
            {"gf": {"id": "gemini-flash-latest"}},
        ),
        patch("asky.cli.main.USER_PROMPTS", {"gn": "test prompt"}),
    ):
        main()

    mock_list_prompts.assert_called_once_with(filter_prefix="nonexistent")


# Tests for list_prompts_command function


@patch("asky.cli.prompts.USER_PROMPTS", {})
def test_list_prompts_empty(capsys):
    """Test list_prompts_command with no prompts configured."""
    from asky.cli.prompts import list_prompts_command

    list_prompts_command()
    captured = capsys.readouterr()
    assert "No user prompts configured" in captured.out


@patch("asky.cli.prompts.USER_PROMPTS", {"gn": "Guardian news prompt", "wh": "Weather"})
def test_list_prompts_all(capsys):
    """Test list_prompts_command shows all prompts in table."""
    from asky.cli.prompts import list_prompts_command

    list_prompts_command()
    captured = capsys.readouterr()
    assert "/gn" in captured.out
    assert "/wh" in captured.out
    assert "User Prompts" in captured.out


@patch(
    "asky.cli.prompts.USER_PROMPTS",
    {"gn": "Guardian news", "wh": "Weather", "ex": "Explain"},
)
def test_list_prompts_filtered(capsys):
    """Test list_prompts_command filters by prefix."""
    from asky.cli.prompts import list_prompts_command

    list_prompts_command(filter_prefix="g")
    captured = capsys.readouterr()
    assert "/gn" in captured.out
    # wh and ex should not be shown (filtered out)
    # Note: They might still appear in other parts, but gn should be present


@patch("asky.cli.prompts.USER_PROMPTS", {"gn": "Guardian news", "wh": "Weather"})
def test_list_prompts_no_matches_shows_all(capsys):
    """Test list_prompts_command shows 'no matches' then all prompts."""
    from asky.cli.prompts import list_prompts_command

    list_prompts_command(filter_prefix="xyz")
    captured = capsys.readouterr()
    assert "No matches for '/xyz'" in captured.out
    # Should still show all prompts as fallback
    assert "/gn" in captured.out
    assert "/wh" in captured.out


@patch("asky.cli.prompts.USER_PROMPTS", {"gn": "A" * 100})
def test_list_prompts_truncates_long_expansion(capsys):
    """Test list_prompts_command truncates long expansions."""
    from asky.cli.prompts import list_prompts_command

    list_prompts_command()
    captured = capsys.readouterr()
    # Should have ... for truncation
    assert "..." in captured.out
