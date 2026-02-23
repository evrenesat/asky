"""Router behavior tests for daemon mode."""

from types import SimpleNamespace

from asky.daemon.interface_planner import InterfaceAction
from asky.daemon.router import DaemonRouter


class _FakeTranscriptManager:
    def __init__(self):
        self.mark_used_calls = []
        self.records = {}

    def create_pending_transcript(self, *, jid, audio_url, audio_path):
        rec = SimpleNamespace(session_transcript_id=1)
        self.records[(jid, 1)] = SimpleNamespace(
            session_transcript_id=1,
            status="completed",
            transcript_text="hello transcript",
            used=False,
            audio_path=audio_path,
            audio_url=audio_url,
        )
        return rec

    def mark_transcript_completed(self, *, jid, transcript_id, transcript_text, duration_seconds):
        rec = self.records[(jid, transcript_id)]
        rec.transcript_text = transcript_text
        rec.status = "completed"
        return rec

    def mark_transcript_failed(self, *, jid, transcript_id, error):
        return None

    def list_for_jid(self, jid, limit=20):
        return []

    def get_for_jid(self, jid, transcript_id):
        return self.records.get((jid, transcript_id))

    def mark_used(self, *, jid, transcript_id):
        self.mark_used_calls.append((jid, transcript_id))
        rec = self.records.get((jid, transcript_id))
        if rec is not None:
            rec.used = True
        return rec

    def clear_for_jid(self, jid):
        return []


class _FakeCommandExecutor:
    def __init__(self):
        self.command_calls = []
        self.query_calls = []

    def execute_command_text(self, *, jid, command_text):
        self.command_calls.append((jid, command_text))
        return f"command:{command_text}"

    def execute_query_text(self, *, jid, query_text):
        self.query_calls.append((jid, query_text))
        return f"query:{query_text}"


class _FakePlanner:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.actions = []

    def plan(self, text):
        self.actions.append(text)
        return InterfaceAction(action_type="query", query_text=f"planned:{text}")


class _FakeVoiceTranscriber:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.jobs = []

    def enqueue(self, job):
        self.jobs.append(job)


def _build_router(interface_enabled=True, auto_yes_without_interface=True):
    return DaemonRouter(
        transcript_manager=_FakeTranscriptManager(),
        command_executor=_FakeCommandExecutor(),
        interface_planner=_FakePlanner(enabled=interface_enabled),
        voice_transcriber=_FakeVoiceTranscriber(enabled=True),
        command_prefix="/asky",
        allowed_jids=["u@example.com/resource"],
        voice_auto_yes_without_interface_model=auto_yes_without_interface,
    )


def test_router_silent_drop_for_unauthorized():
    router = _build_router()
    response = router.handle_text_message(
        jid="other@example.com/resource",
        message_type="chat",
        body="hello",
    )
    assert response is None


def test_router_bare_jid_allowlist_matches_any_resource():
    router = DaemonRouter(
        transcript_manager=_FakeTranscriptManager(),
        command_executor=_FakeCommandExecutor(),
        interface_planner=_FakePlanner(enabled=True),
        voice_transcriber=_FakeVoiceTranscriber(enabled=True),
        command_prefix="/asky",
        allowed_jids=["u@example.com"],
    )
    response = router.handle_text_message(
        jid="u@example.com/mobile-resource",
        message_type="chat",
        body="/asky --history 1",
    )
    assert response == "command:--history 1"


def test_router_full_jid_allowlist_remains_strict():
    router = _build_router(interface_enabled=True)
    response = router.handle_text_message(
        jid="u@example.com/other-resource",
        message_type="chat",
        body="/asky --history 5",
    )
    assert response is None


def test_router_prefixed_command_with_interface_enabled():
    router = _build_router(interface_enabled=True)
    response = router.handle_text_message(
        jid="u@example.com/resource",
        message_type="chat",
        body="/asky --history 5",
    )
    assert response == "command:--history 5"


def test_router_query_without_interface_model_command_detection():
    router = _build_router(interface_enabled=False)
    response = router.handle_text_message(
        jid="u@example.com/resource",
        message_type="chat",
        body="what is new",
    )
    assert response == "query:what is new"


def test_router_preset_listing():
    router = _build_router()
    response = router.handle_text_message(
        jid="u@example.com/resource",
        message_type="chat",
        body=r"\presets",
    )
    assert response is not None
    assert "Command Presets" in response or "No command presets" in response


def test_router_audio_queues_background_transcription():
    router = _build_router()
    response = router.handle_audio_message(
        jid="u@example.com/resource",
        message_type="chat",
        audio_url="https://example.com/audio.m4a",
    )
    assert "Queued transcription job" in str(response)


def test_router_transcript_ready_message_clarifies_yes_no_action():
    router = _build_router()
    router.handle_audio_message(
        jid="u@example.com/resource",
        message_type="chat",
        audio_url="https://example.com/audio.m4a",
    )
    result = router.handle_transcription_result(
        {
            "jid": "u@example.com/resource",
            "transcript_id": 1,
            "status": "completed",
            "transcript_text": "hello transcript",
            "duration_seconds": 1.2,
        }
    )
    assert result is not None
    _jid, message = result
    assert "Reply 'yes' to run transcript #1 as a query now." in message
    assert "Reply 'no' to keep it for later." in message


def test_router_auto_runs_transcript_when_interface_model_disabled():
    router = _build_router(interface_enabled=False, auto_yes_without_interface=True)
    router.handle_audio_message(
        jid="u@example.com/resource",
        message_type="chat",
        audio_url="https://example.com/audio.m4a",
    )
    result = router.handle_transcription_result(
        {
            "jid": "u@example.com/resource",
            "transcript_id": 1,
            "status": "completed",
            "transcript_text": "how is weather in rijswijk today",
            "duration_seconds": 1.1,
        }
    )
    assert result == ("u@example.com/resource", "query:how is weather in rijswijk today")


def test_router_auto_run_can_be_disabled_explicitly():
    router = _build_router(interface_enabled=False, auto_yes_without_interface=False)
    router.handle_audio_message(
        jid="u@example.com/resource",
        message_type="chat",
        audio_url="https://example.com/audio.m4a",
    )
    result = router.handle_transcription_result(
        {
            "jid": "u@example.com/resource",
            "transcript_id": 1,
            "status": "completed",
            "transcript_text": "how is weather in rijswijk today",
            "duration_seconds": 1.1,
        }
    )
    assert result is not None
    _jid, message = result
    assert "Reply 'yes' to run transcript #1 as a query now." in message
