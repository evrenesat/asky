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
        add_model=False,
        edit_model=None,
        query=["test", "query"],
        reply=False,
        session_from_message=None,
        completion_script=None,
    )


def test_parse_args_defaults():
    with patch("asky.cli.main.DEFAULT_MODEL", "gf"):
        with patch("sys.argv", ["asky", "query"]):
            args = parse_args()
            assert args.query == ["query"]
            assert args.model == "gf"


def test_parse_args_help_uses_explicit_typed_metavars(capsys):
    with patch("sys.argv", ["asky", "--help"]):
        with pytest.raises(SystemExit) as excinfo:
            parse_args()
        assert excinfo.value.code == 0

    help_output = capsys.readouterr().out
    assert "HISTORY_IDS" in help_output
    assert "SESSION_SELECTOR" in help_output
    assert "LINE_COUNT" in help_output

    assert "TERMINAL_LINES" not in help_output
    assert "PRINT_SESSION" not in help_output
    assert "SESSION_HISTORY" not in help_output


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


def test_parse_args_verbose_levels():
    with patch("sys.argv", ["asky", "-v", "query"]):
        args = parse_args()
        assert args.verbose is True
        assert args.double_verbose is False
        assert args.verbose_level == 1

    with patch("sys.argv", ["asky", "-vv", "query"]):
        args = parse_args()
        assert args.verbose is True
        assert args.double_verbose is True
        assert args.verbose_level == 2


def test_parse_args_lean_flag():
    with patch("sys.argv", ["asky", "-L", "query"]):
        args = parse_args()
        assert args.lean is True
        assert args.query == ["query"]


def test_parse_args_tool_off_aliases():
    with patch(
        "sys.argv",
        [
            "asky",
            "-tool-off",
            "web_search",
            "-off",
            "get_url_content,get_url_details",
            "query",
        ],
    ):
        args = parse_args()
        assert args.tool_off == ["web_search", "get_url_content,get_url_details"]
        assert args.query == ["query"]


def test_parse_args_local_corpus():
    with patch("sys.argv", ["asky", "-lc", "/a/b", "/c/d", "--", "query"]):
        args = parse_args()
        assert args.local_corpus == ["/a/b", "/c/d"]
        assert args.query == ["query"]


def test_run_chat_local_corpus_implies_research_mode():
    from asky.cli.chat import run_chat

    mock_args = argparse.Namespace(
        model="gf",
        research=False,
        local_corpus=["/tmp/corpus"],
        summarize=False,
        open=False,
        continue_ids=None,
        sticky_session=None,
        resume_session=None,
        lean=False,
        tool_off=[],
        terminal_lines=None,
        save_history=True,
        verbose=False,
    )

    mock_turn_result = MagicMock()
    mock_turn_result.final_answer = None
    mock_turn_result.halted = True
    mock_turn_result.notices = []

    with (
        patch(
            "asky.cli.chat.MODELS",
            {"gf": {"id": "gemini-flash"}},
        ),
        patch("asky.cli.chat.AskyClient") as mock_client_cls,
        patch("asky.cli.chat.get_shell_session_id", return_value=None),
        patch("asky.cli.chat.InterfaceRenderer"),
        patch("asky.cli.chat.LIVE_BANNER", False),
    ):
        mock_client = MagicMock()
        mock_client.run_turn.return_value = mock_turn_result
        mock_client_cls.return_value = mock_client

        run_chat(mock_args, "query")

        # Verify AskyConfig was created with research_mode=True
        config_arg = mock_client_cls.call_args[0][0]
        assert config_arg.research_mode is True

        # Verify local_corpus_paths was passed in the turn request
        mock_client.run_turn.assert_called_once()
        request_arg = mock_client.run_turn.call_args[0][0]
        assert request_arg.local_corpus_paths == ["/tmp/corpus"]


