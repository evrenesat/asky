"""Daemon command executor tests."""

from types import SimpleNamespace

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
