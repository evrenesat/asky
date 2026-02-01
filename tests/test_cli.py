import pytest
import argparse
from unittest.mock import patch, MagicMock
from asearch.cli import (
    parse_args,
    show_history,
    load_context,
    build_messages,
    print_answers,
    handle_cleanup,
    handle_print_answer_implicit,
    handle_print_answer_implicit,
    main,
)
from asearch.config import MODELS
from asearch.llm import construct_system_prompt


@pytest.fixture
def mock_args():
    return argparse.Namespace(
        model="gf",
        deep_research=0,
        deep_dive=False,
        history=None,
        continue_ids=None,
        full=False,
        summarize=False,
        force_search=False,
        cleanup_db=None,
        all=False,
        print_ids=None,
        query=["test", "query"],
    )


def test_parse_args_defaults():
    with patch("sys.argv", ["asearch", "query"]):
        args = parse_args()
        assert args.query == ["query"]
        assert args.model == "gf"
        assert args.deep_research == 0
        assert args.deep_dive is False


def test_parse_args_options():
    with patch(
        "sys.argv",
        [
            "asearch",
            "-m",
            "q34",
            "-d",
            "5",
            "-dd",
            "-H",
            "20",
            "-c",
            "1,2",
            "-f",
            "-s",
            "-fs",
        ],
    ):
        args = parse_args()
        assert args.model == "q34"
        assert args.deep_research == 5
        assert args.deep_dive is True
        assert args.history == 20
        assert args.continue_ids == "1,2"
        assert args.full is True
        assert args.summarize is True
        assert args.force_search is True


@patch("asearch.cli.get_history")
def test_show_history(mock_get_history, capsys):
    mock_get_history.return_value = [
        (1, "ts", "query1", "summary1", "ans_sum1", "model")
    ]
    show_history(5)
    captured = capsys.readouterr()
    assert "Last 1 Queries:" in captured.out
    assert "summary1" in captured.out
    assert "ans_sum1" in captured.out
    mock_get_history.assert_called_with(5)


@patch("asearch.cli.get_interaction_context")
def test_load_context_success(mock_get_context):
    mock_get_context.return_value = "Context Content"
    result = load_context("1,2", False)
    assert result == "Context Content"
    mock_get_context.assert_called_with([1, 2], full=False)


@patch("asearch.cli.get_interaction_context")
def test_load_context_invalid(mock_get_context, capsys):
    result = load_context("1,a", False)
    assert result is None
    captured = capsys.readouterr()
    assert "Error: Invalid format" in captured.out


@patch("asearch.cli.get_history")
@patch("asearch.cli.get_interaction_context")
def test_load_context_relative_success(mock_get_context, mock_get_history):
    # Mock history: ID 5 is most recent (~1), ID 4 is ~2
    mock_get_history.return_value = [
        (5, "ts", "q5", "s5", "a5", "m"),
        (4, "ts", "q4", "s4", "a4", "m"),
    ]
    mock_get_context.return_value = "Context Content"

    # Test ~1 -> ID 5
    result = load_context("~1", False)
    mock_get_history.assert_called_with(limit=1)
    mock_get_context.assert_called_with([5], full=False)
    assert result == "Context Content"

    # Test ~2 -> ID 4
    result = load_context("~2", False)
    mock_get_history.assert_called_with(limit=2)
    mock_get_context.assert_called_with([4], full=False)


@patch("asearch.cli.get_history")
@patch("asearch.cli.get_interaction_context")
def test_load_context_mixed(mock_get_context, mock_get_history):
    # Mock history
    mock_get_history.return_value = [
        (10, "ts", "q10", "s10", "a10", "m"),
    ]
    mock_get_context.return_value = "Mixed Context"

    # Test 123, ~1 -> 123, 10
    load_context("123, ~1", False)
    mock_get_history.assert_called_with(limit=1)
    # verify call args contains 123 and 10. Order might vary due to sorted(set(...))
    call_args = mock_get_context.call_args[0][0]
    assert set(call_args) == {10, 123}


@patch("asearch.cli.get_history")
def test_load_context_relative_out_of_bounds(mock_get_history, capsys):
    mock_get_history.return_value = [(1, "ts", "q", "s", "a", "m")]  # only 1 record

    result = load_context("~5", False)
    assert result is None
    captured = capsys.readouterr()
    assert "Error: Relative ID 5 is out of range" in captured.out


def test_build_messages_basic(mock_args):
    messages = build_messages(mock_args, "")
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "test query"


