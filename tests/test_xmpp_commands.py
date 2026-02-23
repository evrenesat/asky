"""Daemon command executor tests."""

from types import SimpleNamespace
from unittest.mock import patch

from asky.daemon.command_executor import CommandExecutor


class _FakeTranscriptManager:
    def __init__(self):
        self.session_profile_manager = _FakeSessionProfileManager()
        self.records = {
            ("jid", 1): SimpleNamespace(
                session_transcript_id=1,
                status="completed",
                transcript_text="transcript text",
                used=False,
                audio_path="/tmp/a1.m4a",
            )
        }
        self.image_records = {
            ("jid", 1): SimpleNamespace(
                session_image_id=1,
                status="completed",
                transcript_text="image transcript text",
                used=False,
                image_path="/tmp/i1.jpg",
            )
        }
        self.used = []
        self.image_used = []

    def get_or_create_session_id(self, jid):
        return 1

    def list_for_jid(self, jid, limit=20):
        return [self.records[("jid", 1)]]

    def get_for_jid(self, jid, transcript_id):
        return self.records.get((jid, transcript_id))

    def mark_used(self, *, jid, transcript_id):
        self.used.append((jid, transcript_id))
        return self.records.get((jid, transcript_id))

    def clear_for_jid(self, jid):
        return list(self.records.values())

    def list_images_for_jid(self, jid, limit=20):
        _ = (jid, limit)
        return list(self.image_records.values())

    def get_image_for_jid(self, jid, image_id):
        return self.image_records.get((jid, image_id))

    def mark_image_used(self, *, jid, image_id):
        self.image_used.append((jid, image_id))
        return self.image_records.get((jid, image_id))


def _blocked_args():
    return SimpleNamespace(
        open=True,
        mail_recipients=None,
        terminal_lines=None,
        delete_messages=None,
        delete_sessions=None,
        all=False,
        clean_session_research=None,
        add_model=False,
        edit_model=None,
        clear_memories=False,
        delete_memory=None,
        xmpp_daemon=False,
        xmpp_menubar_child=False,
        edit_daemon=False,
        completion_script=None,
    )


class _FakeSessionProfileManager:
    def __init__(self):
        self.profile = SimpleNamespace(
            default_model="dummy-model",
            summarization_model="dummy-model",
            user_prompts={},
        )
        self.switch_calls = []
        self.new_calls = []
        self.apply_calls = []
        self._message_count = 5

    def resolve_conversation_session_id(self, *, room_jid, jid):
        _ = (room_jid, jid)
        return 1

    def get_effective_profile(self, *, session_id):
        _ = session_id
        return self.profile

    def list_recent_sessions(self, limit=20):
        _ = limit
        return [SimpleNamespace(id=1, name="session-one")]

    def create_new_conversation_session(self, *, room_jid, jid, inherit_current):
        self.new_calls.append((room_jid, jid, inherit_current))
        _ = (room_jid, jid, inherit_current)
        return 11

    def switch_conversation_session(self, *, room_jid, jid, selector):
        self.switch_calls.append((room_jid, jid, selector))
        _ = (room_jid, jid, selector)
        return 7, None

    def apply_override_file(self, *, session_id, filename, content):
        self.apply_calls.append((session_id, filename, content))
        _ = (session_id, content)
        return SimpleNamespace(
            filename=filename,
            saved=True,
            ignored_keys=(),
            applied_keys=("general.default_model",),
            error=None,
        )

    def count_session_messages(self, session_id: int) -> int:
        _ = session_id
        return self._message_count

    def clear_conversation(self, session_id: int) -> int:
        count = self._message_count
        self._message_count = 0
        return count


def _turn_result(final_answer: str = "ok"):
    return SimpleNamespace(
        halted=False,
        final_answer=final_answer,
        halt_reason=None,
        notices=[],
    )


def test_remote_policy_blocks_open_flag():
    executor = CommandExecutor(_FakeTranscriptManager())
    error = executor._validate_remote_policy(_blocked_args())
    assert error is not None
    assert "Remote policy blocked" in error


def test_transcript_list_show_and_clear():
    manager = _FakeTranscriptManager()
    executor = CommandExecutor(manager)

    listed = executor.execute_command_text(jid="jid", command_text="transcript list")
    assert "Transcripts:" in listed
    assert "#at1" in listed
    assert "#it1" in listed

    shown = executor.execute_command_text(jid="jid", command_text="transcript show 1")
    assert "Transcript #at1" in shown
    assert "transcript text" in shown

    cleared = executor.execute_command_text(jid="jid", command_text="transcript clear")
    assert "Deleted" in cleared


