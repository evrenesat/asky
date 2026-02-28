"""XMPP transport service for daemon mode."""

from __future__ import annotations

import logging
import queue
import re
import threading
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlparse

from asky.config import (
    DEFAULT_IMAGE_MODEL,
    INTERFACE_MODEL,
    INTERFACE_PLANNER_SYSTEM_PROMPT,
    XMPP_ALLOWED_JIDS,
    XMPP_COMMAND_PREFIX,
    XMPP_IMAGE_ALLOWED_MIME_TYPES,
    XMPP_IMAGE_ENABLED,
    XMPP_IMAGE_MAX_SIZE_MB,
    XMPP_IMAGE_PROMPT,
    XMPP_IMAGE_STORAGE_DIR,
    XMPP_IMAGE_WORKERS,
    XMPP_INTERFACE_PLANNER_INCLUDE_COMMAND_REFERENCE,
    XMPP_JID,
    XMPP_PASSWORD,
    XMPP_HOST,
    XMPP_PORT,
    XMPP_RESOURCE,
    XMPP_RESPONSE_CHUNK_CHARS,
    XMPP_TRANSCRIPT_MAX_PER_SESSION,
    XMPP_CLIENT_CAPABILITIES,
    XMPP_VOICE_ALLOWED_MIME_TYPES,
    XMPP_VOICE_AUTO_YES_WITHOUT_INTERFACE_MODEL,
    XMPP_VOICE_ENABLED,
    XMPP_VOICE_HF_TOKEN,
    XMPP_VOICE_HF_TOKEN_ENV,
    XMPP_VOICE_LANGUAGE,
    XMPP_VOICE_MAX_SIZE_MB,
    XMPP_VOICE_MODEL,
    XMPP_VOICE_STORAGE_DIR,
    XMPP_VOICE_WORKERS,
)
from asky.daemon.errors import DaemonUserError
from asky.plugins.xmpp_daemon.adhoc_commands import AdHocCommandHandler
from asky.plugins.xmpp_daemon.chunking import chunk_text
from asky.plugins.xmpp_daemon.command_executor import CommandExecutor
from asky.plugins.xmpp_daemon.document_ingestion import (
    DocumentIngestionService,
    redact_document_urls,
    split_document_urls,
)
from asky.plugins.xmpp_daemon.image_transcriber import ImageTranscriber
from asky.plugins.xmpp_daemon.interface_planner import InterfacePlanner
from asky.plugins.xmpp_daemon.query_progress import (
    QUERY_STATUS_UPDATE_SECONDS,
    QueryProgressEvent,
    QueryStatusPublisher,
)
from asky.plugins.xmpp_daemon.router import DaemonRouter
from asky.plugins.xmpp_daemon.transcript_manager import TranscriptManager
from asky.plugins.xmpp_daemon.voice_transcriber import VoiceTranscriber
from asky.plugins.xmpp_daemon.xmpp_client import AskyXMPPClient

logger = logging.getLogger(__name__)
URL_PATTERN = re.compile(r"https?://[^\s<>\"]+")
AUDIO_EXTENSIONS = (".m4a", ".mp3", ".mp4", ".wav", ".webm", ".ogg", ".flac", ".opus")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
GENERIC_ADHOC_QUERY_ERROR = (
    "Error: failed to execute the requested command. Please try again."
)


"""XMPP transport: wires daemon router, background workers, and XMPP client."""

from asky.plugins.xmpp_daemon.xmpp_formatting import (
    ASCIITableRenderer,
    MessageFormatter,
    extract_markdown_tables,
)