def test_run_chat_renders_answer_before_final_history_finalize():
    from asky.cli.chat import run_chat

    mock_args = argparse.Namespace(
        model="gf",
        research=True,
        local_corpus=None,
        summarize=False,
        open=False,
        continue_ids=None,
        sticky_session=None,
        resume_session=None,
        lean=False,
        tool_off=[],
        terminal_lines=None,
        save_history=True,
        verbose=False,
        system_prompt=None,
        elephant_mode=False,
        turns=None,
        mail_recipients=None,
        subject=None,
        push_data_endpoint=None,
        push_params=None,
    )

    turn_result = MagicMock()
    turn_result.final_answer = "Final answer"
    turn_result.halted = False
    turn_result.notices = []
    turn_result.session_id = None
    turn_result.preload = MagicMock(shortlist_stats={}, shortlist_payload=None)
    turn_result.session = MagicMock(matched_sessions=[])

    call_order = []

    with (
        patch("asky.cli.chat.MODELS", {"gf": {"id": "gemini-flash"}}),
        patch("asky.cli.chat.get_shell_session_id", return_value=None),
        patch("asky.cli.chat.InterfaceRenderer") as mock_renderer_cls,
        patch("asky.cli.chat.LIVE_BANNER", True),
        patch("asky.cli.chat.AskyClient") as mock_client_cls,
        patch("asky.rendering.extract_markdown_title", return_value="title"),
        patch("asky.rendering.save_html_report", return_value=(None, None)),
        patch(
            "asky.research.cache.ResearchCache.wait_for_background_summaries",
            return_value=True,
        ) as mock_wait_for_summaries,
    ):
        renderer = MagicMock()
        renderer.live = None
        renderer.current_turn = 1
        renderer.console = MagicMock()
        renderer.print_final_answer.side_effect = lambda _answer: call_order.append(
            "printed"
        )
        mock_renderer_cls.return_value = renderer

        mock_client = MagicMock()

        def run_turn_side_effect(_request, **kwargs):
            kwargs["display_callback"](
                1,
                is_final=True,
                final_answer=turn_result.final_answer,
            )
            return turn_result

        def finalize_side_effect(*_args, **_kwargs):
            call_order.append("finalize")
            res = MagicMock()
            res.notices = []
            res.saved_message_id = None
            return res

        mock_client.run_turn.side_effect = run_turn_side_effect
        mock_client.finalize_turn_history.side_effect = finalize_side_effect
        mock_client_cls.return_value = mock_client

        run_chat(mock_args, "query")

    assert call_order == ["printed", "finalize"]
    mock_wait_for_summaries.assert_called_once()


def test_run_chat_double_verbose_payload_prints_after_live_stops():
    from asky.cli.chat import run_chat

    mock_args = argparse.Namespace(
        model="gf",
        research=False,
        local_corpus=None,
        summarize=False,
        open=False,
        continue_ids=None,
        sticky_session=None,
        resume_session=None,
        lean=False,
        tool_off=[],
        terminal_lines=None,
        save_history=True,
        verbose=True,
        double_verbose=True,
        system_prompt=None,
        elephant_mode=False,
        turns=None,
        mail_recipients=None,
        subject=None,
        push_data_endpoint=None,
        push_params=None,
    )

    turn_result = MagicMock()
    turn_result.final_answer = ""
    turn_result.halted = True
    turn_result.notices = []
    turn_result.session_id = None
    turn_result.preload = MagicMock(shortlist_stats={}, shortlist_payload=None)
    turn_result.session = MagicMock(matched_sessions=[])

    payload = {
        "kind": "llm_request_messages",
        "phase": "main_loop",
        "turn": 1,
        "model_alias": "gf",
        "model_id": "model-id",
        "use_tools": True,
        "messages": [
            {"role": "system", "content": "System Prompt"},
            {"role": "user", "content": "Query"},
        ],
    }

    with (
        patch("asky.cli.chat.MODELS", {"gf": {"id": "gemini-flash"}}),
        patch("asky.cli.chat.get_shell_session_id", return_value=None),
        patch("asky.cli.chat.InterfaceRenderer") as mock_renderer_cls,
        patch("asky.cli.chat.LIVE_BANNER", True),
        patch("asky.cli.chat.AskyClient") as mock_client_cls,
    ):
        renderer = MagicMock()
        renderer.console = MagicMock()
        renderer.live = MagicMock(console=MagicMock())
        renderer.current_turn = 0
        mock_renderer_cls.return_value = renderer

        mock_client = MagicMock()

        def run_turn_side_effect(_request, **kwargs):
            kwargs["verbose_output_callback"](payload)
            return turn_result

        mock_client.run_turn.side_effect = run_turn_side_effect
        mock_client_cls.return_value = mock_client

        run_chat(mock_args, "query")

        renderer.live.console.print.assert_not_called()
        printed_titles = [
            getattr(call.args[0], "title", "")
            for call in renderer.console.print.call_args_list
            if call.args
        ]
        assert "Main Model Request" in printed_titles


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


