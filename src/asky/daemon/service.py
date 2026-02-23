"""Foreground daemon service bootstrap for XMPP mode."""

from __future__ import annotations

import logging
import queue
import threading
from typing import Callable
from urllib.parse import urlparse

from asky.config import (
    DEFAULT_IMAGE_MODEL,
    INTERFACE_MODEL,
    INTERFACE_PLANNER_SYSTEM_PROMPT,
    XMPP_ALLOWED_JIDS,
    XMPP_COMMAND_PREFIX,
    XMPP_ENABLED,
    XMPP_HOST,
    XMPP_INTERFACE_PLANNER_INCLUDE_COMMAND_REFERENCE,
    XMPP_IMAGE_ALLOWED_MIME_TYPES,
    XMPP_IMAGE_ENABLED,
    XMPP_IMAGE_MAX_SIZE_MB,
    XMPP_IMAGE_PROMPT,
    XMPP_IMAGE_STORAGE_DIR,
    XMPP_IMAGE_WORKERS,
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
from asky.daemon.image_transcriber import ImageTranscriber
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
        self.image_transcriber = ImageTranscriber(
            enabled=XMPP_IMAGE_ENABLED,
            workers=XMPP_IMAGE_WORKERS,
            max_size_mb=XMPP_IMAGE_MAX_SIZE_MB,
            model_alias=DEFAULT_IMAGE_MODEL,
            prompt_text=XMPP_IMAGE_PROMPT,
            storage_dir=XMPP_IMAGE_STORAGE_DIR,
            allowed_mime_types=XMPP_IMAGE_ALLOWED_MIME_TYPES,
            completion_callback=self._on_image_transcription_complete,
        )
        self.router = DaemonRouter(
            transcript_manager=self.transcript_manager,
            command_executor=self.command_executor,
            interface_planner=self.interface_planner,
            voice_transcriber=self.voice_transcriber,
            image_transcriber=self.image_transcriber,
            command_prefix=XMPP_COMMAND_PREFIX,
            allowed_jids=list(XMPP_ALLOWED_JIDS),
            voice_auto_yes_without_interface_model=XMPP_VOICE_AUTO_YES_WITHOUT_INTERFACE_MODEL,
        )
        self._jid_queues: dict[str, queue.Queue[Callable[[], None]]] = {}
        self._jid_workers: dict[str, threading.Thread] = {}
        self._jid_workers_lock = threading.Lock()
        self._client = AskyXMPPClient(
            jid=XMPP_JID,
            password=XMPP_PASSWORD,
            host=XMPP_HOST,
            port=XMPP_PORT,
            resource=XMPP_RESOURCE,
            message_callback=self._on_xmpp_message,
            session_start_callback=self._on_xmpp_session_start,
        )

    def run_foreground(self) -> None:
        self._client.start_foreground()

    def _on_xmpp_message(self, payload: dict) -> None:
        from_jid = str(payload.get("from_jid", "") or "").strip()
        if not from_jid:
            return
        queue_key = _resolve_queue_key(payload, fallback_jid=from_jid)

        def _task() -> None:
            oob_urls = payload.get("oob_urls", []) or []
            audio_urls, image_urls = _split_media_urls(oob_urls)
            body = str(payload.get("body", "") or "").strip()
            message_type = str(payload.get("type", "") or "").strip().lower()
            room_jid = str(payload.get("room_jid", "") or "").strip().lower()
            sender_jid = str(payload.get("sender_jid", "") or "").strip()
            sender_nick = str(payload.get("sender_nick", "") or "").strip()
            invite_room_jid = str(payload.get("invite_room_jid", "") or "").strip().lower()
            invite_from_jid = str(payload.get("invite_from_jid", "") or "").strip()
            target_jid, target_message_type = _resolve_reply_target(
                from_jid=from_jid,
                message_type=message_type,
                room_jid=room_jid,
            )

            if invite_room_jid and invite_from_jid:
                if self.router.handle_room_invite(
                    room_jid=invite_room_jid,
                    inviter_jid=invite_from_jid,
                ):
                    self._client.join_room(invite_room_jid)

            if message_type == "groupchat" and sender_nick == XMPP_RESOURCE:
                return

            toml_urls = _extract_toml_urls(payload)
            for toml_url in toml_urls:
                response_text = self.router.handle_toml_url_message(
                    jid=from_jid,
                    message_type=message_type,
                    url=toml_url,
                    room_jid=room_jid or None,
                    sender_jid=sender_jid or None,
                )
                if response_text:
                    self._send_chunked(
                        target_jid,
                        response_text,
                        message_type=target_message_type,
                    )

            for audio_url in audio_urls:
                response_text = self.router.handle_audio_message(
                    jid=from_jid,
                    message_type=message_type,
                    audio_url=audio_url,
                    room_jid=room_jid or None,
                    sender_jid=sender_jid or None,
                )
                if response_text:
                    self._send_chunked(
                        target_jid,
                        response_text,
                        message_type=target_message_type,
                    )
            for image_url in image_urls:
                response_text = self.router.handle_image_message(
                    jid=from_jid,
                    message_type=message_type,
                    image_url=image_url,
                    room_jid=room_jid or None,
                )
                if response_text:
                    self._send_chunked(
                        target_jid,
                        response_text,
                        message_type=target_message_type,
                    )
            if _should_process_text_body(
                has_media=bool(audio_urls or image_urls), body=body
            ):
                response_text = self.router.handle_text_message(
                    jid=from_jid,
                    message_type=message_type,
                    body=body,
                    room_jid=room_jid or None,
                    sender_jid=sender_jid or None,
                )
                if response_text:
                    self._send_chunked(
                        target_jid,
                        response_text,
                        message_type=target_message_type,
                    )

        self._enqueue_for_jid(queue_key, _task)

    def _enqueue_for_jid(self, jid: str, task: Callable[[], None]) -> None:
        if jid not in self._jid_queues:
            self._jid_queues[jid] = queue.Queue()
        with self._jid_workers_lock:
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

    def _send_chunked(self, jid: str, text: str, *, message_type: str = "chat") -> None:
        parts = chunk_text(text, XMPP_RESPONSE_CHUNK_CHARS)
        total = len(parts)
        for index, part in enumerate(parts, start=1):
            if total > 1:
                body = f"[part {index}/{total}]\n{part}"
            else:
                body = part
            if str(message_type or "").strip().lower() == "groupchat":
                self._client.send_group_message(jid, body)
            else:
                self._client.send_chat_message(jid, body)

    def _on_transcription_complete(self, payload: dict) -> None:
        result = self.router.handle_transcription_result(payload)
        if not result:
            return
        jid, message = result
        message_type = "groupchat" if self.command_executor.is_room_bound(jid) else "chat"
        self._send_chunked(jid, message, message_type=message_type)

    def _on_image_transcription_complete(self, payload: dict) -> None:
        result = self.router.handle_image_transcription_result(payload)
        if not result:
            return
        jid, message = result
        message_type = "groupchat" if self.command_executor.is_room_bound(jid) else "chat"
        self._send_chunked(jid, message, message_type=message_type)

    def _on_xmpp_session_start(self) -> None:
        for room_jid in self.command_executor.list_bound_room_jids():
            self._client.join_room(room_jid)


def run_xmpp_daemon_foreground() -> None:
    """Entry point used by CLI flag."""
    if not XMPP_ENABLED:
        raise RuntimeError("XMPP daemon is disabled in xmpp.toml (xmpp.enabled=false).")
    service = XMPPDaemonService()
    service.run_foreground()


def _should_process_text_body(*, has_media: bool, body: str) -> bool:
    normalized_body = str(body or "").strip()
    if not normalized_body:
        return False
    if not has_media:
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


def _resolve_queue_key(payload: dict, *, fallback_jid: str) -> str:
    message_type = str(payload.get("type", "") or "").strip().lower()
    if message_type == "groupchat":
        room_jid = str(payload.get("room_jid", "") or "").strip().lower()
        if room_jid:
            return room_jid
    return fallback_jid


def _resolve_reply_target(
    *,
    from_jid: str,
    message_type: str,
    room_jid: str,
) -> tuple[str, str]:
    if str(message_type or "").strip().lower() == "groupchat":
        if room_jid:
            return room_jid, "groupchat"
    return from_jid, "chat"


def _extract_toml_urls(payload: dict) -> list[str]:
    raw_urls = payload.get("oob_urls", []) or []
    urls: list[str] = []
    for value in raw_urls:
        normalized = str(value or "").strip()
        if not normalized:
            continue
        parsed = urlparse(normalized)
        path = str(parsed.path or "").lower()
        if not path.endswith(".toml"):
            continue
        urls.append(normalized)
    return urls


def _split_media_urls(urls: list[str]) -> tuple[list[str], list[str]]:
    audio_urls: list[str] = []
    image_urls: list[str] = []
    for value in urls:
        normalized = str(value or "").strip()
        if not normalized:
            continue
        parsed = urlparse(normalized)
        path = str(parsed.path or "").lower()
        if path.endswith(".toml"):
            continue
        if path.endswith((".m4a", ".mp3", ".mp4", ".wav", ".webm", ".ogg", ".flac", ".opus")):
            audio_urls.append(normalized)
            continue
        if path.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
            image_urls.append(normalized)
    return audio_urls, image_urls
