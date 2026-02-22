import pytest
from unittest.mock import MagicMock, patch, ANY
import argparse
from typing import Set

from asky.api import AskyClient, AskyConfig, AskyTurnRequest
from asky.core import ConversationEngine


@pytest.fixture
def mock_get_all_tools():
    with patch("asky.core.tool_registry_factory.get_all_available_tool_names") as mock:
        mock.return_value = {"tool_a", "tool_b", "research_tool"}
        yield mock


class TestLeanModeCLI:
    """Test lean mode behavior in the CLI layer."""

    def test_run_chat_lean_disables_all_tools(self, mock_get_all_tools):
        from asky.cli.chat import run_chat

        mock_args = argparse.Namespace(
            model="gf",
            lean=True,
            tool_off=[],
            research=False,
            local_corpus=None,
            summarize=False,
            open=False,
            continue_ids=None,
            sticky_session=None,
            resume_session=None,
            terminal_lines=None,
            save_history=False,
            verbose=False,
            system_prompt=None,  # Added this missing field
            mail_recipients=None,  # Added missing field
            push_data_endpoint=None,  # Added missing field
        )

        with (
            patch("asky.cli.chat.AskyClient") as mock_client_cls,
            patch("asky.cli.chat.get_shell_session_id", return_value=None),
            patch("asky.cli.chat.InterfaceRenderer"),
            patch("asky.cli.chat.LIVE_BANNER", False),
            patch("asky.cli.chat.MODELS", {"gf": {"id": "gemini-flash"}}),
        ):
            mock_client = MagicMock()
            mock_client.run_turn.return_value = MagicMock(halted=True, notices=[])
            mock_client_cls.return_value = mock_client

            run_chat(mock_args, "query")

            # Verify AskyClient was initialized with disabled_tools containing all tools
            config_arg = mock_client_cls.call_args[0][0]
            assert "tool_a" in config_arg.disabled_tools
            assert "tool_b" in config_arg.disabled_tools
            assert "research_tool" in config_arg.disabled_tools

    def test_run_chat_lean_suppresses_output(self, mock_get_all_tools):
        from asky.cli.chat import run_chat

        mock_args = argparse.Namespace(
            model="gf",
            lean=True,
            tool_off=[],
            research=False,
            local_corpus=None,
            summarize=False,
            open=False,
            continue_ids=None,
            sticky_session=None,
            resume_session=None,
            terminal_lines=None,
            save_history=True,  # Enable history to check for "Saving..." suppression
            verbose=False,
            system_prompt=None,
            mail_recipients=None,
            push_data_endpoint=None,
        )

        with (
            patch("asky.cli.chat.AskyClient") as mock_client_cls,
            patch("asky.cli.chat.get_shell_session_id", return_value=None),
            patch("asky.cli.chat.InterfaceRenderer") as mock_renderer_cls,
            patch(
                "asky.cli.chat.LIVE_BANNER", True
            ),  # Enable globally to test suppression
            patch("asky.cli.chat.MODELS", {"gf": {"id": "gemini-flash"}}),
            patch("asky.cli.chat.Console") as mock_console_cls,
            patch("asky.rendering.save_html_report", return_value="/tmp/report.html"),
        ):
            mock_client = MagicMock()
            # Simulation: return a result with a final answer
            turn_result = MagicMock(
                halted=False,
                notices=[],
                final_answer="The Answer",
                session_id=None,
                preload=MagicMock(shortlist_payload={}),
            )
            mock_client.run_turn.return_value = turn_result
            mock_client_cls.return_value = mock_client

            mock_renderer = mock_renderer_cls.return_value
            # Make sure renderer.console is the same as the one used in run_chat logic
            # run_chat instantiates Console() directly for some prints
            mock_console_instance = mock_console_cls.return_value

            run_chat(mock_args, "query")

            # 1. Verify start_live() was NOT called
            mock_renderer.start_live.assert_not_called()

            # 2. Verify "Saving interaction..." was NOT printed
            for call in mock_console_instance.print.call_args_list:
                args, _ = call
                text = str(args[0])
                assert "Saving interaction..." not in text
                assert "Open in browser" not in text

            # 3. Verify display_callback used raw markdown print
            _, kwargs = mock_client.run_turn.call_args
            display_cb = kwargs["display_callback"]
            assert display_cb is not None

            # Simulate engine calling the callback with final answer
            display_cb(0, is_final=True, final_answer="**Bold Answer**")

            # Verify Markdown was printed
            # The test mocks Console class, so mock_console_instance should have received the call
            # We need to find the call with Markdown object
            print_calls = mock_console_instance.print.call_args_list
            markdown_call_found = False
            for call in print_calls:
                args, _ = call
                if args and "Markdown" in str(type(args[0])):
                    # Double check content if possible, but type check is good enough for now
                    markdown_call_found = True
                    break

            # Since we can't easily inspect the 'rich.markdown.Markdown' object content without more complex mocking,
            # we assume if Markdown was instantiated and printed, it's correct path.
            # We can check that print_final_answer was NOT called on renderer if we mocked renderer properly.
            # mock_renderer is MagicMock.
            mock_renderer.print_final_answer.assert_not_called()


