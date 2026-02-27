"""Focused tests for XMPP daemon plugin progress and status-update paths."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

import asky.plugins.xmpp_daemon.xmpp_client as plugin_xmpp_client
from asky.plugins.xmpp_daemon.command_executor import CommandExecutor
from asky.plugins.xmpp_daemon.query_progress import QueryProgressEvent
from asky.plugins.xmpp_daemon.xmpp_service import (
    GENERIC_ADHOC_QUERY_ERROR,
    XMPPService,
)


class _Loop:
    def call_soon_threadsafe(self, callback):
        callback()


class _MessageStanza:
    def __init__(self, *, to_jid: str, body: str, message_type: str, sink: list[dict]):
        self._sink = sink
        self._to_jid = to_jid
        self._body = body
        self._message_type = message_type
        self._attrs: dict[str, str] = {}
        self._replace: dict[str, str] = {}

    def __getitem__(self, key):
        if key == "replace":
            return self._replace
        return self._attrs[key]

    def __setitem__(self, key, value):
        self._attrs[key] = value

    def send(self):
        self._sink.append(
            {
                "to": self._to_jid,
                "body": self._body,
                "type": self._message_type,
                "id": self._attrs.get("id"),
                "replace_id": self._replace.get("id"),
            }
        )


class _ClientWithStanzaSupport:
    def __init__(self, jid, password):
        _ = (jid, password)
        self.handlers = {}
        self.plugin = {}
        self.loop = _Loop()
        self.sent_messages: list[dict] = []
        self.sent_stanzas: list[dict] = []

    def add_event_handler(self, name, callback):
        self.handlers[name] = callback

    def register_plugin(self, name):
        self.plugin[name] = object()

    def connect(self, host=None, port=None):
        _ = (host, port)
        return True

    def process(self, forever=True):
        _ = forever

    def send_message(self, **kwargs):
        self.sent_messages.append(kwargs)

    def make_message(self, *, mto, mbody, mtype):
        return _MessageStanza(
            to_jid=mto,
            body=mbody,
            message_type=mtype,
            sink=self.sent_stanzas,
        )

    def disconnect(self):
        return None


class _FakeSessionProfileManager:
    def resolve_conversation_session_id(self, *, room_jid, jid):
        _ = (room_jid, jid)
        return 1


class _FakeTranscriptManager:
    def __init__(self):
        self.session_profile_manager = _FakeSessionProfileManager()


def test_status_message_update_uses_replace_stanza(monkeypatch):
    module = SimpleNamespace(ClientXMPP=_ClientWithStanzaSupport)
    monkeypatch.setattr(plugin_xmpp_client, "slixmpp", module)
    client = plugin_xmpp_client.AskyXMPPClient(
        jid="bot@example.com",
        password="secret",
        host="xmpp.example.com",
        port=5222,
        resource="asky",
        message_callback=lambda _payload: None,
    )

    original = client.send_status_message(
        to_jid="u@example.com", body="starting", message_type="chat"
    )
    updated = client.update_status_message(original, body="working")

    assert len(client._client.sent_stanzas) == 2
    first, second = client._client.sent_stanzas
    assert first["replace_id"] is None
    assert first["id"] == original.message_id
    assert second["replace_id"] == original.message_id
    assert second["id"] == updated.message_id
    assert updated.message_id != original.message_id


def test_command_executes_lm_query_is_structural_only():
    executor = CommandExecutor(_FakeTranscriptManager())
    with (
        patch.object(executor, "_prepare_query_text", side_effect=AssertionError),
        patch.object(executor, "_resolve_session_id", side_effect=AssertionError),
    ):
        assert executor.command_executes_lm_query(jid="u", command_text="hello world") is True
        assert executor.command_executes_lm_query(jid="u", command_text="--history 5") is False
        assert executor.command_executes_lm_query(jid="u", command_text="transcript use #at1") is True
        assert executor.command_executes_lm_query(jid="u", command_text="--query-corpus topic") is False


def test_schedule_adhoc_query_uses_generic_error_message():
    service = XMPPService.__new__(XMPPService)
    service.command_executor = Mock()
    service.command_executor.execute_command_text.side_effect = RuntimeError(
        "secret path /tmp/cred"
    )
    sent: list[tuple[str, str, str]] = []

    def _enqueue(jid, task):
        _ = jid
        task()

    service._enqueue_for_jid = _enqueue
    service._send_chunked = lambda jid, text, message_type="chat": sent.append((jid, text, message_type))

    service._schedule_adhoc_query(jid="u@example.com", room_jid=None, command_text="bad")

    assert sent == [("u@example.com", GENERIC_ADHOC_QUERY_ERROR, "chat")]


def test_query_progress_event_lifecycle_tracks_publishers():
    events: list[tuple[str, str]] = []

    class _FakePublisher:
        def __init__(self, *, client, target_jid, message_type, update_interval_seconds):
            _ = (client, target_jid, message_type, update_interval_seconds)

        def start(self, text):
            events.append(("start", text))

        def update(self, text):
            events.append(("update", text))

        def finish(self, text):
            events.append(("finish", text))

    service = XMPPService.__new__(XMPPService)
    service._client = object()
    service._query_publishers = {}
    service._query_publishers_lock = threading.Lock()

    with patch("asky.plugins.xmpp_daemon.xmpp_service.QueryStatusPublisher", _FakePublisher):
        service._on_query_progress_event(
            QueryProgressEvent(
                event_type="start",
                query_id="q1",
                jid="u@example.com",
                room_jid=None,
                text="Running",
                source="test",
            )
        )
        assert "q1" in service._query_publishers
        service._on_query_progress_event(
            QueryProgressEvent(
                event_type="update",
                query_id="q1",
                jid="u@example.com",
                room_jid=None,
                text="Thinking",
                source="test",
            )
        )
        service._on_query_progress_event(
            QueryProgressEvent(
                event_type="done",
                query_id="q1",
                jid="u@example.com",
                room_jid=None,
                text="Done",
                source="test",
            )
        )

    assert events == [("start", "Running"), ("update", "Thinking"), ("finish", "Done")]
    assert "q1" not in service._query_publishers
