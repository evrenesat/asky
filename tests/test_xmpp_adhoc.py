"""Unit tests for XEP-0050 Ad-Hoc Command handlers."""

from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
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
        # Simulate real slixmpp behavior: .bare strips resource
        if "/" in jid:
            self.bare = jid.split("/")[0]
        else:
            self.bare = jid
        self._full_jid = jid

    def __str__(self):
        return self._full_jid


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
    query_dispatch_callback = Mock()

    handler = AdHocCommandHandler(
        command_executor=executor,
        router=router,
        voice_enabled=voice_enabled,
        image_enabled=image_enabled,
        query_dispatch_callback=query_dispatch_callback,
    )
    handler._query_dispatch_callback_test = query_dispatch_callback
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
    assert "Voice transcription" in text
    assert "enabled" in text
    assert "Image transcription" in text
    assert "disabled" in text


def test_status_includes_connected_jid():
    handler, _, _ = _make_handler()
    result = _run(handler._cmd_status(_MockIQ("user@example.com"), {}))
    assert "Connected JID" in result["notes"][0][1]
    assert "asky Status" in result["notes"][0][1]


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


def test_list_prompts_no_prompts_returns_text():
    handler, _, _ = _make_handler()
    handler._xep_0004 = _MockXep0004()
    with patch("asky.config.USER_PROMPTS", {}):
        result = _run(handler._cmd_list_prompts(_MockIQ("user@example.com"), {}))
    assert result["has_next"] is False
    assert "No prompt aliases" in result["notes"][0][1]


def test_list_prompts_step1_returns_form_with_options():
    handler, _, _ = _make_handler()
    handler._xep_0004 = _MockXep0004()
    prompts = {"greet": "Say hello to $*", "recap": "Summarize the following"}
    with patch("asky.config.USER_PROMPTS", prompts):
        result = _run(handler._cmd_list_prompts(_MockIQ("user@example.com"), {}))
    assert result["has_next"] is True
    assert result["next"] == handler._cmd_list_prompts_submit
    form = result["payload"]
    assert isinstance(form, _MockXep0004Form)
    # Both prompt and query fields present
    assert "prompt" in form.fields
    assert "query" in form.fields
    options = form.fields["prompt"].options
    aliases = {o["value"] for o in options}
    assert "greet" in aliases
    assert "recap" in aliases


def test_list_prompts_step1_no_form_when_no_xep_0004():
    handler, _, _ = _make_handler()
    handler._xep_0004 = None
    prompts = {"greet": "Say hello"}
    with patch("asky.config.USER_PROMPTS", prompts):
        result = _run(handler._cmd_list_prompts(_MockIQ("user@example.com"), {}))
    assert result["has_next"] is False
    assert result["notes"][0][0] == "error"


def test_list_prompts_submit_executes_alias_without_query():
    handler, executor, _ = _make_handler()
    iq = _MockIQ("user@example.com", {"prompt": "greet", "query": ""})
    result = _run(handler._cmd_list_prompts_submit(iq, {}))
    executor.execute_query_text.assert_not_called()
    handler._query_dispatch_callback_test.assert_called_once_with(
        jid="user@example.com",
        room_jid=None,
        query_text="/greet",
        command_text=None,
    )
    assert "Response will be sent to chat." in result["notes"][0][1]


def test_list_prompts_submit_appends_query_text():
    handler, executor, _ = _make_handler()
    iq = _MockIQ("user@example.com", {"prompt": "recap", "query": "the meeting notes"})
    _run(handler._cmd_list_prompts_submit(iq, {}))
    call_kwargs = handler._query_dispatch_callback_test.call_args.kwargs
    assert call_kwargs["query_text"] == "/recap the meeting notes"


def test_list_prompts_submit_error_when_no_alias():
    handler, executor, _ = _make_handler()
    iq = _MockIQ("user@example.com", {"prompt": "", "query": "hello"})
    result = _run(handler._cmd_list_prompts_submit(iq, {}))
    assert result["notes"][0][0] == "error"
    executor.execute_query_text.assert_not_called()
    handler._query_dispatch_callback_test.assert_not_called()


def test_list_presets_no_presets_returns_text():
    handler, _, _ = _make_handler()
    handler._xep_0004 = _MockXep0004()
    with patch("asky.config.COMMAND_PRESETS", {}):
        result = _run(handler._cmd_list_presets(_MockIQ("user@example.com"), {}))
    assert result["has_next"] is False
    assert "No command presets" in result["notes"][0][1]