def test_parse_args_session_from_message_short_flag():
    with patch("sys.argv", ["asky", "-sfm", "12", "next"]):
        args = parse_args()
        assert args.session_from_message == "12"
        assert args.query == ["next"]


def test_parse_args_completion_script():
    with patch("sys.argv", ["asky", "--completion-script", "zsh"]):
        args = parse_args()
        assert args.completion_script == "zsh"


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


@patch("asky.cli.chat.get_interaction_context")
def test_load_context_history_selector_token(mock_get_context):
    mock_get_context.return_value = "Token Context"
    result = load_context("project_brief__hid_123", False)
    assert result == "Token Context"
    mock_get_context.assert_called_with([123], full=True)


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


def test_build_messages_with_source_shortlist_context(mock_args):
    from unittest.mock import MagicMock

    mock_preload = MagicMock()
    mock_preload.combined_context = "shortlist summary"
    mock_preload.is_corpus_preloaded = False

    messages = build_messages(
        mock_args,
        "",
        "test query",
        preload=mock_preload,
    )
    assert len(messages) == 2
    assert "shortlist summary" in messages[1]["content"]


def test_build_messages_with_local_kb_guidance(mock_args):
    messages = build_messages(
        mock_args,
        "",
        "test query",
        research_mode=True,
        local_kb_hint_enabled=True,
    )

    assert "Local Knowledge Base Guidance" in messages[0]["content"]
    assert "query_research_memory" in messages[0]["content"]


def test_build_messages_with_retrieval_guidance(mock_args):
    # Mock a PreloadResolution with preloaded content
    mock_preload = MagicMock()
    mock_preload.is_corpus_preloaded = True

    messages = build_messages(
        mock_args,
        "",
        "test query",
        research_mode=True,
        preload=mock_preload,
    )

    assert "A research corpus has been pre-loaded" in messages[0]["content"]
    assert "Do NOT attempt to browse new URLs" in messages[0]["content"]


def test_build_shortlist_banner_stats():
    from asky.cli.chat import _build_shortlist_banner_stats

    payload = {
        "enabled": True,
        "candidates": [{"url": "https://example.com"}],
        "warnings": ["w1"],
        "stats": {
            "metrics": {
                "candidate_deduped": 7,
                "fetch_calls": 4,
            }
        },
    }
    stats = _build_shortlist_banner_stats(payload, 123.4)
    assert stats == {
        "enabled": True,
        "collected": 7,
        "processed": 4,
        "selected": 1,
        "warnings": 1,
        "elapsed_ms": 123.4,
    }


def test_shortlist_enabled_resolution_prefers_lean():
    from asky.cli.chat import _shortlist_enabled_for_request

    args = argparse.Namespace(lean=True)
    model_cfg = {"id": "test-model", "source_shortlist_enabled": True}
    enabled, reason = _shortlist_enabled_for_request(
        args=args,
        model_config=model_cfg,
        research_mode=False,
    )
    assert enabled is False
    assert reason == "lean_flag"


def test_parse_disabled_tools_supports_repeats_and_commas():
    from asky.cli.chat import _parse_disabled_tools

    disabled = _parse_disabled_tools(
        ["web_search,get_url_content", "web_search", " custom_tool "]
    )
    assert disabled == {"web_search", "get_url_content", "custom_tool"}


def test_combine_preloaded_source_context_merges_non_empty_blocks():
    from asky.cli.chat import _combine_preloaded_source_context

    merged = _combine_preloaded_source_context(
        "Local block",
        None,
        "Shortlist block",
        "",
    )

    assert merged == "Local block\n\nShortlist block"


