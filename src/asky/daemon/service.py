"""Foreground daemon service bootstrap for XMPP mode."""

from __future__ import annotations

import logging
import queue
import threading
from typing import Callable
from urllib.parse import urlparse

from asky.config import (
    INTERFACE_MODEL,
    INTERFACE_PLANNER_SYSTEM_PROMPT,
    XMPP_ALLOWED_JIDS,
    XMPP_COMMAND_PREFIX,
    XMPP_ENABLED,
    XMPP_HOST,
    XMPP_INTERFACE_PLANNER_INCLUDE_COMMAND_REFERENCE,
    XMPP_JID,
    XMPP_PASSWORD,
    XMPP_PORT,
    XMPP_RESOURCE,
    XMPP_RESPONSE_CHUNK_CHARS,
    XMPP_TRANSCRIPT_MAX_PER_SESSION,
    XMPP_VOICE_ALLOWED_MIME_TYPES,
    XMPP_VOICE_AUTO_YES_WITHOUT_INTERFACE_MODEL,
    XMPP_VOICE_ENABLED,
    XMPP_VOICE_LANGUAGE,
    XMPP_VOICE_HF_TOKEN,
    XMPP_VOICE_HF_TOKEN_ENV,
    XMPP_VOICE_MAX_SIZE_MB,
    XMPP_VOICE_MODEL,
    XMPP_VOICE_STORAGE_DIR,
    XMPP_VOICE_WORKERS,
)
from asky.daemon.chunking import chunk_text
from asky.daemon.command_executor import CommandExecutor
from asky.daemon.interface_planner import InterfacePlanner
from asky.daemon.router import DaemonRouter
from asky.daemon.transcript_manager import TranscriptManager
from asky.daemon.voice_transcriber import VoiceTranscriber
from asky.daemon.xmpp_client import AskyXMPPClient
from asky.storage import init_db

logger = logging.getLogger(__name__)


class XMPPDaemonService:
    """Coordinates daemon router, background workers, and XMPP transport."""

    def __init__(self):
        init_db()
        self.transcript_manager = TranscriptManager(
            transcript_cap=XMPP_TRANSCRIPT_MAX_PER_SESSION
        )
        self.command_executor = CommandExecutor(self.transcript_manager)
        self.interface_planner = InterfacePlanner(
            INTERFACE_MODEL,
            system_prompt=INTERFACE_PLANNER_SYSTEM_PROMPT,
            command_reference=self.command_executor.get_interface_command_reference(),
            include_command_reference=XMPP_INTERFACE_PLANNER_INCLUDE_COMMAND_REFERENCE,
        )
        self.voice_transcriber = VoiceTranscriber(
            enabled=XMPP_VOICE_ENABLED,
            workers=XMPP_VOICE_WORKERS,
            max_size_mb=XMPP_VOICE_MAX_SIZE_MB,
            model=XMPP_VOICE_MODEL,
            language=XMPP_VOICE_LANGUAGE,
            storage_dir=XMPP_VOICE_STORAGE_DIR,
            hf_token_env=XMPP_VOICE_HF_TOKEN_ENV,
            hf_token=XMPP_VOICE_HF_TOKEN,
            allowed_mime_types=XMPP_VOICE_ALLOWED_MIME_TYPES,
            completion_callback=self._on_transcription_complete,
        )
        self.router = DaemonRouter(
            transcript_manager=self.transcript_manager,
            command_executor=self.command_executor,
            interface_planner=self.interface_planner,
            voice_transcriber=self.voice_transcriber,
            command_prefix=XMPP_COMMAND_PREFIX,
            allowed_jids=list(XMPP_ALLOWED_JIDS),
            voice_auto_yes_without_interface_model=XMPP_VOICE_AUTO_YES_WITHOUT_INTERFACE_MODEL,
        )
        self._jid_queues: dict[str, queue.Queue[Callable[[], None]]] = {}
        self._jid_workers: dict[str, threading.Thread] = {}
        self._client = AskyXMPPClient(
            jid=XMPP_JID,
            password=XMPP_PASSWORD,
            host=XMPP_HOST,
            port=XMPP_PORT,
            resource=XMPP_RESOURCE,
            message_callback=self._on_xmpp_message,
        )

    def run_foreground(self) -> None:
        self._client.start_foreground()

    def _on_xmpp_message(self, payload: dict) -> None:
        from_jid = str(payload.get("from_jid", "") or "").strip()
        if not from_jid:
            return

        def _task() -> None:
            response_text = None
            audio_url = str(payload.get("audio_url", "") or "").strip()
            body = str(payload.get("body", "") or "").strip()
            message_type = str(payload.get("type", "") or "").strip().lower()
            if audio_url:
                response_text = self.router.handle_audio_message(
                    jid=from_jid,
                    message_type=message_type,
                    audio_url=audio_url,
                )
                if response_text:
                    self._send_chunked(from_jid, response_text)
            if _should_process_text_body(audio_url=audio_url, body=body):
                response_text = self.router.handle_text_message(
                    jid=from_jid,
                    message_type=message_type,
                    body=body,
                )
                if response_text:
                    self._send_chunked(from_jid, response_text)

        self._enqueue_for_jid(from_jid, _task)

    def _enqueue_for_jid(self, jid: str, task: Callable[[], None]) -> None:
        if jid not in self._jid_queues:
            self._jid_queues[jid] = queue.Queue()
        if jid not in self._jid_workers or not self._jid_workers[jid].is_alive():
            worker = threading.Thread(
                target=self._jid_worker_loop,
                args=(jid,),
                daemon=True,
                name=f"asky-xmpp-{jid}",
            )
            worker.start()
            self._jid_workers[jid] = worker
        self._jid_queues[jid].put(task)

    def _jid_worker_loop(self, jid: str) -> None:
        jid_queue = self._jid_queues[jid]
        while True:
            task = jid_queue.get()
            try:
                task()
            except Exception:
                logger.exception("failed to process daemon task for jid=%s", jid)
            finally:
                jid_queue.task_done()

    def _send_chunked(self, jid: str, text: str) -> None:
        parts = chunk_text(text, XMPP_RESPONSE_CHUNK_CHARS)
        total = len(parts)
        for index, part in enumerate(parts, start=1):
            if total > 1:
                body = f"[part {index}/{total}]\n{part}"
            else:
                body = part
            self._client.send_chat_message(jid, body)

    def _on_transcription_complete(self, payload: dict) -> None:
        result = self.router.handle_transcription_result(payload)
        if not result:
            return
        jid, message = result
        self._send_chunked(jid, message)


def run_xmpp_daemon_foreground() -> None:
    """Entry point used by CLI flag."""
    if not XMPP_ENABLED:
        raise RuntimeError("XMPP daemon is disabled in xmpp.toml (xmpp.enabled=false).")
    service = XMPPDaemonService()
    service.run_foreground()


def _should_process_text_body(*, audio_url: str, body: str) -> bool:
    normalized_body = str(body or "").strip()
    if not normalized_body:
        return False
    if not str(audio_url or "").strip():
        return True
    if _is_url_only_text(normalized_body):
        return False
    return True


def _is_url_only_text(value: str) -> bool:
    normalized = str(value or "").strip()
    if not normalized:
        return False
    if len(normalized.split()) != 1:
        return False
    parsed = urlparse(normalized)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