def test_list_presets_step1_returns_form_with_options():
    handler, _, _ = _make_handler()
    handler._xep_0004 = _MockXep0004()
    presets = {"search": "websearch $*", "fix": "fix the following code: $*"}
    with patch("asky.config.COMMAND_PRESETS", presets):
        result = _run(handler._cmd_list_presets(_MockIQ("user@example.com"), {}))
    assert result["has_next"] is True
    assert result["next"] == handler._cmd_list_presets_submit
    form = result["payload"]
    assert isinstance(form, _MockXep0004Form)
    assert "preset" in form.fields
    assert "args" in form.fields
    options = form.fields["preset"].options
    names = {o["value"] for o in options}
    assert "search" in names
    assert "fix" in names


def test_list_presets_step1_no_form_when_no_xep_0004():
    handler, _, _ = _make_handler()
    handler._xep_0004 = None
    presets = {"search": "websearch $*"}
    with patch("asky.config.COMMAND_PRESETS", presets):
        result = _run(handler._cmd_list_presets(_MockIQ("user@example.com"), {}))
    assert result["has_next"] is False
    assert result["notes"][0][0] == "error"


def test_list_presets_submit_expands_and_executes():
    handler, executor, _ = _make_handler()
    executor.command_executes_lm_query.return_value = False
    executor.execute_command_text.return_value = "preset output"
    iq = _MockIQ("user@example.com", {"preset": "search", "args": "python asyncio"})
    presets = {"search": "websearch $*"}
    # Patch the reference used inside expand_preset_invocation at runtime
    with patch("asky.config.COMMAND_PRESETS", presets):
        result = _run(handler._cmd_list_presets_submit(iq, {}))
    executor.execute_command_text.assert_called_once()
    assert result["notes"][0][1] == "preset output"


def test_list_presets_submit_without_args():
    handler, executor, _ = _make_handler()
    executor.command_executes_lm_query.return_value = False
    executor.execute_command_text.return_value = "ok"
    iq = _MockIQ("user@example.com", {"preset": "fix", "args": ""})
    presets = {"fix": "fix the following code"}
    with patch("asky.config.COMMAND_PRESETS", presets):
        result = _run(handler._cmd_list_presets_submit(iq, {}))
    executor.execute_command_text.assert_called_once()
    assert result["has_next"] is False


def test_list_presets_submit_error_when_no_preset():
    handler, executor, _ = _make_handler()
    iq = _MockIQ("user@example.com", {"preset": "", "args": ""})
    result = _run(handler._cmd_list_presets_submit(iq, {}))
    assert result["notes"][0][0] == "error"
    executor.execute_command_text.assert_not_called()


def test_list_presets_submit_error_on_unknown_preset():
    handler, executor, _ = _make_handler()
    iq = _MockIQ("user@example.com", {"preset": "unknown_preset", "args": ""})
    with patch("asky.config.COMMAND_PRESETS", {}):
        result = _run(handler._cmd_list_presets_submit(iq, {}))
    assert "Error" in result["notes"][0][1]
    executor.execute_command_text.assert_not_called()


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
    executor.execute_command_text.assert_not_called()
    handler._query_dispatch_callback_test.assert_called_once()
    cmd = handler._query_dispatch_callback_test.call_args.kwargs["command_text"]
    assert "What is Python?" in cmd
    assert result["has_next"] is False


def test_query_submit_includes_research_flag_when_enabled():
    handler, executor, _ = _make_handler()
    iq = _MockIQ("user@example.com", {"query": "deep topic", "research": "true"})
    _run(handler._cmd_query_submit(iq, {}))
    cmd = handler._query_dispatch_callback_test.call_args.kwargs["command_text"]
    assert "-r" in cmd


def test_query_submit_includes_model_and_turns():
    handler, executor, _ = _make_handler()
    iq = _MockIQ("user@example.com", {"query": "hello", "model": "opus", "turns": "5"})
    _run(handler._cmd_query_submit(iq, {}))
    cmd = handler._query_dispatch_callback_test.call_args.kwargs["command_text"]
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
    handler._query_dispatch_callback_test.assert_not_called()


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
    iq = _MockIQ("user@example.com", {"transcript_id": "3"})
    result = _run(handler._cmd_use_transcript_submit(iq, {}))
    cmd = handler._query_dispatch_callback_test.call_args.kwargs["command_text"]
    assert "transcript use #at3" in cmd
    assert "Response will be sent to chat." in result["notes"][0][1]