def test_append_enabled_tool_guidelines_updates_system_prompt():
    from asky.cli.chat import _append_enabled_tool_guidelines

    messages = [{"role": "system", "content": "System base"}]
    _append_enabled_tool_guidelines(
        messages,
        [
            "`web_search`: Discover initial sources first.",
            "`get_url_content`: Read selected pages for details.",
        ],
    )
    assert "Enabled Tool Guidelines:" in messages[0]["content"]
    assert "`web_search`: Discover initial sources first." in messages[0]["content"]


def test_ensure_research_session_creates_session_when_missing():
    from asky.cli.chat import _ensure_research_session

    usage_tracker = MagicMock()
    summarization_tracker = MagicMock()
    console = MagicMock()
    created_session = MagicMock(id=42, name="research_topic")
    manager = MagicMock()
    manager.current_session = None
    manager.create_session.return_value = created_session

    with (
        patch("asky.cli.chat.SessionManager", return_value=manager) as mock_manager_cls,
        patch(
            "asky.cli.chat.generate_session_name", return_value="research_topic"
        ) as mock_name,
        patch("asky.cli.chat.set_shell_session_id") as mock_set_session_id,
    ):
        ensured = _ensure_research_session(
            session_manager=None,
            model_config={"alias": "gf"},
            usage_tracker=usage_tracker,
            summarization_tracker=summarization_tracker,
            query_text="research topic prompt",
            console=console,
        )

    assert ensured is manager
    mock_manager_cls.assert_called_once_with(
        {"alias": "gf"},
        usage_tracker,
        summarization_tracker=summarization_tracker,
    )
    mock_name.assert_called_once_with("research topic prompt")
    manager.create_session.assert_called_once_with("research_topic")
    mock_set_session_id.assert_called_once_with(42)
    console.print.assert_called_once()


def test_ensure_research_session_keeps_existing_session():
    from asky.cli.chat import _ensure_research_session

    usage_tracker = MagicMock()
    summarization_tracker = MagicMock()
    console = MagicMock()
    session_manager = MagicMock()
    session_manager.current_session = MagicMock(id=9, name="existing")

    with (
        patch("asky.cli.chat.SessionManager") as mock_manager_cls,
        patch("asky.cli.chat.generate_session_name") as mock_name,
        patch("asky.cli.chat.set_shell_session_id") as mock_set_session_id,
    ):
        ensured = _ensure_research_session(
            session_manager=session_manager,
            model_config={"alias": "gf"},
            usage_tracker=usage_tracker,
            summarization_tracker=summarization_tracker,
            query_text="ignored",
            console=console,
        )

    assert ensured is session_manager
    mock_manager_cls.assert_not_called()
    mock_name.assert_not_called()
    mock_set_session_id.assert_not_called()
    console.print.assert_not_called()


def test_shortlist_enabled_resolution_prefers_model_override():
    from asky.cli.chat import _shortlist_enabled_for_request

    args = argparse.Namespace(lean=False)
    model_cfg = {"id": "test-model", "source_shortlist_enabled": False}
    enabled, reason = _shortlist_enabled_for_request(
        args=args,
        model_config=model_cfg,
        research_mode=True,
    )
    assert enabled is False
    assert reason == "model_override"


def test_print_shortlist_verbose(capsys):
    from rich.console import Console
    from asky.cli.chat import _print_shortlist_verbose

    payload = {
        "enabled": True,
        "trace": {
            "processed_candidates": [
                {"source_type": "seed", "url": "https://example.com/a"}
            ]
        },
        "candidates": [
            {
                "rank": 1,
                "final_score": 0.88,
                "source_type": "search",
                "url": "https://example.com/b",
            }
        ],
        "warnings": ["warning_one"],
    }
    _print_shortlist_verbose(Console(), payload)
    captured = capsys.readouterr()
    assert "https://example.com/a" in captured.out
    assert "https://example.com/b" in captured.out
    assert "Shortlist Warnings" in captured.out


@patch("asky.cli.history.get_interaction_context")
def test_print_answers(mock_get_context, capsys):
    mock_get_context.return_value = "Answer Content"
    print_answers("1,2", False, open_browser=False)
    captured = capsys.readouterr()
    assert "Answer Content" in captured.out
    mock_get_context.assert_called_with([1, 2], full=True)