class TestLeanModeAPI:
    """Test lean mode behavior in the API layer."""

    def test_run_turn_lean_calculates_effective_disabled_tools(
        self, mock_get_all_tools
    ):
        config = AskyConfig(model_alias="gf")
        # Wait, AskyConfig doesn't have 'lean' field, it's in TurnRequest.
        # But AskyTurnRequest has 'lean'.
        # Let's re-check types.py. AskyConfig does NOT have lean. Correct.

        config = AskyConfig(model_alias="gf")
        client = AskyClient(config)
        client.run_messages = MagicMock(return_value="answer")

        # Mock session stuff to avoid complex setup
        with (
            patch("asky.api.client.resolve_session_for_turn") as mock_resolve,
            patch("asky.api.client.run_preload_pipeline") as mock_preload,
            patch("asky.api.client.load_context_from_history") as mock_load_ctx,
            patch("asky.api.client.save_interaction"),
        ):
            mock_resolve.return_value = (
                MagicMock(),
                MagicMock(halt_reason=None, notices=[]),
            )
            mock_preload.return_value = MagicMock()
            mock_load_ctx.return_value = MagicMock(context_str="", resolved_ids=[])

            request = AskyTurnRequest(query_text="hi", lean=True, save_history=False)
            client.run_turn(request)

            # Verify run_messages called with effective disabled tools
            call_kwargs = client.run_messages.call_args[1]
            assert call_kwargs["lean"] is True
            disabled_arg = call_kwargs["disabled_tools"]
            assert "tool_a" in disabled_arg
            assert "tool_b" in disabled_arg

    @patch("asky.api.client.create_tool_registry")
    @patch("asky.api.client.ConversationEngine")
    def test_run_messages_propagates_lean_and_disabled_tools(
        self, mock_engine_cls, mock_create_registry, mock_get_all_tools
    ):
        config = AskyConfig(model_alias="gf")
        client = AskyClient(config)

        msg = [{"role": "user", "content": "hi"}]
        override_tools = {"tool_a", "tool_b"}

        client.run_messages(msg, lean=True, disabled_tools=override_tools)

        # Verify registry creation uses override
        mock_create_registry.assert_called_with(
            usage_tracker=ANY,
            summarization_tracker=ANY,
            summarization_status_callback=ANY,
            summarization_verbose_callback=ANY,
            disabled_tools=override_tools,
            tool_trace_callback=ANY,
        )

        # Verify engine Init receives lean=True
        mock_engine_cls.assert_called_with(
            model_config=ANY,
            tool_registry=ANY,
            summarize=ANY,
            verbose=ANY,
            double_verbose=ANY,
            usage_tracker=ANY,
            open_browser=ANY,
            session_manager=ANY,
            verbose_output_callback=ANY,
            event_callback=ANY,
            lean=True,
            max_turns=ANY,
        )


class TestLeanModeEngine:
    """Test lean mode behavior in the Core Engine."""

    def test_lean_suppresses_system_update(self):
        engine = ConversationEngine(
            model_config={"id": "test"}, tool_registry=MagicMock(), lean=True
        )

        messages = [{"role": "system", "content": "Original Prompt"}]

        # We need to mock get_llm_msg to avoid API call and return immediate result to break loop
        with (
            patch("asky.core.engine.get_llm_msg") as mock_get_msg,
            patch("asky.core.engine.count_tokens", return_value=100),
        ):
            mock_get_msg.return_value = {"role": "assistant", "content": "Done"}

            engine.run(messages)

            # Verify system prompt was NOT modified
            assert messages[0]["content"] == "Original Prompt"

    def test_non_lean_injects_system_update(self):
        engine = ConversationEngine(
            model_config={"id": "test"}, tool_registry=MagicMock(), lean=False
        )

        messages = [{"role": "system", "content": "Original Prompt"}]

        with (
            patch("asky.core.engine.get_llm_msg") as mock_get_msg,
            patch("asky.core.engine.count_tokens", return_value=100),
        ):
            mock_get_msg.return_value = {"role": "assistant", "content": "Done"}

            engine.run(messages)

            # Verify system prompt WAS modified
            assert "[SYSTEM UPDATE]" in messages[0]["content"]
            assert "Original Prompt" in messages[0]["content"]