def test_build_messages_with_context(mock_args):
    messages = build_messages(mock_args, "Previous Context")
    assert len(messages) == 3
    assert messages[1]["role"] == "user"
    assert "Context from previous queries" in messages[1]["content"]
    assert "Previous Context" in messages[1]["content"]


@patch("asearch.cli.get_interaction_context")
def test_print_answers(mock_get_context, capsys):
    mock_get_context.return_value = "Answer Content"
    print_answers("1,2", True)
    captured = capsys.readouterr()
    assert "Answer Content" in captured.out
    mock_get_context.assert_called_with([1, 2], full=True)


@patch("asearch.cli.cleanup_db")
def test_handle_cleanup(mock_cleanup):
    args = MagicMock()
    args.cleanup_db = "1,2"
    args.all = False

    assert handle_cleanup(args) is True
    mock_cleanup.assert_called_with("1,2")


@patch("asearch.cli.cleanup_db")
def test_handle_cleanup_all(mock_cleanup):
    args = MagicMock()
    args.cleanup_db = None
    args.all = True

    assert handle_cleanup(args) is True
    mock_cleanup.assert_called_with(None, delete_all=True)


@patch("asearch.cli.print_answers")
def test_handle_print_answer_implicit(mock_print_answers):
    args = MagicMock()
    args.query = ["1,", "2"]
    args.full = False

    assert handle_print_answer_implicit(args) is True
    mock_print_answers.assert_called_with("1,2", False)


def test_handle_print_answer_implicit_fail():
    args = MagicMock()
    args.query = ["not", "ids"]
    assert handle_print_answer_implicit(args) is False


@patch("asearch.cli.parse_args")
@patch("asearch.cli.init_db")
@patch("asearch.cli.run_conversation_loop")
@patch("asearch.cli.generate_summaries")
@patch("asearch.cli.save_interaction")
def test_main_flow(mock_save, mock_gen_sum, mock_run_loop, mock_init, mock_parse):
    mock_parse.return_value = argparse.Namespace(
        model="gf",
        deep_research=0,
        deep_dive=False,
        history=None,
        continue_ids=None,
        full=False,
        summarize=False,
        force_search=False,
        cleanup_db=None,
        all=False,
        print_ids=None,
        query=["test"],
        verbose=False,
    )
    mock_run_loop.return_value = "Final Answer"
    mock_gen_sum.return_value = ("q_sum", "a_sum")

    main()

    mock_init.assert_called_once()
    mock_run_loop.assert_called_once_with(
        MODELS["gf"],
        [
            {"role": "system", "content": construct_system_prompt(0, False, False)},
            {"role": "user", "content": "test"},
        ],
        False,
        verbose=False,
    )
    mock_save.assert_called_once()


@patch("asearch.cli.parse_args")
@patch("asearch.cli.init_db")
@patch("asearch.cli.run_conversation_loop")
@patch("asearch.cli.generate_summaries")
@patch("asearch.cli.save_interaction")
@patch("asearch.cli.os.environ.get")
def test_main_flow_verbose(
    mock_env_get, mock_save, mock_gen_sum, mock_run_loop, mock_init, mock_parse, capsys
):
    mock_env_get.return_value = "fake_key_123456789"
    mock_parse.return_value = argparse.Namespace(
        model="gf",
        deep_research=0,
        deep_dive=False,
        history=None,
        continue_ids=None,
        full=False,
        summarize=False,
        force_search=False,
        cleanup_db=None,
        all=False,
        print_ids=None,
        query=["test"],
        verbose=True,
    )
    mock_run_loop.return_value = "Final Answer"
    mock_gen_sum.return_value = ("q_sum", "a_sum")

    main()

    captured = capsys.readouterr()
    assert "=== CONFIGURATION ===" in captured.out
    assert "Selected Model: gf" in captured.out
    assert "DEFAULT_MODEL:" in captured.out
    assert "[Status]: SET" in captured.out
    # We can't strictly assert SET/NOT SET without knowing the env,
    # but we can check if the code path printing [Status] is triggered if we mock os.environ.get
    # For now, let's just ensure no crash.
    # Actually, let's mock os.environ.get to ensure we see "SET" or "NOT SET"

    mock_run_loop.assert_called_once_with(
        MODELS["gf"],
        [
            {"role": "system", "content": construct_system_prompt(0, False, False)},
            {"role": "user", "content": "test"},
        ],
        False,
        verbose=True,
    )