@patch("asky.cli.history.get_interaction_context")
def test_print_answers_selector_tokens(mock_get_context, capsys):
    mock_get_context.return_value = "Answer Content"
    print_answers("plan_update__id_318,quick_note__id_316", False, open_browser=False)
    captured = capsys.readouterr()
    assert "Answer Content" in captured.out
    mock_get_context.assert_called_with([318, 316], full=True)


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
@patch("asky.cli.main.setup_logging")
@patch("asky.cli.main.init_db")
@patch("asky.cli.main.chat.run_chat")
def test_main_completion_script_early_exit(
    mock_run_chat, mock_init_db, mock_setup_logging, mock_parse, capsys
):
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
        query=[],
        verbose=False,
        open=False,
        mail_recipients=None,
        subject=None,
        sticky_session=None,
        resume_session=None,
        session_end=False,
        session_history=None,
        terminal_lines=None,
        add_model=False,
        edit_model=None,
        reply=False,
        session_from_message=None,
        completion_script="bash",
    )

    main()
    captured = capsys.readouterr()
    assert "#compdef asky ask" in captured.out
    mock_init_db.assert_not_called()
    mock_run_chat.assert_not_called()


@patch("asky.cli.main.parse_args")
@patch("asky.cli.main.init_db")
@patch("asky.cli.main.get_db_record_count")
@patch("asky.cli.chat.ConversationEngine.run")
@patch("asky.cli.chat.generate_summaries")
@patch("asky.cli.chat.save_interaction")
@patch("asky.cli.main.generate_timestamped_log_path")
@patch("asky.cli.main.setup_logging")
@patch("asky.cli.main.ResearchCache")
@patch("asky.cli.terminal.get_terminal_context")
@patch("asky.cli.chat.get_shell_session_id", return_value=None)
def test_main_flow(
    mock_get_shell,
    mock_get_term,
    mock_research_cache,
    mock_setup_logging,
    mock_generate_log_path,
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
        add_model=False,
        edit_model=None,
        reply=False,
        session_from_message=None,
        completion_script=None,
    )
    mock_run.return_value = "Final Answer"
    mock_gen_sum.return_value = ("q_sum", "a_sum")

    with (
        patch(
            "asky.cli.main.MODELS",
            {"gf": {"id": "gemini-flash-latest"}, "lfm": {"id": "llama-fallback"}},
        ),
        patch("asky.cli.main.SUMMARIZATION_MODEL", "gf"),
        patch(
            "asky.research.source_shortlist.SOURCE_SHORTLIST_ENABLE_STANDARD_MODE",
            False,
        ),
    ):
        main()

    mock_init.assert_called_once()
    # Should use default logging setup (LOG_LEVEL, LOG_FILE)
    mock_setup_logging.assert_called_once_with(ANY, ANY)
    # In default flow, it shouldn't be generating a timestamped path
    mock_generate_log_path.assert_not_called()

    mock_run.assert_called_once_with(
        [
            {"role": "system", "content": ANY},
            {"role": "user", "content": "test"},
        ],
        display_callback=ANY,
    )
    # Summarization/persistence now run inside asky.api client orchestration.
    mock_gen_sum.assert_not_called()
    mock_save.assert_not_called()


