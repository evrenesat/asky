"""Daemon command executor tests."""

from types import SimpleNamespace
from unittest.mock import patch

import asky.daemon.command_executor as command_executor
from asky.daemon.command_executor import CommandExecutor


class _FakeTranscriptManager:
    def __init__(self):
        self.records = {
            ("jid", 1): SimpleNamespace(
                session_transcript_id=1,
                status="completed",
                transcript_text="transcript text",
                used=False,
            )
        }
        self.used = []

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
        completion_script=None,
    )


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

    shown = executor.execute_command_text(jid="jid", command_text="transcript show 1")
    assert "Transcript 1" in shown
    assert "transcript text" in shown

    cleared = executor.execute_command_text(jid="jid", command_text="transcript clear")
    assert "Deleted" in cleared


def test_execute_query_text_expands_aliases_before_model_call():
    executor = CommandExecutor(_FakeTranscriptManager())
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
    mock_load.assert_called_once()
    mock_expand.assert_called_once_with("ask /alias now", verbose=False)
    request = mock_client.run_turn.call_args.args[0]
    assert request.query_text == "expanded query"


def test_execute_query_text_slash_only_lists_prompts():
    executor = CommandExecutor(_FakeTranscriptManager())
    with (
        patch(
            "asky.daemon.command_executor.utils.expand_query_text",
            return_value="/",
        ),
        patch("asky.daemon.command_executor.utils.load_custom_prompts"),
        patch(
            "asky.daemon.command_executor._capture_output",
            return_value="prompt list",
        ) as mock_capture,
        patch("asky.daemon.command_executor.AskyClient") as mock_client_cls,
    ):
        response = executor.execute_query_text(jid="jid", query_text="/")

    assert response == "prompt list"
    mock_client_cls.assert_not_called()
    assert mock_capture.call_count == 1
    assert mock_capture.call_args.args[0] == command_executor.prompts.list_prompts_command
    assert mock_capture.call_args.kwargs == {}


def test_execute_query_text_unknown_slash_lists_filtered_prompts():
    executor = CommandExecutor(_FakeTranscriptManager())
    with (
        patch.dict(command_executor.USER_PROMPTS, {"known": "Known"}, clear=True),
        patch(
            "asky.daemon.command_executor.utils.expand_query_text",
            return_value="/unknown rest",
        ),
        patch("asky.daemon.command_executor.utils.load_custom_prompts"),
        patch(
            "asky.daemon.command_executor._capture_output",
            return_value="filtered prompt list",
        ) as mock_capture,
        patch("asky.daemon.command_executor.AskyClient") as mock_client_cls,
    ):
        response = executor.execute_query_text(jid="jid", query_text="/unknown rest")

    assert response == "filtered prompt list"
    mock_client_cls.assert_not_called()
    assert mock_capture.call_count == 1
    assert mock_capture.call_args.args[0] == command_executor.prompts.list_prompts_command
    assert mock_capture.call_args.kwargs == {"filter_prefix": "unknown"}


def test_execute_command_text_query_uses_shared_preparation():
    executor = CommandExecutor(_FakeTranscriptManager())
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
    mock_load.assert_called_once()
    mock_expand.assert_called_once_with("ask /alias from command", verbose=False)
    request = mock_client.run_turn.call_args.args[0]
    assert request.query_text == "normalized query"


def test_transcript_use_path_inherits_query_alias_preparation():
    manager = _FakeTranscriptManager()
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
        response = executor.execute_command_text(jid="jid", command_text="transcript use 1")

    assert response == "transcript answer"
    assert manager.used == [("jid", 1)]
    mock_load.assert_called_once()
    mock_expand.assert_called_once_with("check /alias", verbose=False)
    request = mock_client.run_turn.call_args.args[0]
    assert request.query_text == "expanded transcript query"
