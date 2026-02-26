"""Unit tests for XEP-0050 Ad-Hoc Command handlers."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from asky.plugins.xmpp_daemon.adhoc_commands import (
    AdHocCommandHandler,
    ADHOC_COMMANDS,
    NODE_STATUS,
    NODE_LIST_SESSIONS,
    NODE_LIST_HISTORY,
    NODE_LIST_TRANSCRIPTS,
    NODE_LIST_TOOLS,
    NODE_LIST_MEMORIES,
    NODE_LIST_PROMPTS,
    NODE_LIST_PRESETS,
    NODE_QUERY,
    NODE_NEW_SESSION,
    NODE_SWITCH_SESSION,
    NODE_CLEAR_SESSION,
    NODE_USE_TRANSCRIPT,
)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class _MockJID:
    def __init__(self, jid: str):
        self.bare = jid

    def __str__(self):
        return self.bare


class _MockForm:
    def __init__(self, values: dict):
        self._values = values

    def get_values(self):
        return dict(self._values)


class _MockCommand:
    def __init__(self, form_values: dict):
        self._form = _MockForm(form_values)

    def __getitem__(self, key):
        if key == "form":
            return self._form
        raise KeyError(key)


class _MockIQ:
    def __init__(self, jid: str, form_values: dict | None = None):
        self._jid = jid
        self._form_values = form_values or {}

    def __getitem__(self, key):
        if key == "from":
            return _MockJID(self._jid)
        if key == "command":
            return _MockCommand(self._form_values)
        raise KeyError(key)


class _MockXep0004Field:
    def __init__(self):
        self.options: list[dict] = []

    def add_option(self, value, label):
        self.options.append({"value": value, "label": label})


class _MockXep0004Form:
    def __init__(self):
        self.fields: dict[str, _MockXep0004Field] = {}

    def add_field(self, var, ftype=None, label=None, required=False, value=None, **kwargs):
        field = _MockXep0004Field()
        self.fields[var] = field
        return field


class _MockXep0004:
    def make_form(self, ftype, title):
        return _MockXep0004Form()


def _make_handler(authorized: bool = True, voice_enabled: bool = False, image_enabled: bool = False):
    executor = Mock()
    executor.execute_command_text.return_value = "command result"
    executor.execute_query_text.return_value = "query result"
    executor.execute_session_command.return_value = "session result"
    executor.session_profile_manager.resolve_conversation_session_id.return_value = 42
    executor.session_profile_manager.clear_conversation.return_value = 7
    executor.transcript_manager.list_for_jid.return_value = []

    router = Mock()
    router.is_authorized.return_value = authorized

    handler = AdHocCommandHandler(
        command_executor=executor,
        router=router,
        voice_enabled=voice_enabled,
        image_enabled=image_enabled,
    )
    return handler, executor, router


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# register_all
# ---------------------------------------------------------------------------


def test_register_all_calls_add_command_for_each_entry():
    handler, _, _ = _make_handler()
    xep_0050 = Mock()
    handler.register_all(xep_0050, _MockXep0004())
    assert xep_0050.add_command.call_count == len(ADHOC_COMMANDS)
    registered_nodes = {call.kwargs["node"] for call in xep_0050.add_command.call_args_list}
    assert NODE_STATUS in registered_nodes
    assert NODE_QUERY in registered_nodes
    assert NODE_USE_TRANSCRIPT in registered_nodes


def test_register_all_logs_warning_when_no_add_command():
    handler, _, _ = _make_handler()
    xep_0050_without_method = object()
    handler.register_all(xep_0050_without_method)


def test_register_all_skips_failed_command_gracefully():
    handler, _, _ = _make_handler()
    xep_0050 = Mock()
    xep_0050.add_command.side_effect = RuntimeError("boom")
    handler.register_all(xep_0050, _MockXep0004())


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


def test_unauthorized_iq_returns_error_note_for_status():
    handler, _, _ = _make_handler(authorized=False)
    result = _run(handler._cmd_status(_MockIQ("evil@example.com"), {}))
    assert result["has_next"] is False
    assert result["notes"][0][0] == "error"
    assert "Not authorized" in result["notes"][0][1]


def test_unauthorized_iq_returns_error_note_for_query():
    handler, _, _ = _make_handler(authorized=False)
    result = _run(handler._cmd_query(_MockIQ("evil@example.com"), {}))
    assert result["notes"][0][0] == "error"


def test_unauthorized_iq_on_query_submit_returns_error():
    handler, _, _ = _make_handler(authorized=False)
    handler._xep_0004 = _MockXep0004()
    iq = _MockIQ("evil@example.com", {"query": "hello"})
    result = _run(handler._cmd_query_submit(iq, {}))
    assert result["notes"][0][0] == "error"


# ---------------------------------------------------------------------------
# Status command
# ---------------------------------------------------------------------------


def test_status_returns_jid_and_feature_flags():
    handler, _, _ = _make_handler(voice_enabled=True, image_enabled=False)
    result = _run(handler._cmd_status(_MockIQ("user@example.com"), {}))
    assert result["has_next"] is False
    text = result["notes"][0][1]
    assert "Voice transcription: enabled" in text
    assert "Image transcription: disabled" in text


def test_status_includes_connected_jid():
    handler, _, _ = _make_handler()
    result = _run(handler._cmd_status(_MockIQ("user@example.com"), {}))
    assert "Connected JID:" in result["notes"][0][1]


# ---------------------------------------------------------------------------
# Listing commands
# ---------------------------------------------------------------------------


def test_list_sessions_calls_execute_session_command():
    handler, executor, _ = _make_handler()
    result = _run(handler._cmd_list_sessions(_MockIQ("user@example.com"), {}))
    executor.execute_session_command.assert_called_once()
    call_kwargs = executor.execute_session_command.call_args.kwargs
    assert call_kwargs["command_text"] == "/session"
    assert result["notes"][0][1] == "session result"


def test_list_history_calls_execute_command_text():
    handler, executor, _ = _make_handler()
    result = _run(handler._cmd_list_history(_MockIQ("user@example.com"), {}))
    executor.execute_command_text.assert_called_once()
    call_kwargs = executor.execute_command_text.call_args.kwargs
    assert "--history" in call_kwargs["command_text"]
    assert result["has_next"] is False


def test_list_transcripts_calls_execute_command_text():
    handler, executor, _ = _make_handler()
    _run(handler._cmd_list_transcripts(_MockIQ("user@example.com"), {}))
    call_kwargs = executor.execute_command_text.call_args.kwargs
    assert "transcript list" in call_kwargs["command_text"]


def test_list_tools_returns_tool_list():
    handler, _, _ = _make_handler()
    with patch(
        "asky.plugins.xmpp_daemon.adhoc_commands.AdHocCommandHandler._run_blocking",
        new=lambda self, fn, *a, **kw: asyncio.coroutine(lambda: fn())(),
    ):
        pass

    def _fake_get_tools():
        from asky.core.tool_registry_factory import get_all_available_tool_names  # noqa: F401

        return "Available LLM tools:\n  - web_search"

    async def _run_test():
        with patch.object(handler, "_run_blocking", side_effect=lambda fn, *a, **kw: asyncio.sleep(0, result=fn())):
            return await handler._cmd_list_tools(_MockIQ("user@example.com"), {})

    # Use simple mock approach instead
    with patch(
        "asky.plugins.xmpp_daemon.adhoc_commands.AdHocCommandHandler._run_blocking"
    ) as mock_run:

        async def _fake_run(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        mock_run.side_effect = _fake_run

        async def _inner():
            with patch(
                "asky.core.tool_registry_factory.get_all_available_tool_names",
                return_value=["web_search", "get_url_content"],
            ):
                result = await handler._cmd_list_tools(_MockIQ("user@example.com"), {})
                assert "web_search" in result["notes"][0][1]

        asyncio.run(_inner())


def test_list_prompts_calls_execute_query_text_with_slash():
    handler, executor, _ = _make_handler()
    executor.execute_query_text.return_value = "Prompt Aliases:\n  /test: hello"
    result = _run(handler._cmd_list_prompts(_MockIQ("user@example.com"), {}))
    executor.execute_query_text.assert_called_once()
    call_kwargs = executor.execute_query_text.call_args.kwargs
    assert call_kwargs["query_text"] == "/"
    assert "Prompt Aliases" in result["notes"][0][1]


def test_list_presets_returns_presets_text():
    handler, _, _ = _make_handler()
    with patch("asky.cli.presets.list_presets_text", return_value="Presets:\n  \\foo: bar"):
        result = _run(handler._cmd_list_presets(_MockIQ("user@example.com"), {}))
    assert "Presets" in result["notes"][0][1]


# ---------------------------------------------------------------------------
# Query command (two-step)
# ---------------------------------------------------------------------------


def test_query_step1_returns_form_when_xep_0004_available():
    handler, _, _ = _make_handler()
    handler._xep_0004 = _MockXep0004()
    result = _run(handler._cmd_query(_MockIQ("user@example.com"), {}))
    assert result["has_next"] is True
    assert result["next"] == handler._cmd_query_submit
    assert result["payload"] is not None


def test_query_step1_returns_error_when_no_xep_0004():
    handler, _, _ = _make_handler()
    handler._xep_0004 = None
    result = _run(handler._cmd_query(_MockIQ("user@example.com"), {}))
    assert result["has_next"] is False
    assert result["notes"][0][0] == "error"


def test_query_submit_builds_plain_query():
    handler, executor, _ = _make_handler()
    iq = _MockIQ("user@example.com", {"query": "What is Python?", "research": "false"})
    result = _run(handler._cmd_query_submit(iq, {}))
    executor.execute_command_text.assert_called_once()
    cmd = executor.execute_command_text.call_args.kwargs["command_text"]
    assert "What is Python?" in cmd
    assert result["has_next"] is False


def test_query_submit_includes_research_flag_when_enabled():
    handler, executor, _ = _make_handler()
    iq = _MockIQ("user@example.com", {"query": "deep topic", "research": "true"})
    _run(handler._cmd_query_submit(iq, {}))
    cmd = executor.execute_command_text.call_args.kwargs["command_text"]
    assert "-r" in cmd


def test_query_submit_includes_model_and_turns():
    handler, executor, _ = _make_handler()
    iq = _MockIQ("user@example.com", {"query": "hello", "model": "opus", "turns": "5"})
    _run(handler._cmd_query_submit(iq, {}))
    cmd = executor.execute_command_text.call_args.kwargs["command_text"]
    assert "-m" in cmd
    assert "opus" in cmd
    assert "-t" in cmd
    assert "5" in cmd


def test_query_submit_returns_error_when_query_empty():
    handler, executor, _ = _make_handler()
    iq = _MockIQ("user@example.com", {"query": ""})
    result = _run(handler._cmd_query_submit(iq, {}))
    assert result["notes"][0][0] == "error"
    executor.execute_command_text.assert_not_called()


# ---------------------------------------------------------------------------
# New session command
# ---------------------------------------------------------------------------


def test_new_session_calls_session_new_command():
    handler, executor, _ = _make_handler()
    result = _run(handler._cmd_new_session(_MockIQ("user@example.com"), {}))
    executor.execute_session_command.assert_called_once()
    cmd = executor.execute_session_command.call_args.kwargs["command_text"]
    assert cmd == "/session new"
    assert result["has_next"] is False


# ---------------------------------------------------------------------------
# Switch session command (two-step)
# ---------------------------------------------------------------------------


def test_switch_session_step1_returns_form():
    handler, _, _ = _make_handler()
    handler._xep_0004 = _MockXep0004()
    result = _run(handler._cmd_switch_session(_MockIQ("user@example.com"), {}))
    assert result["has_next"] is True
    assert result["next"] == handler._cmd_switch_session_submit


def test_switch_session_submit_passes_selector():
    handler, executor, _ = _make_handler()
    iq = _MockIQ("user@example.com", {"selector": "42"})
    result = _run(handler._cmd_switch_session_submit(iq, {}))
    cmd = executor.execute_session_command.call_args.kwargs["command_text"]
    assert "42" in cmd
    assert result["has_next"] is False


def test_switch_session_submit_error_on_empty_selector():
    handler, executor, _ = _make_handler()
    iq = _MockIQ("user@example.com", {"selector": ""})
    result = _run(handler._cmd_switch_session_submit(iq, {}))
    assert result["notes"][0][0] == "error"
    executor.execute_session_command.assert_not_called()


# ---------------------------------------------------------------------------
# Clear session command (two-step)
# ---------------------------------------------------------------------------


def test_clear_session_step1_returns_form():
    handler, _, _ = _make_handler()
    handler._xep_0004 = _MockXep0004()
    result = _run(handler._cmd_clear_session(_MockIQ("user@example.com"), {}))
    assert result["has_next"] is True
    assert result["next"] == handler._cmd_clear_session_submit


def test_clear_session_submit_cancels_when_confirm_false():
    handler, executor, _ = _make_handler()
    iq = _MockIQ("user@example.com", {"confirm": "false"})
    result = _run(handler._cmd_clear_session_submit(iq, {}))
    assert "cancelled" in result["notes"][0][1].lower()
    executor.session_profile_manager.clear_conversation.assert_not_called()


def test_clear_session_submit_clears_when_confirmed():
    handler, executor, _ = _make_handler()
    iq = _MockIQ("user@example.com", {"confirm": "true"})
    result = _run(handler._cmd_clear_session_submit(iq, {}))
    executor.session_profile_manager.clear_conversation.assert_called_once_with(42)
    assert "Cleared 7" in result["notes"][0][1]


# ---------------------------------------------------------------------------
# Use transcript command (two-step)
# ---------------------------------------------------------------------------


def test_use_transcript_step1_returns_no_transcripts_when_empty():
    handler, executor, _ = _make_handler()
    executor.transcript_manager.list_for_jid.return_value = []
    result = _run(handler._cmd_use_transcript(_MockIQ("user@example.com"), {}))
    assert result["has_next"] is False
    assert "No transcripts" in result["notes"][0][1]


def test_use_transcript_step1_returns_form_with_options():
    handler, executor, _ = _make_handler()
    handler._xep_0004 = _MockXep0004()
    executor.transcript_manager.list_for_jid.return_value = [
        SimpleNamespace(session_transcript_id=3, transcript_text="hello world"),
        SimpleNamespace(session_transcript_id=7, transcript_text="second transcript"),
    ]
    result = _run(handler._cmd_use_transcript(_MockIQ("user@example.com"), {}))
    assert result["has_next"] is True
    assert result["next"] == handler._cmd_use_transcript_submit
    form = result["payload"]
    assert isinstance(form, _MockXep0004Form)
    assert len(form.fields["transcript_id"].options) == 2


def test_use_transcript_submit_executes_transcript_use():
    handler, executor, _ = _make_handler()
    executor.execute_command_text.return_value = "transcript answer"
    iq = _MockIQ("user@example.com", {"transcript_id": "3"})
    result = _run(handler._cmd_use_transcript_submit(iq, {}))
    cmd = executor.execute_command_text.call_args.kwargs["command_text"]
    assert "transcript use #at3" in cmd
    assert result["notes"][0][1] == "transcript answer"


def test_use_transcript_submit_error_on_empty_id():
    handler, executor, _ = _make_handler()
    iq = _MockIQ("user@example.com", {"transcript_id": ""})
    result = _run(handler._cmd_use_transcript_submit(iq, {}))
    assert result["notes"][0][0] == "error"
    executor.execute_command_text.assert_not_called()


# ---------------------------------------------------------------------------
# _make_form
# ---------------------------------------------------------------------------


def test_make_form_returns_none_when_xep_0004_is_none():
    handler, _, _ = _make_handler()
    handler._xep_0004 = None
    result = handler._make_form("Title", [{"var": "x", "ftype": "text-single", "label": "X"}])
    assert result is None


def test_make_form_builds_form_with_options():
    handler, _, _ = _make_handler()
    handler._xep_0004 = _MockXep0004()
    form = handler._make_form(
        "Pick",
        [
            {
                "var": "choice",
                "ftype": "list-single",
                "label": "Choose",
                "options": [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}],
            }
        ],
    )
    assert isinstance(form, _MockXep0004Form)
    assert len(form.fields["choice"].options) == 2