def test_use_transcript_submit_error_on_empty_id():
    handler, executor, _ = _make_handler()
    iq = _MockIQ("user@example.com", {"transcript_id": ""})
    result = _run(handler._cmd_use_transcript_submit(iq, {}))
    assert result["notes"][0][0] == "error"
    executor.execute_command_text.assert_not_called()
    handler._query_dispatch_callback_test.assert_not_called()


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


# ---------------------------------------------------------------------------
# Bug Condition Exploration - Property-Based Tests
# ---------------------------------------------------------------------------


from hypothesis import given, strategies as st, example


class _MockJIDWithoutBare:
    """Mock JID object that lacks the .bare attribute."""
    def __init__(self, jid: str):
        self._jid = jid

    def __str__(self):
        return self._jid


class _MockJIDWithEmptyBare:
    """Mock JID object where .bare returns empty string."""
    def __init__(self, jid: str):
        self._jid = jid
        self.bare = ""

    def __str__(self):
        return self._jid


class _MockIQWithNoneFrom:
    """Mock IQ where iq['from'] is None."""
    def __getitem__(self, key):
        if key == "from":
            return None
        raise KeyError(key)


class _MockIQWithMissingBare:
    """Mock IQ where iq['from'] lacks .bare attribute."""
    def __init__(self, jid: str):
        self._jid = jid

    def __getitem__(self, key):
        if key == "from":
            return _MockJIDWithoutBare(self._jid)
        raise KeyError(key)


class _MockIQWithEmptyBare:
    """Mock IQ where iq['from'].bare returns empty string."""
    def __init__(self, jid: str):
        self._jid = jid

    def __getitem__(self, key):
        if key == "from":
            return _MockJIDWithEmptyBare(self._jid)
        raise KeyError(key)


def _build_iq_xml(from_jid: str, form_values: dict | None = None):
    iq = ET.Element("iq", attrib={"from": from_jid})
    command = ET.SubElement(iq, "{http://jabber.org/protocol/commands}command")
    if form_values:
        form = ET.SubElement(command, "{jabber:x:data}x", attrib={"type": "submit"})
        for var_name, value in form_values.items():
            field = ET.SubElement(form, "{jabber:x:data}field", attrib={"var": var_name})
            value_node = ET.SubElement(field, "{jabber:x:data}value")
            value_node.text = str(value)
    return iq


class _MockIQXmlOnly:
    """Mock IQ where stanza interfaces are unavailable but raw XML exists."""

    def __init__(self, from_jid: str, form_values: dict | None = None):
        self.interfaces: set[str] = set()
        self.xml = _build_iq_xml(from_jid, form_values=form_values)

    def __getitem__(self, key):
        raise KeyError(key)


class _MockIQMissingFromWithForm:
    """Mock IQ missing 'from' field but still carrying form submission values."""

    def __init__(self, form_values: dict):
        self._form_values = form_values

    def __getitem__(self, key):
        if key == "from":
            raise KeyError(key)
        if key == "command":
            return _MockCommand(self._form_values)
        raise KeyError(key)


@given(jid=st.from_regex(r"^[a-z]+@[a-z]+\.[a-z]+$", fullmatch=True))
@example(jid="alice@example.com")
@example(jid="bob@test.org")
def test_bug_condition_sender_jid_returns_empty_when_bare_missing(jid):
    """
    **Validates: Requirements 1.1, 1.2**
    
    Property 1: Fault Condition - JID Extraction Failure for Authorized Users
    
    EXPECTED OUTCOME: This test FAILS on unfixed code (proving bug exists).
    
    For IQ stanzas where iq["from"] lacks .bare attribute, _sender_jid() 
    should extract JID using fallback methods, but currently returns empty string.
    """
    handler, _, _ = _make_handler(authorized=True)
    iq = _MockIQWithMissingBare(jid)
    
    sender = handler._sender_jid(iq)
    
    # Expected behavior: should extract JID using fallback (str(from_field).split("/")[0])
    # Current buggy behavior: returns empty string because AttributeError is caught
    assert sender != "", f"Expected JID extraction to succeed for {jid}, but got empty string"
    assert sender == jid, f"Expected {jid}, got {sender}"