def test_execute_query_text_expands_aliases_before_model_call():
    manager = _FakeTranscriptManager()
    manager.session_profile_manager.profile.user_prompts = {"alias": "hello"}
    executor = CommandExecutor(manager)
    with (
        patch("asky.daemon.command_executor.AskyClient") as mock_client_cls,
        patch("asky.daemon.command_executor.utils.load_custom_prompts") as mock_load,
        patch(
            "asky.daemon.command_executor.utils.expand_query_text",
            return_value="expanded query",
        ) as mock_expand,
    ):
        mock_client = mock_client_cls.return_value
        mock_client.run_turn.return_value = _turn_result("expanded answer")
        response = executor.execute_query_text(jid="jid", query_text="ask /alias now")

    assert response == "expanded answer"
    mock_load.assert_called_once_with(prompt_map={"alias": "hello"})
    mock_expand.assert_called_once_with(
        "ask /alias now",
        verbose=False,
        prompt_map={"alias": "hello"},
    )
    request = mock_client.run_turn.call_args.args[0]
    assert request.query_text == "expanded query"


def test_execute_query_text_slash_only_lists_prompts():
    manager = _FakeTranscriptManager()
    manager.session_profile_manager.profile.user_prompts = {"known": "Known prompt"}
    executor = CommandExecutor(manager)
    with (
        patch(
            "asky.daemon.command_executor.utils.expand_query_text",
            return_value="/",
        ),
        patch("asky.daemon.command_executor.utils.load_custom_prompts"),
        patch("asky.daemon.command_executor.AskyClient") as mock_client_cls,
    ):
        response = executor.execute_query_text(jid="jid", query_text="/")

    assert "Prompt Aliases:" in response
    assert "/known:" in response
    mock_client_cls.assert_not_called()


def test_execute_query_text_unknown_slash_lists_filtered_prompts():
    manager = _FakeTranscriptManager()
    manager.session_profile_manager.profile.user_prompts = {"known": "Known"}
    executor = CommandExecutor(manager)
    with (
        patch(
            "asky.daemon.command_executor.utils.expand_query_text",
            return_value="/unknown rest",
        ),
        patch("asky.daemon.command_executor.utils.load_custom_prompts"),
        patch("asky.daemon.command_executor.AskyClient") as mock_client_cls,
    ):
        response = executor.execute_query_text(jid="jid", query_text="/unknown rest")

    assert "Prompt Aliases:" in response
    assert "/known:" in response
    mock_client_cls.assert_not_called()


def test_execute_command_text_query_uses_shared_preparation():
    manager = _FakeTranscriptManager()
    manager.session_profile_manager.profile.user_prompts = {"alias": "Hello"}
    executor = CommandExecutor(manager)
    with (
        patch("asky.daemon.command_executor.AskyClient") as mock_client_cls,
        patch("asky.daemon.command_executor.init_db"),
        patch("asky.daemon.command_executor.utils.load_custom_prompts") as mock_load,
        patch(
            "asky.daemon.command_executor.utils.expand_query_text",
            return_value="normalized query",
        ) as mock_expand,
    ):
        mock_client = mock_client_cls.return_value
        mock_client.run_turn.return_value = _turn_result("query answer")
        response = executor.execute_command_text(
            jid="jid",
            command_text="ask /alias from command",
        )

    assert response == "query answer"
    mock_load.assert_called_once_with(prompt_map={"alias": "Hello"})
    mock_expand.assert_called_once_with(
        "ask /alias from command",
        verbose=False,
        prompt_map={"alias": "Hello"},
    )
    request = mock_client.run_turn.call_args.args[0]
    assert request.query_text == "normalized query"


def test_transcript_use_path_inherits_query_alias_preparation():
    manager = _FakeTranscriptManager()
    manager.session_profile_manager.profile.user_prompts = {"alias": "Hello"}
    manager.records[("jid", 1)].transcript_text = "check /alias"
    executor = CommandExecutor(manager)
    with (
        patch("asky.daemon.command_executor.AskyClient") as mock_client_cls,
        patch("asky.daemon.command_executor.utils.load_custom_prompts") as mock_load,
        patch(
            "asky.daemon.command_executor.utils.expand_query_text",
            return_value="expanded transcript query",
        ) as mock_expand,
    ):
        mock_client = mock_client_cls.return_value
        mock_client.run_turn.return_value = _turn_result("transcript answer")
        response = executor.execute_command_text(
            jid="jid", command_text="transcript use 1"
        )

    assert response == "transcript answer"
    assert manager.used == [("jid", 1)]
    mock_load.assert_called_once_with(prompt_map={"alias": "Hello"})
    mock_expand.assert_called_once_with(
        "check /alias",
        verbose=False,
        prompt_map={"alias": "Hello"},
    )
    request = mock_client.run_turn.call_args.args[0]
    assert request.query_text == "expanded transcript query"


def test_query_pointer_resolution_for_audio_and_image():
    manager = _FakeTranscriptManager()
    executor = CommandExecutor(manager)
    with patch("asky.daemon.command_executor.AskyClient") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.run_turn.return_value = _turn_result("ok")
        response = executor.execute_query_text(
            jid="jid",
            query_text="compare #i1 with #a1 and #it1 plus #at1",
        )

    assert response == "ok"
    request = mock_client.run_turn.call_args.args[0]
    assert "/tmp/i1.jpg" in request.query_text
    assert "/tmp/a1.m4a" in request.query_text
    assert "image transcript text" in request.query_text
    assert "transcript text" in request.query_text
    assert manager.used == [("jid", 1)]
    assert manager.image_used == [("jid", 1)]


