"""Reusable query progress tracking and publishing for XMPP flows."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from asky.plugins.xmpp_daemon.xmpp_client import AskyXMPPClient, StatusMessageHandle

QUERY_STATUS_UPDATE_SECONDS = 2.0


@dataclass
class QueryProgressEvent:
    """Structured progress event emitted by query execution."""

    event_type: str
    query_id: str
    jid: str
    room_jid: Optional[str]
    text: str
    source: str


class QueryProgressAdapter:
    """Converts run_turn callbacks/events into concise query progress updates."""

    def __init__(
        self,
        *,
        jid: str,
        room_jid: Optional[str],
        source: str,
        emit_event: Optional[Callable[[QueryProgressEvent], None]],
    ):
        self.query_id = uuid.uuid4().hex
        self.jid = str(jid or "").strip()
        self.room_jid = str(room_jid or "").strip() or None
        self.source = str(source or "query").strip()
        self._emit_event_callback = emit_event
        self._last_text = ""
        self._turn = 0
        self._max_turns = 0

    def emit_start(self, *, model_alias: str) -> None:
        text = f"Running query ({model_alias})..."
        self._emit("start", text)

    def emit_done(self) -> None:
        self._emit("done", "Done. Sending response...", allow_duplicate=True)

    def emit_error(self, error: str) -> None:
        trimmed = str(error or "").strip() or "unknown error"
        self._emit("error", f"Query failed: {trimmed}", allow_duplicate=True)

    def preload_status_callback(self, message: str) -> None:
        normalized = str(message or "").strip()
        if not normalized:
            return
        self._emit("update", normalized)

    def display_callback(
        self,
        turn: int,
        *,
        status_message: Optional[str] = None,
        is_final: bool = False,
        final_answer: Optional[str] = None,
    ) -> None:
        if is_final:
            return
        normalized = str(status_message or "").strip()
        if normalized:
            self._emit("update", normalized)
            return
        if turn > 0:
            self._turn = int(turn)
            if self._max_turns > 0:
                self._emit("update", f"Turn {self._turn}/{self._max_turns}")
            else:
                self._emit("update", f"Turn {self._turn}")

    def event_callback(self, name: str, payload: dict) -> None:
        normalized_name = str(name or "").strip()
        if normalized_name == "turn_start":
            self._turn = int(payload.get("turn", 0) or 0)
            self._max_turns = int(payload.get("max_turns", 0) or 0)
            if self._turn > 0 and self._max_turns > 0:
                self._emit("update", f"Turn {self._turn}/{self._max_turns}")
        elif normalized_name == "tool_start":
            tool_name = str(payload.get("tool_name", "") or "").strip()
            if self._turn > 0 and self._max_turns > 0:
                prefix = f"Turn {self._turn}/{self._max_turns}: "
            elif self._turn > 0:
                prefix = f"Turn {self._turn}: "
            else:
                prefix = ""
            if tool_name:
                self._emit("update", f"{prefix}running {tool_name}")
        elif normalized_name == "llm_status":
            status_message = str(payload.get("status_message", "") or "").strip()
            if status_message:
                self._emit("update", status_message)

    def summarization_status_callback(self, message: Optional[str]) -> None:
        normalized = str(message or "").strip()
        if not normalized:
            return
        self._emit("update", normalized)

    def _emit(self, event_type: str, text: str, allow_duplicate: bool = False) -> None:
        normalized_text = str(text or "").strip()
        if not normalized_text:
            return
        if not allow_duplicate and normalized_text == self._last_text:
            return
        self._last_text = normalized_text
        if self._emit_event_callback is None:
            return
        self._emit_event_callback(
            QueryProgressEvent(
                event_type=event_type,
                query_id=self.query_id,
                jid=self.jid,
                room_jid=self.room_jid,
                text=normalized_text,
                source=self.source,
            )
        )


class QueryStatusPublisher:
    """Publishes status updates via message-edit when possible, with fallback appends."""

    def __init__(
        self,
        *,
        client: "AskyXMPPClient",
        target_jid: str,
        message_type: str,
        update_interval_seconds: float = QUERY_STATUS_UPDATE_SECONDS,
    ):
        self.client = client
        self.target_jid = str(target_jid or "").strip()
        self.message_type = str(message_type or "chat").strip().lower() or "chat"
        self.update_interval_seconds = float(update_interval_seconds)
        self.handle: Optional["StatusMessageHandle"] = None
        self.last_text = ""
        self.last_sent_at = 0.0

    def start(self, text: str) -> None:
        normalized = str(text or "").strip()
        if not normalized:
            return
        self.handle = self.client.send_status_message(
            to_jid=self.target_jid,
            body=normalized,
            message_type=self.message_type,
        )
        self.last_text = normalized
        self.last_sent_at = time.monotonic()

    def update(self, text: str, *, force: bool = False) -> None:
        normalized = str(text or "").strip()
        if not normalized:
            return
        if normalized == self.last_text and not force:
            return
        now = time.monotonic()
        if (
            not force
            and self.last_sent_at > 0
            and (now - self.last_sent_at) < self.update_interval_seconds
        ):
            return
        if self.handle is None:
            self.start(normalized)
            return
        self.handle = self.client.update_status_message(self.handle, body=normalized)
        self.last_text = normalized
        self.last_sent_at = time.monotonic()

    def finish(self, text: str) -> None:
        self.update(text, force=True)