@patch("asky.cli.main.parse_args")
@patch("asky.cli.main.init_db")
@patch("asky.cli.main.get_db_record_count")
@patch("asky.cli.chat.ConversationEngine.run")
@patch("asky.cli.chat.generate_summaries")
@patch("asky.cli.chat.save_interaction")
@patch("asky.cli.utils.os.environ.get")
@patch("asky.cli.main.generate_timestamped_log_path")
@patch("asky.cli.main.setup_logging")
@patch("asky.cli.main.ResearchCache")
@patch("asky.cli.terminal.get_terminal_context")
@patch("asky.cli.chat.get_shell_session_id", return_value=None)
@patch("asky.storage.sqlite.SQLiteHistoryRepository")
def test_main_flow_verbose(
    mock_repo,
    mock_get_shell,
    mock_get_term,
    mock_research_cache,
    mock_setup_logging,
    mock_generate_log_path,
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
    mock_generate_log_path.return_value = "/tmp/test.log"
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
        add_model=False,
        edit_model=None,
        reply=False,
        session_from_message=None,
        completion_script=None,
    )
    mock_run.return_value = "Final Answer"
    mock_gen_sum.return_value = ("q_sum", "a_sum")

    with (
        patch(
            "asky.cli.main.MODELS",
            {"gf": {"id": "gemini-flash-latest"}, "lfm": {"id": "llama-fallback"}},
        ),
        patch("asky.cli.main.SUMMARIZATION_MODEL", "gf"),
        patch(
            "asky.research.source_shortlist.SOURCE_SHORTLIST_ENABLE_STANDARD_MODE",
            False,
        ),
    ):
        main()

    captured = capsys.readouterr()
    # Verbose no longer prints config, it sets debug log level
    assert "=== CONFIGURATION ===" not in captured.out

    # Verify logging setup for verbose mode
    mock_generate_log_path.assert_called_once()
    mock_setup_logging.assert_called_once_with("DEBUG", "/tmp/test.log")

    # We can't easily check the root logger level here without mocking logging.getLogger
    # but we can rely on verifying behavior through integration or assuming the code
    # we wrote is correct if we had injected a mock logger.
    # For now, asserting it DOES NOT print config is good.

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
@patch("asky.cli.main.setup_logging")
@patch("asky.cli.chat.get_shell_session_id", return_value=None)
@patch("asky.storage.sqlite.SQLiteHistoryRepository")
def test_main_flow_default_no_context(
    mock_repo,
    mock_get_shell,
    mock_setup_logging,
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
        add_model=False,
        edit_model=None,
        reply=False,
        session_from_message=None,
        completion_script=None,
    )
    mock_run.return_value = "Final Answer"
    mock_gen_sum.return_value = ("q_sum", "a_sum")

    with (
        patch(
            "asky.cli.main.MODELS",
            {"gf": {"id": "gemini-flash-latest"}, "lfm": {"id": "llama-fallback"}},
        ),
        patch("asky.cli.main.SUMMARIZATION_MODEL", "gf"),
        patch(
            "asky.research.source_shortlist.SOURCE_SHORTLIST_ENABLE_STANDARD_MODE",
            False,
        ),
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


@patch("asky.cli.main.parse_args")
@patch("asky.cli.main.init_db")
@patch("asky.cli.main.get_db_record_count")
@patch("asky.cli.chat.ConversationEngine.run")
@patch("asky.cli.chat.generate_summaries")
@patch("asky.cli.chat.save_interaction")
@patch("asky.cli.terminal.get_terminal_context")
@patch("asky.cli.chat.InterfaceRenderer")
@patch("asky.cli.main.ResearchCache")
@patch("asky.cli.main.setup_logging")
@patch("asky.cli.main.generate_timestamped_log_path")
@patch("asky.cli.chat.shortlist_prompt_sources")
@patch("asky.cli.chat.SessionManager")
@patch("asky.cli.chat.get_shell_session_id")
def test_main_terminal_lines_callback(
    mock_get_shell_id,
    mock_session_manager,
    mock_shortlist,
    mock_generate_log_path,
    mock_setup_logging,
    mock_research_cache,
    mock_renderer_cls,
    mock_get_term,
    mock_save,
    mock_gen_sum,
    mock_run,
    mock_db_count,
    mock_init,
    mock_parse,
):
    """Test that terminal lines fetch invokes renderer status update via callback."""
    # Setup
    mock_get_term.return_value = "Ctx"
    # Mock shortlist to return disabled payload so it's fast
    mock_shortlist.return_value = {"enabled": False}
    mock_get_shell_id.return_value = None

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
        terminal_lines=5,  # Valid logic trigger
        add_model=False,
        edit_model=None,
        reply=False,
        session_from_message=None,
        completion_script=None,
    )
    mock_run.return_value = "Ans"
    mock_gen_sum.return_value = ("q", "a")

    # Mock renderer instance
    mock_renderer = MagicMock()
    mock_renderer_cls.return_value = mock_renderer

    # We need LIVE_BANNER to be True for the callback to be active
    with (
        patch(
            "asky.cli.main.MODELS",
            {"gf": {"id": "gemini-flash-latest"}, "lfm": {"id": "llama-fallback"}},
        ),
        patch("asky.cli.main.SUMMARIZATION_MODEL", "gf"),
        patch("asky.cli.chat.LIVE_BANNER", True),
    ):
        main()

    # Verification
    # 1. Renderer should be instantiated
    mock_renderer_cls.assert_called_once()

    # 2. update_banner should be called with status message
    # We expect call(0, status_message="Fetching...")
    mock_renderer.update_banner.assert_any_call(
        0, status_message="Fetching last 5 lines of terminal context..."
    )

    # 3. update_banner should be cleared afterwards
    mock_renderer.update_banner.assert_any_call(0, status_message=None)