@given(jid=st.from_regex(r"^[a-z]+@[a-z]+\.[a-z]+$", fullmatch=True))
@example(jid="charlie@example.net")
@example(jid="dave@test.com")
def test_bug_condition_sender_jid_returns_empty_when_bare_is_empty_string(jid):
    """
    **Validates: Requirements 1.1, 1.2**
    
    Property 1: Fault Condition - JID Extraction Failure for Authorized Users
    
    EXPECTED OUTCOME: This test FAILS on unfixed code (proving bug exists).
    
    For IQ stanzas where iq["from"].bare exists but returns empty string,
    _sender_jid() should use fallback methods, but currently returns empty string.
    """
    handler, _, _ = _make_handler(authorized=True)
    iq = _MockIQWithEmptyBare(jid)
    
    sender = handler._sender_jid(iq)
    
    # Expected behavior: should detect empty string and use fallback
    # Current buggy behavior: returns empty string because no check for empty .bare
    assert sender != "", f"Expected JID extraction to succeed for {jid}, but got empty string"
    assert sender == jid, f"Expected {jid}, got {sender}"


def test_bug_condition_sender_jid_returns_empty_when_from_is_none():
    """
    **Validates: Requirements 1.2**
    
    Property 1: Fault Condition - JID Extraction Failure for Authorized Users
    
    EXPECTED OUTCOME: This test verifies robust null handling.

    For IQ stanzas where iq["from"] is None, _sender_jid() should return
    empty string.
    """
    handler, _, _ = _make_handler(authorized=True)
    iq = _MockIQWithNoneFrom()

    sender = handler._sender_jid(iq)

    assert sender == ""


@given(jid=st.from_regex(r"^[a-z]+@[a-z]+\.[a-z]+$", fullmatch=True))
@example(jid="alice@example.com")
@example(jid="bob@test.org")
def test_bug_condition_authorization_fails_for_allowlisted_users_when_jid_extraction_fails(jid):
    """
    **Validates: Requirements 1.1, 2.1**
    
    Property 1: Fault Condition - JID Extraction Failure for Authorized Users
    
    EXPECTED OUTCOME: This test FAILS on unfixed code (proving bug exists).
    
    When _sender_jid() fails to extract JID (returns empty string), 
    _is_authorized() returns False even for users in the allowlist.
    This is the core bug: authorized users get "Not authorized" errors.
    """
    handler, _, router = _make_handler(authorized=True)
    
    # Simulate allowlist containing this JID
    router.is_authorized.return_value = True
    
    # Use IQ with missing .bare attribute (triggers bug)
    iq = _MockIQWithMissingBare(jid)
    
    is_auth = handler._is_authorized(iq)
    
    # Expected behavior: should return True (user is in allowlist)
    # Current buggy behavior: returns False because _sender_jid() returns empty string
    assert is_auth is True, f"Expected authorization to succeed for allowlisted user {jid}, but got False"
    
    # Verify that if JID extraction worked, router.is_authorized would be called with correct JID
    # In the fixed version, this should be called with the extracted JID
    # In the buggy version, it's called with empty string, so is_authorized returns False


# ---------------------------------------------------------------------------
# Preservation Property Tests - Authorization Logic Unchanged
# ---------------------------------------------------------------------------


@given(jid=st.from_regex(r"^[a-z]+@[a-z]+\.[a-z]+(/[a-z0-9]+)?$", fullmatch=True))
@example(jid="alice@example.com")
@example(jid="bob@test.org/mobile")
@example(jid="charlie@example.net")
def test_preservation_authorized_users_with_valid_bare_extraction(jid):
    """
    **Validates: Requirements 3.2, 3.5**
    
    Property 2: Preservation - Authorization Logic Unchanged for Valid JID Extraction
    
    EXPECTED OUTCOME: This test PASSES on unfixed code (confirms baseline behavior).
    
    For IQ stanzas where iq["from"].bare works correctly, authorized users
    should continue to be authorized after the fix.
    """
    handler, _, router = _make_handler(authorized=True)
    
    # Mock router to simulate this JID is in the allowlist
    router.is_authorized.return_value = True
    
    # Use normal IQ with working .bare attribute
    iq = _MockIQ(jid)
    
    # Extract JID and verify it works
    sender = handler._sender_jid(iq)
    assert sender != "", f"JID extraction should succeed for {jid}"
    
    # Verify authorization succeeds
    is_auth = handler._is_authorized(iq)
    assert is_auth is True, f"Authorized user {jid} should be authorized"
    
    # Verify router.is_authorized was called with the extracted JID
    router.is_authorized.assert_called()