def test_transcript_use_accepts_prefixed_id():
    manager = _FakeTranscriptManager()
    executor = CommandExecutor(manager)
    with patch("asky.daemon.command_executor.AskyClient") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.run_turn.return_value = _turn_result("answer")
        response = executor.execute_command_text(
            jid="jid",
            command_text="transcript use #at1",
        )

    assert response == "answer"


def test_session_command_help_lists_recent_sessions():
    manager = _FakeTranscriptManager()
    executor = CommandExecutor(manager)
    output = executor.execute_session_command(
        jid="jid",
        room_jid=None,
        command_text="/session",
    )
    assert "Session commands:" in output
    assert "Latest 20 Sessions:" in output
    assert "1: session-one" in output


def test_session_command_switch_and_child():
    manager = _FakeTranscriptManager()
    executor = CommandExecutor(manager)

    switched = executor.execute_session_command(
        jid="jid",
        room_jid="room@conference.example.com",
        command_text="/session 7",
    )
    child = executor.execute_session_command(
        jid="jid",
        room_jid="room@conference.example.com",
        command_text="/session child",
    )
    assert switched == "Switched to session 7."
    assert child == "Switched to child session 11 (inherited overrides)."
    assert manager.session_profile_manager.switch_calls == [
        ("room@conference.example.com", "jid", "7")
    ]
    assert manager.session_profile_manager.new_calls == [
        ("room@conference.example.com", "jid", True)
    ]


def test_apply_inline_toml_if_present_uses_current_session():
    manager = _FakeTranscriptManager()
    executor = CommandExecutor(manager)
    response = executor.apply_inline_toml_if_present(
        jid="jid",
        room_jid="room@conference.example.com",
        body='general.toml\n```toml\n[general]\ndefault_model = "dummy-model"\n```',
    )
    assert "Applied general.toml override to session 1." in str(response)
    assert manager.session_profile_manager.apply_calls[0][1] == "general.toml"


def test_help_command_returns_help_text():
    executor = CommandExecutor(_FakeTranscriptManager())
    response = executor.execute_command_text(jid="jid", command_text="/h")
    assert "Session" in response
    assert "Transcript" in response
    assert "Asky Commands" in response
    assert "Prompt Aliases" in response
    assert "Command Presets" in response
    assert "Config Override" in response


def test_help_alias_returns_same_text():
    executor = CommandExecutor(_FakeTranscriptManager())
    h_response = executor.execute_command_text(jid="jid", command_text="/h")
    help_response = executor.execute_command_text(jid="jid", command_text="/help")
    assert h_response == help_response


def test_help_command_token_recognized_by_router():
    from asky.daemon.router import _looks_like_command

    assert _looks_like_command("/h") is True
    assert _looks_like_command("/help") is True
    assert _looks_like_command("/HELP") is True


def test_session_clear_returns_prompt_with_count():
    manager = _FakeTranscriptManager()
    manager.session_profile_manager._message_count = 8
    executor = CommandExecutor(manager)

    response = executor.execute_session_command(
        jid="user@example.com",
        room_jid=None,
        command_text="/session clear",
        conversation_key="user@example.com",
    )

    assert "8 message(s)" in response
    assert "yes" in response.lower()
    assert "transcripts" in response.lower()
    assert executor._pending_clear.get("user@example.com") == ("user@example.com", None)


def test_session_clear_empty_session_returns_no_prompt():
    manager = _FakeTranscriptManager()
    manager.session_profile_manager._message_count = 0
    executor = CommandExecutor(manager)

    response = executor.execute_session_command(
        jid="user@example.com",
        room_jid=None,
        command_text="/session clear",
        conversation_key="user@example.com",
    )

    assert "no messages" in response.lower()
    assert not executor._pending_clear


def test_confirm_session_clear_deletes_and_returns_count():
    manager = _FakeTranscriptManager()
    manager.session_profile_manager._message_count = 3
    executor = CommandExecutor(manager)
    executor._pending_clear["user@example.com"] = ("user@example.com", None)

    result = executor.confirm_session_clear(jid="user@example.com", room_jid=None)

    assert "Cleared 3 message(s)" in result
    assert manager.session_profile_manager._message_count == 0


def test_consume_pending_clear_without_consume_does_not_pop():
    manager = _FakeTranscriptManager()
    executor = CommandExecutor(manager)
    executor._pending_clear["key"] = ("jid", None)

    entry = executor.consume_pending_clear("key", consume=False)
    assert entry == ("jid", None)
    assert "key" in executor._pending_clear

    entry2 = executor.consume_pending_clear("key", consume=True)
    assert entry2 == ("jid", None)
    assert "key" not in executor._pending_clear