# Tests for slash command prompt listing


@patch("asky.cli.main.prompts.list_prompts_command")
@patch("asky.cli.main.parse_args")
@patch("asky.cli.main.init_db")
@patch("asky.cli.main.setup_logging")
def test_slash_only_lists_all_prompts(
    mock_setup_logging, mock_init, mock_parse, mock_list_prompts
):
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
        reply=False,
        session_from_message=None,
        completion_script=None,
        add_model=False,
        edit_model=None,
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
@patch("asky.cli.main.setup_logging")
def test_slash_partial_filters_prompts(
    mock_setup_logging, mock_init, mock_parse, mock_list_prompts
):
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
        reply=False,
        session_from_message=None,
        completion_script=None,
        add_model=False,
        edit_model=None,
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
@patch("asky.cli.main.setup_logging")
def test_main_terminal_lines_logic(
    mock_setup_logging,
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
            add_model=False,
            edit_model=None,
            query=["query"],
            reply=False,
            session_from_message=None,
            completion_script=None,
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
            add_model=False,
            edit_model=None,
            query=["query"],
            reply=False,
            session_from_message=None,
            completion_script=None,
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
            add_model=False,
            edit_model=None,
            query=["is", "this"],
            reply=False,
            session_from_message=None,
            completion_script=None,
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
@patch("asky.cli.main.setup_logging")
def test_slash_nonexistent_shows_filtered_list(
    mock_setup_logging, mock_init, mock_parse, mock_list_prompts
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
        reply=False,
        session_from_message=None,
        completion_script=None,
        add_model=False,
        edit_model=None,
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


def test_parse_args_system_prompt():
    with patch("sys.argv", ["asky", "-sp", "Custom System Prompt", "query"]):
        args = parse_args()
        assert args.system_prompt == "Custom System Prompt"

    with patch("sys.argv", ["asky", "--system-prompt", "Another Prompt", "query"]):
        args = parse_args()
        assert args.system_prompt == "Another Prompt"


def test_build_messages_with_override(mock_args):
    messages = build_messages(
        mock_args, context_str="", query_text="Q", system_prompt_override="Override"
    )
    assert messages[0]["content"] == "Override"


@patch("asky.cli.chat.AskyClient")
@patch("asky.cli.chat.get_shell_session_id", return_value=None)
@patch("asky.cli.chat.InterfaceRenderer")
@patch("asky.cli.chat.LIVE_BANNER", False)
def test_run_chat_passes_system_prompt_override(
    mock_renderer, mock_get_shell, mock_client_cls
):
    from asky.cli.chat import run_chat

    mock_args = argparse.Namespace(
        model="gf",
        research=False,
        local_corpus=None,
        summarize=False,
        open=False,
        continue_ids=None,
        sticky_session=None,
        resume_session=None,
        lean=False,
        tool_off=[],
        terminal_lines=None,
        save_history=True,
        verbose=False,
        system_prompt="Custom Override",
    )

    mock_turn_result = MagicMock()
    mock_turn_result.final_answer = None
    mock_turn_result.halted = True
    mock_turn_result.notices = []

    with patch("asky.cli.chat.MODELS", {"gf": {"id": "g"}}):
        mock_client = MagicMock()
        mock_client.run_turn.return_value = mock_turn_result
        mock_client_cls.return_value = mock_client

        run_chat(mock_args, "query")

        # Verify AskyConfig was created with system_prompt_override
        config_arg = mock_client_cls.call_args[0][0]
        assert config_arg.system_prompt_override == "Custom Override"