@given(jid=st.from_regex(r"^[a-z]+@[a-z]+\.[a-z]+(/[a-z0-9]+)?$", fullmatch=True))
@example(jid="evil@example.com")
@example(jid="unauthorized@test.org/desktop")
def test_preservation_unauthorized_users_rejected(jid):
    """
    **Validates: Requirements 3.1**
    
    Property 2: Preservation - Authorization Logic Unchanged for Valid JID Extraction
    
    EXPECTED OUTCOME: This test PASSES on unfixed code (confirms baseline behavior).
    
    Users not in the allowlist should continue to be rejected after the fix.
    """
    handler, _, router = _make_handler(authorized=False)
    
    # Mock router to simulate this JID is NOT in the allowlist
    router.is_authorized.return_value = False
    
    # Use normal IQ with working .bare attribute
    iq = _MockIQ(jid)
    
    # Verify authorization fails
    is_auth = handler._is_authorized(iq)
    assert is_auth is False, f"Unauthorized user {jid} should be rejected"


@given(
    bare_jid=st.from_regex(r"^[a-z]+@[a-z]+\.[a-z]+$", fullmatch=True),
    resource=st.from_regex(r"^[a-z0-9]+$", fullmatch=True),
)
@example(bare_jid="alice@example.com", resource="mobile")
@example(bare_jid="bob@test.org", resource="desktop")
def test_preservation_bare_jid_matching_any_resource(bare_jid, resource):
    """
    **Validates: Requirements 3.3**
    
    Property 2: Preservation - Authorization Logic Unchanged for Valid JID Extraction
    
    EXPECTED OUTCOME: This test PASSES on unfixed code (confirms baseline behavior).
    
    When the allowlist contains bare JIDs (user@domain), the system should
    continue to match incoming requests from any resource (user@domain/resource1,
    user@domain/resource2) after the fix.
    """
    handler, _, router = _make_handler(authorized=True)
    
    # Create full JID with resource
    full_jid = f"{bare_jid}/{resource}"
    
    # Mock router to simulate bare JID matching logic
    # The router should authorize any resource for a bare JID in allowlist
    def mock_is_authorized(jid_to_check):
        # Simulate bare JID matching: strip resource and check
        bare = jid_to_check.split("/")[0] if "/" in jid_to_check else jid_to_check
        return bare == bare_jid
    
    router.is_authorized.side_effect = mock_is_authorized
    
    # Use IQ with full JID (bare + resource)
    iq = _MockIQ(full_jid)
    
    # Extract JID - should get bare JID
    sender = handler._sender_jid(iq)
    assert sender == bare_jid, f"Expected bare JID {bare_jid}, got {sender}"
    
    # Verify authorization succeeds (bare JID matches)
    is_auth = handler._is_authorized(iq)
    assert is_auth is True, f"Bare JID {bare_jid} in allowlist should match full JID {full_jid}"


@given(
    bare_jid=st.from_regex(r"^[a-z]+@[a-z]+\.[a-z]+$", fullmatch=True),
    allowed_resource=st.from_regex(r"^[a-z0-9]+$", fullmatch=True),
    other_resource=st.from_regex(r"^[a-z0-9]+$", fullmatch=True),
)
@example(bare_jid="alice@example.com", allowed_resource="work", other_resource="home")
@example(bare_jid="bob@test.org", allowed_resource="desktop", other_resource="mobile")
def test_preservation_full_jid_matching_specific_resource(bare_jid, allowed_resource, other_resource):
    """
    **Validates: Requirements 3.4**
    
    Property 2: Preservation - Authorization Logic Unchanged for Valid JID Extraction
    
    EXPECTED OUTCOME: This test PASSES on unfixed code (confirms baseline behavior).
    
    When the allowlist contains full JIDs (user@domain/resource), the system
    should continue to match incoming requests only from that specific resource
    after the fix.
    
    NOTE: The current implementation of _sender_jid() always extracts bare JID,
    so full JID matching through ad-hoc commands requires the bare JID to also
    be in the allowlist. This test verifies that behavior is preserved.
    """
    # Skip if resources are the same (we want to test different resources)
    if allowed_resource == other_resource:
        return
    
    handler, _, router = _make_handler(authorized=True)
    
    # Create full JIDs
    allowed_full_jid = f"{bare_jid}/{allowed_resource}"
    other_full_jid = f"{bare_jid}/{other_resource}"
    
    # Mock router to simulate the actual DaemonRouter.is_authorized() logic:
    # - Check if the JID (as passed) is in allowed_full_jids
    # - Then check if the bare JID is in allowed_bare_jids
    # Since _sender_jid() always returns bare JID, we need bare JID in allowlist
    def mock_is_authorized(jid_to_check):
        # Simulate DaemonRouter.is_authorized() logic
        # First check full JID match
        if jid_to_check == allowed_full_jid:
            return True
        # Then check bare JID match
        bare = jid_to_check.split("/")[0] if "/" in jid_to_check else jid_to_check
        # For this test, we're simulating that ONLY the bare JID is in allowed_bare_jids
        # (not the full JID), so any resource from that bare JID is authorized
        return bare == bare_jid
    
    router.is_authorized.side_effect = mock_is_authorized
    
    # Test: Both resources should be authorized because _sender_jid() returns bare JID
    # and the bare JID is in the allowlist
    iq_allowed = _MockIQ(allowed_full_jid)
    sender_allowed = handler._sender_jid(iq_allowed)
    assert sender_allowed == bare_jid, f"Expected bare JID {bare_jid}, got {sender_allowed}"
    
    is_auth_allowed = handler._is_authorized(iq_allowed)
    assert is_auth_allowed is True, f"Bare JID {bare_jid} should be authorized"
    
    # Other resource should also be authorized (same bare JID)
    iq_other = _MockIQ(other_full_jid)
    sender_other = handler._sender_jid(iq_other)
    assert sender_other == bare_jid, f"Expected bare JID {bare_jid}, got {sender_other}"
    
    is_auth_other = handler._is_authorized(iq_other)
    assert is_auth_other is True, f"Bare JID {bare_jid} should be authorized for any resource"