class XMPPService:
    """XMPP transport: wires daemon router, background workers, and XMPP client."""

    def __init__(
        self,
        double_verbose: bool = False,
        plugin_runtime: Optional[Any] = None,
    ):
        logger.debug("initializing XMPPService")
        self.plugin_runtime = plugin_runtime
        self.transcript_manager = TranscriptManager(
            transcript_cap=XMPP_TRANSCRIPT_MAX_PER_SESSION
        )
        self.command_executor = CommandExecutor(
            self.transcript_manager,
            double_verbose=double_verbose,
            plugin_runtime=self.plugin_runtime,
            query_progress_callback=self._on_query_progress_event,
        )
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

        self._table_renderer = ASCIITableRenderer()
        self._formatter = MessageFormatter(self._table_renderer)

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
        self.document_ingestion = DocumentIngestionService()
        self._adhoc_handler = AdHocCommandHandler(
            command_executor=self.command_executor,
            router=self.router,
            voice_enabled=XMPP_VOICE_ENABLED,
            image_enabled=XMPP_IMAGE_ENABLED,
            query_dispatch_callback=self._schedule_adhoc_query,
        )
        self._jid_queues: dict[str, queue.Queue[Callable[[], None]]] = {}
        self._jid_workers: dict[str, threading.Thread] = {}
        self._jid_workers_lock = threading.Lock()
        self._query_publishers: dict[str, QueryStatusPublisher] = {}
        self._query_publishers_lock = threading.Lock()
        self._client = AskyXMPPClient(
            jid=XMPP_JID,
            password=XMPP_PASSWORD,
            host=XMPP_HOST,
            port=XMPP_PORT,
            resource=XMPP_RESOURCE,
            message_callback=self._on_xmpp_message,
            session_start_callback=self._on_xmpp_session_start,
            client_capabilities=dict(XMPP_CLIENT_CAPABILITIES),
        )
        logger.debug(
            "XMPPService initialized host=%s port=%s resource=%s allowed_count=%s client_capability_map_count=%s",
            XMPP_HOST,
            XMPP_PORT,
            XMPP_RESOURCE,
            len(XMPP_ALLOWED_JIDS),
            len(XMPP_CLIENT_CAPABILITIES),
        )

    def run(self) -> None:
        """Blocking foreground loop: connect XMPP and process messages."""
        self._client.start_foreground()

    def stop(self) -> None:
        """Request graceful shutdown of the XMPP client."""
        logger.info("XMPPService stop requested")
        self._client.stop()

    def _on_xmpp_message(self, payload: dict) -> None:
        from_jid = str(payload.get("from_jid", "") or "").strip()
        if not from_jid:
            return
        queue_key = _resolve_queue_key(payload, fallback_jid=from_jid)

        def _task() -> None:
            oob_urls = payload.get("oob_urls", []) or []
            body = str(payload.get("body", "") or "").strip()
            body_urls = _extract_urls_from_text(body)
            audio_urls_oob, image_urls_oob = _split_media_urls(oob_urls)
            audio_urls_body, image_urls_body = _split_media_urls(body_urls)
            audio_urls = _merge_unique_urls(audio_urls_oob + audio_urls_body)
            image_urls = _merge_unique_urls(image_urls_oob + image_urls_body)
            document_urls = _merge_unique_urls(
                split_document_urls(oob_urls) + split_document_urls(body_urls)
            )
            message_type = str(payload.get("type", "") or "").strip().lower()
            room_jid = str(payload.get("room_jid", "") or "").strip().lower()
            sender_jid = str(payload.get("sender_jid", "") or "").strip()
            sender_nick = str(payload.get("sender_nick", "") or "").strip()
            invite_room_jid = (
                str(payload.get("invite_room_jid", "") or "").strip().lower()
            )
            invite_from_jid = str(payload.get("invite_from_jid", "") or "").strip()
            target_jid, target_message_type = _resolve_reply_target(
                from_jid=from_jid,
                message_type=message_type,
                room_jid=room_jid,
            )
            try:
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
                if document_urls:
                    session_id = self.command_executor.session_profile_manager.resolve_conversation_session_id(
                        room_jid=room_jid or None,
                        jid=sender_jid or from_jid,
                    )
                    ingestion_report = self.document_ingestion.ingest_for_session(
                        session_id=int(session_id),
                        urls=document_urls,
                    )
                    self._send_chunked(
                        target_jid,
                        self.document_ingestion.format_ack(ingestion_report),
                        message_type=target_message_type,
                    )
                    body = redact_document_urls(body, document_urls)
                if _should_process_text_body(
                    has_media=bool(audio_urls or image_urls or document_urls), body=body
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
            except DaemonUserError as exc:
                logger.warning(
                    "user-visible daemon error for jid=%s: %s",
                    from_jid,
                    exc.user_message,
                )
                self._send_chunked(
                    target_jid,
                    f"Error: {exc.user_message}",
                    message_type=target_message_type,
                )

        self._enqueue_for_jid(queue_key, _task)

    def _schedule_adhoc_query(
        self,
        *,
        jid: str,
        room_jid: Optional[str],
        query_text: Optional[str] = None,
        command_text: Optional[str] = None,
    ) -> None:
        normalized_jid = str(jid or "").strip()
        if not normalized_jid:
            return
        normalized_query_text = str(query_text or "").strip()
        normalized_command_text = str(command_text or "").strip()
        if not normalized_query_text and not normalized_command_text:
            return

        def _task() -> None:
            try:
                if normalized_query_text:
                    response_text = self.command_executor.execute_query_text(
                        jid=normalized_jid,
                        room_jid=room_jid,
                        query_text=normalized_query_text,
                    )
                else:
                    response_text = self.command_executor.execute_command_text(
                        jid=normalized_jid,
                        room_jid=room_jid,
                        command_text=normalized_command_text,
                    )
                if response_text:
                    self._send_chunked(normalized_jid, response_text, message_type="chat")
            except Exception:
                logger.exception("failed to execute ad-hoc queued query")
                self._send_chunked(
                    normalized_jid,
                    GENERIC_ADHOC_QUERY_ERROR,
                    message_type="chat",
                )

        self._enqueue_for_jid(normalized_jid, _task)

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
        model = extract_markdown_tables(text)
        xhtml_body = self._formatter.format_xhtml_body(model)
        if xhtml_body:
            formatted_text = self._formatter.format_plain_body_for_xhtml_fallback(model)
        else:
            formatted_text = self._formatter.format_message(model)
        self._send_chunked_text(
            jid,
            formatted_text,
            message_type=str(message_type or "").strip().lower(),
            xhtml_body=xhtml_body,
        )

    def _send_chunked_text(
        self,
        jid: str,
        text: str,
        *,
        message_type: str,
        xhtml_body: Optional[str] = None,
    ) -> None:
        if not text:
            return
        parts = chunk_text(text, XMPP_RESPONSE_CHUNK_CHARS)
        total = len(parts)
        for index, part in enumerate(parts, start=1):
            if total > 1:
                body = f"[part {index}/{total}]\n{part}"
            else:
                body = part
            if total == 1 and xhtml_body:
                self._client.send_message(
                    to_jid=jid,
                    body=body,
                    message_type=message_type,
                    xhtml_body=xhtml_body,
                )
            elif message_type == "groupchat":
                self._client.send_group_message(jid, body)
            else:
                self._client.send_chat_message(jid, body)

    def _on_query_progress_event(self, event: QueryProgressEvent) -> None:
        key = str(event.query_id or "").strip()
        if not key:
            return
        target_jid, message_type = _resolve_query_progress_target(event)
        if not target_jid:
            return
        if event.event_type == "start":
            with self._query_publishers_lock:
                publisher = QueryStatusPublisher(
                    client=self._client,
                    target_jid=target_jid,
                    message_type=message_type,
                    update_interval_seconds=QUERY_STATUS_UPDATE_SECONDS,
                )
                self._query_publishers[key] = publisher
            try:
                publisher.start(event.text)
            except Exception:
                with self._query_publishers_lock:
                    self._query_publishers.pop(key, None)
                raise
            return
        with self._query_publishers_lock:
            publisher = self._query_publishers.get(key)
        if publisher is None:
            publisher = QueryStatusPublisher(
                client=self._client,
                target_jid=target_jid,
                message_type=message_type,
                update_interval_seconds=QUERY_STATUS_UPDATE_SECONDS,
            )
            publisher.start("Running query...")
            with self._query_publishers_lock:
                self._query_publishers[key] = publisher
        if event.event_type == "done":
            publisher.finish(event.text)
            with self._query_publishers_lock:
                self._query_publishers.pop(key, None)
            return
        if event.event_type == "error":
            publisher.finish(event.text)
            with self._query_publishers_lock:
                self._query_publishers.pop(key, None)
            return
        publisher.update(event.text)

    def _on_transcription_complete(self, payload: dict) -> None:
        results = self.router.handle_transcription_result(payload)
        for jid, message in results:
            message_type = (
                "groupchat" if self.command_executor.is_room_bound(jid) else "chat"
            )
            self._send_chunked(jid, message, message_type=message_type)

    def _on_image_transcription_complete(self, payload: dict) -> None:
        results = self.router.handle_image_transcription_result(payload)
        for jid, message in results:
            message_type = (
                "groupchat" if self.command_executor.is_room_bound(jid) else "chat"
            )
            self._send_chunked(jid, message, message_type=message_type)

    def _on_xmpp_session_start(self) -> None:
        for room_jid in self.command_executor.list_bound_room_jids():
            self._client.join_room(room_jid)
        xep_0050 = self._client.get_plugin("xep_0050")
        xep_0004 = self._client.get_plugin("xep_0004")
        if xep_0050 is not None:
            self._adhoc_handler.register_all(xep_0050, xep_0004)
            logger.info("xmpp ad-hoc commands registered (xep_0050)")
        else:
            logger.debug("xep_0050 plugin not available; ad-hoc commands disabled")


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
    urls = _extract_urls_from_text(normalized)
    if not urls:
        return False
    remainder = URL_PATTERN.sub(" ", normalized).strip()
    remainder = remainder.strip(".,;:!?()[]{}\"'`")
    return not remainder


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


def _resolve_query_progress_target(event: QueryProgressEvent) -> tuple[str, str]:
    room_jid = str(event.room_jid or "").strip().lower()
    if room_jid:
        return room_jid, "groupchat"
    jid = str(event.jid or "").strip()
    if not jid:
        return "", "chat"
    return jid, "chat"


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
        suffix_candidate = _extract_attachment_suffix(parsed)
        if suffix_candidate.endswith(".toml"):
            continue
        if suffix_candidate.endswith(AUDIO_EXTENSIONS):
            audio_urls.append(normalized)
            continue
        if suffix_candidate.endswith(IMAGE_EXTENSIONS):
            image_urls.append(normalized)
    return audio_urls, image_urls


def _extract_urls_from_text(text: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for raw in URL_PATTERN.findall(str(text or "")):
        candidate = str(raw or "").strip().rstrip(".,;:!?)]}\"'")
        candidate = candidate.lstrip("([{<'\"")
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        urls.append(candidate)
    return urls


def _extract_attachment_suffix(parsed_url) -> str:
    path = str(parsed_url.path or "").lower()
    if "." in path.rsplit("/", 1)[-1]:
        return path
    query_params = parse_qs(str(parsed_url.query or ""))
    for key in ("filename", "file", "name"):
        for value in query_params.get(key, []):
            candidate = str(value or "").lower()
            if "." in candidate.rsplit("/", 1)[-1]:
                return candidate
    return path


def _merge_unique_urls(urls: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in urls:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        merged.append(normalized)
    return merged
