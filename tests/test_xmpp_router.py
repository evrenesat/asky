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

    def mark_transcript_completed(
        self, *, jid, transcript_id, transcript_text, duration_seconds
    ):
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

    def create_pending_image_transcript(self, *, jid, image_url, image_path):
        rec = SimpleNamespace(session_image_id=1)
        self.records[(jid, "i", 1)] = SimpleNamespace(
            session_image_id=1,
            status="completed",
            transcript_text="image transcript",
            used=False,
            image_path=image_path,
            image_url=image_url,
        )
        return rec

    def mark_image_transcript_completed(
        self, *, jid, image_id, transcript_text, duration_seconds
    ):
        rec = self.records[(jid, "i", image_id)]
        rec.transcript_text = transcript_text
        rec.status = "completed"
        return rec

    def mark_image_transcript_failed(self, *, jid, image_id, error):
        return None

    def list_images_for_jid(self, jid, limit=20):
        _ = (jid, limit)
        return []

    def get_image_for_jid(self, jid, image_id):
        return self.records.get((jid, "i", image_id))

    def mark_image_used(self, *, jid, image_id):
        rec = self.records.get((jid, "i", image_id))
        if rec is not None:
            rec.used = True
        return rec


class _FakeCommandExecutor:
    def __init__(self):
        self.command_calls = []
        self.query_calls = []
        self.session_calls = []
        self.toml_calls = []
        self.bound_rooms = set()
        self._pending_clear = {}

    def execute_command_text(self, *, jid, command_text, room_jid=None):
        self.command_calls.append((jid, room_jid, command_text))
        return f"command:{command_text}:{room_jid or '-'}"

    def execute_query_text(self, *, jid, query_text, room_jid=None):
        self.query_calls.append((jid, room_jid, query_text))
        return f"query:{query_text}:{room_jid or '-'}"

    def execute_session_command(
        self, *, jid, room_jid, command_text, conversation_key=""
    ):
        self.session_calls.append((jid, room_jid, command_text, conversation_key))
        if "clear" in command_text:
            self._pending_clear[conversation_key] = (jid, room_jid)
            return "confirm-clear-prompt"
        return "session:ok"

    def confirm_session_clear(self, *, jid, room_jid):
        return f"cleared:{jid}:{room_jid or '-'}"

    def consume_pending_clear(self, conversation_key, *, consume):
        entry = self._pending_clear.get(conversation_key)
        if entry and consume:
            self._pending_clear.pop(conversation_key, None)
        return entry

    def apply_inline_toml_if_present(self, *, jid, room_jid, body):
        if "```toml" not in body:
            return None
        return "inline-toml-applied"

    def apply_toml_url(self, *, jid, room_jid, url):
        self.toml_calls.append((jid, room_jid, url))
        return f"toml:{url}"

    def ensure_room_binding(self, room_jid):
        self.bound_rooms.add(room_jid)
        return 9

    def is_room_bound(self, room_jid):
        return room_jid in self.bound_rooms


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


class _FakeImageTranscriber:
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
        image_transcriber=_FakeImageTranscriber(enabled=True),
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
        image_transcriber=_FakeImageTranscriber(enabled=True),
        command_prefix="/asky",
        allowed_jids=["u@example.com"],
    )
    response = router.handle_text_message(
        jid="u@example.com/mobile-resource",
        message_type="chat",
        body="/asky --history 1",
    )
    assert response == "command:--history 1:-"


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
    assert response == "command:--history 5:-"


def test_router_query_without_interface_model_command_detection():
    router = _build_router(interface_enabled=False)
    response = router.handle_text_message(
        jid="u@example.com/resource",
        message_type="chat",
        body="what is new",
    )
    assert response == "query:what is new:-"


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


def test_router_image_queues_background_transcription():
    router = _build_router()
    response = router.handle_image_message(
        jid="u@example.com/resource",
        message_type="chat",
        image_url="https://example.com/image.jpg",
    )
    assert "Queued image transcription" in str(response)


def test_router_transcript_ready_message_clarifies_yes_no_action():
    router = _build_router()
    router.handle_audio_message(
        jid="u@example.com/resource",
        message_type="chat",
        audio_url="https://example.com/audio.m4a",
    )
    results = list(
        router.handle_transcription_result(
            {
                "jid": "u@example.com/resource",
                "transcript_id": 1,
                "status": "completed",
                "transcript_text": "hello transcript",
                "duration_seconds": 1.2,
            }
        )
    )
    assert len(results) == 1
    _jid, message = results[0]
    assert "Reply 'yes' to run transcript #at1 as a query now." in message
    assert "Reply 'no' to keep it for later." in message


def test_router_auto_runs_transcript_when_interface_model_disabled():
    router = _build_router(interface_enabled=False, auto_yes_without_interface=True)
    router.handle_audio_message(
        jid="u@example.com/resource",
        message_type="chat",
        audio_url="https://example.com/audio.m4a",
    )
    results = list(
        router.handle_transcription_result(
            {
                "jid": "u@example.com/resource",
                "transcript_id": 1,
                "status": "completed",
                "transcript_text": "how is weather in rijswijk today",
                "duration_seconds": 1.1,
            }
        )
    )
    assert len(results) == 2
    assert results[0] == (
        "u@example.com/resource",
        "Transcript #at1:\nhow is weather in rijswijk today",
    )
    assert results[1] == (
        "u@example.com/resource",
        "query:how is weather in rijswijk today:-",
    )


