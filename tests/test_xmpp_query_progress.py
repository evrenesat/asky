"""Unit tests for XMPP query progress adapter and status publisher."""

from __future__ import annotations

import itertools

from asky.plugins.xmpp_daemon.query_progress import (
    QueryProgressAdapter,
    QueryStatusPublisher,
)
from asky.plugins.xmpp_daemon.xmpp_client import StatusMessageHandle


class _FakeClient:
    def __init__(self):
        self.sent: list[tuple[str, str, str]] = []
        self.updated: list[tuple[str, str]] = []

    def send_status_message(self, *, to_jid: str, body: str, message_type: str) -> StatusMessageHandle:
        self.sent.append((to_jid, body, message_type))
        return StatusMessageHandle(
            message_id="m1",
            to_jid=to_jid,
            message_type=message_type,
            correction_supported=True,
        )

    def update_status_message(self, handle: StatusMessageHandle, *, body: str) -> StatusMessageHandle:
        self.updated.append((handle.message_id, body))
        return StatusMessageHandle(
            message_id=f"{handle.message_id}u",
            to_jid=handle.to_jid,
            message_type=handle.message_type,
            correction_supported=handle.correction_supported,
        )


def test_query_progress_adapter_emits_start_update_done():
    events = []
    adapter = QueryProgressAdapter(
        jid="user@example.com",
        room_jid=None,
        source="test",
        emit_event=events.append,
    )

    adapter.emit_start(model_alias="main")
    adapter.preload_status_callback("Loading context")
    adapter.event_callback("turn_start", {"turn": 1, "max_turns": 3})
    adapter.display_callback(1, status_message="Thinking")
    adapter.summarization_status_callback("Summarizing")
    adapter.emit_done()

    assert [event.event_type for event in events] == [
        "start",
        "update",
        "update",
        "update",
        "update",
        "done",
    ]
    assert events[0].text == "Running query (main)..."
    assert events[-1].text == "Done. Sending response..."


def test_query_progress_adapter_skips_duplicate_and_final_display():
    events = []
    adapter = QueryProgressAdapter(
        jid="user@example.com",
        room_jid=None,
        source="test",
        emit_event=events.append,
    )

    adapter.preload_status_callback("Working")
    adapter.preload_status_callback("Working")
    adapter.display_callback(1, is_final=True, status_message="final")

    assert len(events) == 1
    assert events[0].text == "Working"


def test_query_status_publisher_throttles_updates(monkeypatch):
    client = _FakeClient()
    publisher = QueryStatusPublisher(
        client=client,
        target_jid="user@example.com",
        message_type="chat",
        update_interval_seconds=2.0,
    )
    times = itertools.chain([0.0, 0.0, 0.5, 2.5, 5.0], itertools.repeat(5.0))
    monkeypatch.setattr("asky.plugins.xmpp_daemon.query_progress.time.monotonic", lambda: next(times))

    publisher.start("Starting")
    publisher.update("Still running")
    publisher.update("Still running")
    publisher.update("Next phase")
    publisher.finish("Done")

    assert client.sent == [("user@example.com", "Starting", "chat")]
    assert client.updated == [
        ("m1", "Still running"),
        ("m1u", "Next phase"),
        ("m1uu", "Done"),
    ]