def test_authorization_uses_full_jid_for_strict_allowlist():
    handler, _, router = _make_handler(authorized=False)
    allowlisted = "u@example.com/work"
    router.is_authorized.side_effect = lambda jid_to_check: jid_to_check == allowlisted

    authorized = handler._is_authorized(_MockIQ("u@example.com/work"))
    rejected = handler._is_authorized(_MockIQ("u@example.com/mobile"))

    assert authorized is True
    assert rejected is False


def test_multistep_submit_authorizes_with_session_stored_sender():
    handler, executor, router = _make_handler(authorized=False)
    handler._xep_0004 = _MockXep0004()

    allowlisted = "u@example.com/work"
    router.is_authorized.side_effect = lambda jid_to_check: jid_to_check == allowlisted

    session: dict = {}
    with patch("asky.config.USER_PROMPTS", {"greet": "Say hello"}):
        step1 = _run(handler._cmd_list_prompts(_MockIQ(allowlisted), session))
    assert step1["has_next"] is True
    assert session.get("_authorized_full_jid") == allowlisted
    assert session.get("_authorized_bare_jid") == "u@example.com"

    submit_iq = _MockIQMissingFromWithForm({"prompt": "greet", "query": "there"})
    result = _run(handler._cmd_list_prompts_submit(submit_iq, session))

    assert result["notes"][0][0] == "info"
    handler._query_dispatch_callback_test.assert_called_once_with(
        jid="u@example.com",
        room_jid=None,
        query_text="/greet there",
        command_text=None,
    )


def test_sender_resolution_uses_raw_xml_from_attr_when_interface_missing():
    handler, _, _ = _make_handler()
    iq = _MockIQXmlOnly("u@example.com/work")

    assert handler._sender_full_jid(iq) == "u@example.com/work"
    assert handler._sender_jid(iq) == "u@example.com"


def test_form_values_uses_raw_xml_when_command_interface_missing():
    handler, _, _ = _make_handler()
    iq = _MockIQXmlOnly(
        "u@example.com/work",
        form_values={"prompt": "greet", "query": "there"},
    )

    values = handler._form_values(iq)
    assert values["prompt"] == "greet"
    assert values["query"] == "there"


def test_list_prompts_submit_handles_xml_only_command_next_iq():
    handler, executor, _ = _make_handler()
    iq = _MockIQXmlOnly(
        "user@example.com/resource",
        form_values={"prompt": "greet", "query": "xml fallback"},
    )

    result = _run(handler._cmd_list_prompts_submit(iq, {}))

    executor.execute_query_text.assert_not_called()
    handler._query_dispatch_callback_test.assert_called_once_with(
        jid="user@example.com",
        room_jid=None,
        query_text="/greet xml fallback",
        command_text=None,
    )
    assert "Response will be sent to chat." in result["notes"][0][1]