def test_router_auto_run_can_be_disabled_explicitly():
    router = _build_router(interface_enabled=False, auto_yes_without_interface=False)
    router.handle_audio_message(
        jid="u@example.com/resource",
        message_type="chat",
        audio_url="https://example.com/audio.m4a",
    )
    results = list(
        router.handle_transcription_result(
            {
                "jid": "u@example.com/resource",
                "transcript_id": 1,
                "status": "completed",
                "transcript_text": "how is weather in rijswijk today",
                "duration_seconds": 1.1,
            }
        )
    )
    assert len(results) == 1
    _jid, message = results[0]
    assert "Reply 'yes' to run transcript #at1 as a query now." in message


def test_router_image_transcript_completion_message():
    router = _build_router(interface_enabled=False)
    router.handle_image_message(
        jid="u@example.com/resource",
        message_type="chat",
        image_url="https://example.com/image.jpg",
    )
    results = list(
        router.handle_image_transcription_result(
            {
                "jid": "u@example.com/resource",
                "image_id": 1,
                "status": "completed",
                "transcript_text": "a flower in sunlight",
                "duration_seconds": 0.8,
            }
        )
    )
    assert len(results) == 1
    assert results[0] == (
        "u@example.com/resource",
        "transcript #it1 of image #i1:\na flower in sunlight",
    )


def test_router_groupchat_uses_bound_room_session():
    router = _build_router(interface_enabled=False)
    router.command_executor.ensure_room_binding("room@conference.example.com")

    response = router.handle_text_message(
        jid="room@conference.example.com/nick",
        message_type="groupchat",
        body="what is new",
        room_jid="room@conference.example.com",
        sender_jid="u@example.com/resource",
    )
    assert response == "query:what is new:room@conference.example.com"


def test_router_groupchat_ignores_unbound_room():
    router = _build_router(interface_enabled=False)
    response = router.handle_text_message(
        jid="room@conference.example.com/nick",
        message_type="groupchat",
        body="hello",
        room_jid="room@conference.example.com",
        sender_jid="u@example.com/resource",
    )
    assert response is None


def test_router_trusted_invite_binds_room():
    router = _build_router(interface_enabled=False)
    accepted = router.handle_room_invite(
        room_jid="room@conference.example.com",
        inviter_jid="u@example.com/resource",
    )
    assert accepted is True
    assert router.command_executor.is_room_bound("room@conference.example.com")


def test_router_session_clear_confirmation_flow():
    router = _build_router(interface_enabled=False)
    jid = "u@example.com/resource"

    # 1. Action returns prompt
    resp1 = router.handle_text_message(
        jid=jid, message_type="chat", body="/session clear"
    )
    assert resp1 == "confirm-clear-prompt"
    assert "u@example.com/resource" in router.command_executor._pending_clear

    # 2. 'yes' confirms
    resp2 = router.handle_text_message(jid=jid, message_type="chat", body="yes")
    assert resp2 == "cleared:u@example.com/resource:-"
    assert "u@example.com/resource" not in router.command_executor._pending_clear

    # 3. Request again then 'no' cancels
    router.handle_text_message(jid=jid, message_type="chat", body="/session clear")
    resp3 = router.handle_text_message(jid=jid, message_type="chat", body="no")
    assert "cancelled" in resp3.lower()
    assert "u@example.com/resource" not in router.command_executor._pending_clear


def test_router_help_command_bypasses_planner_with_interface_enabled():
    router = _build_router(interface_enabled=True)
    response = router.handle_text_message(
        jid="u@example.com/resource",
        message_type="chat",
        body="/h",
    )
    assert response == "command:/h:-"
    assert len(router.interface_planner.actions) == 0


def test_router_help_long_form_bypasses_planner_with_interface_enabled():
    router = _build_router(interface_enabled=True)
    response = router.handle_text_message(
        jid="u@example.com/resource",
        message_type="chat",
        body="/help",
    )
    assert response == "command:/help:-"
    assert len(router.interface_planner.actions) == 0


def test_router_transcript_command_bypasses_planner_with_interface_enabled():
    router = _build_router(interface_enabled=True)
    response = router.handle_text_message(
        jid="u@example.com/resource",
        message_type="chat",
        body="transcript list",
    )
    assert response == "command:transcript list:-"
    assert len(router.interface_planner.actions) == 0


def test_router_flag_command_bypasses_planner_with_interface_enabled():
    router = _build_router(interface_enabled=True)
    response = router.handle_text_message(
        jid="u@example.com/resource",
        message_type="chat",
        body="-H 5",
    )
    assert response == "command:-H 5:-"
    assert len(router.interface_planner.actions) == 0


def test_router_natural_language_still_goes_through_planner():
    router = _build_router(interface_enabled=True)
    response = router.handle_text_message(
        jid="u@example.com/resource",
        message_type="chat",
        body="what is the news today",
    )
    assert response == "query:planned:what is the news today:-"
    assert len(router.interface_planner.actions) == 1
    assert router.interface_planner.actions[0] == "what is the news today"
