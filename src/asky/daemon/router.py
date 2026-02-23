"""Ingress routing and policy enforcement for daemon messages."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional

from asky.config import (
    XMPP_ALLOWED_JIDS,
    XMPP_COMMAND_PREFIX,
    XMPP_IMAGE_STORAGE_DIR,
    XMPP_VOICE_STORAGE_DIR,
)
from asky.daemon.command_executor import CommandExecutor
from asky.daemon.image_transcriber import ImageTranscriber, ImageTranscriptionJob
from asky.daemon.interface_planner import (
    ACTION_COMMAND,
    InterfacePlanner,
)
from asky.daemon.transcript_manager import TranscriptManager
from asky.daemon.voice_transcriber import TranscriptionJob, VoiceTranscriber
from asky.cli.presets import expand_preset_invocation, list_presets_text

logger = logging.getLogger(__name__)
YES_TOKENS = {"yes", "y"}
NO_TOKENS = {"no", "n"}
SESSION_COMMAND_PREFIX = "/session"


class DaemonRouter:
    """Routes authorized messages to command/query execution paths."""

    def __init__(
        self,
        *,
        transcript_manager: TranscriptManager,
        command_executor: CommandExecutor,
        interface_planner: InterfacePlanner,
        voice_transcriber: VoiceTranscriber,
        image_transcriber: ImageTranscriber,
        command_prefix: str = XMPP_COMMAND_PREFIX,
        allowed_jids: Optional[list[str]] = None,
        voice_auto_yes_without_interface_model: bool = True,
    ):
        self.transcript_manager = transcript_manager
        self.command_executor = command_executor
        self.interface_planner = interface_planner
        self.voice_transcriber = voice_transcriber
        self.image_transcriber = image_transcriber
        self.command_prefix = str(command_prefix or XMPP_COMMAND_PREFIX).strip()
        self.voice_auto_yes_without_interface_model = bool(
            voice_auto_yes_without_interface_model
        )
        self.allowed_full_jids: set[str] = set()
        self.allowed_bare_jids: set[str] = set()
        for raw_jid in allowed_jids or XMPP_ALLOWED_JIDS:
            normalized = _normalize_jid(raw_jid)
            if not normalized:
                continue
            bare_value = _bare_jid(normalized)
            if "/" in normalized and bare_value != normalized:
                self.allowed_full_jids.add(normalized)
            else:
                self.allowed_bare_jids.add(bare_value)
        self._pending_transcript_confirmation: dict[tuple[str, str], int] = {}

    def is_authorized(self, jid: str) -> bool:
        normalized = _normalize_jid(jid)
        if not normalized:
            return False
        if normalized in self.allowed_full_jids:
            return True
        bare_value = _bare_jid(normalized)
        return bare_value in self.allowed_bare_jids

    def handle_text_message(
        self,
        *,
        jid: str,
        message_type: str,
        body: str,
        room_jid: Optional[str] = None,
        sender_jid: Optional[str] = None,
    ) -> Optional[str]:
        """Handle one text message and return response body."""
        normalized_type = str(message_type or "").strip().lower()
        normalized_room = _normalize_jid(room_jid or "")
        actor_jid = _normalize_jid(sender_jid or jid)

        if normalized_type == "groupchat":
            if not normalized_room:
                return None
            if not self.command_executor.is_room_bound(normalized_room):
                return None
            confirmation_key = normalized_room
        elif normalized_type == "chat":
            if not self.is_authorized(jid):
                return None
            confirmation_key = _normalize_jid(jid)
        else:
            return None

        text = str(body or "").strip()
        if not text:
            return "Error: empty message."

        inline_toml_result = self.command_executor.apply_inline_toml_if_present(
            jid=actor_jid,
            room_jid=normalized_room or None,
            body=text,
        )
        if inline_toml_result is not None:
            return inline_toml_result

        if text.startswith(SESSION_COMMAND_PREFIX):
            return self.command_executor.execute_session_command(
                jid=actor_jid,
                room_jid=normalized_room or None,
                command_text=text,
            )

        confirmation_result = self._handle_confirmation_shortcut(confirmation_key, text, actor_jid)
        if confirmation_result is not None:
            return confirmation_result

        if text.startswith("\\"):
            return self._handle_preset_invocation(
                jid=actor_jid,
                room_jid=normalized_room or None,
                text=text,
            )

        if self.interface_planner.enabled:
            if self.command_prefix and text.startswith(self.command_prefix):
                command_text = text[len(self.command_prefix) :].strip()
                if not command_text:
                    return "Error: command body is required after prefix."
                return self.command_executor.execute_command_text(
                    jid=actor_jid,
                    command_text=command_text,
                    room_jid=normalized_room or None,
                )
            action = self.interface_planner.plan(text)
            if action.action_type == ACTION_COMMAND:
                return self.command_executor.execute_command_text(
                    jid=actor_jid,
                    command_text=action.command_text,
                    room_jid=normalized_room or None,
                )
            return self.command_executor.execute_query_text(
                jid=actor_jid,
                room_jid=normalized_room or None,
                query_text=action.query_text,
            )

        if _looks_like_command(text):
            return self.command_executor.execute_command_text(
                jid=actor_jid,
                room_jid=normalized_room or None,
                command_text=text,
            )

        return self.command_executor.execute_query_text(
            jid=actor_jid,
            room_jid=normalized_room or None,
            query_text=text,
        )

    def handle_toml_url_message(
        self,
        *,
        jid: str,
        message_type: str,
        url: str,
        room_jid: Optional[str] = None,
        sender_jid: Optional[str] = None,
    ) -> Optional[str]:
        """Apply one uploaded TOML URL payload for chat/group conversation."""
        normalized_type = str(message_type or "").strip().lower()
        normalized_room = _normalize_jid(room_jid or "")
        actor_jid = _normalize_jid(sender_jid or jid)
        if normalized_type == "groupchat":
            if not normalized_room:
                return None
            if not self.command_executor.is_room_bound(normalized_room):
                return None
        elif normalized_type == "chat":
            if not self.is_authorized(jid):
                return None
        else:
            return None
        return self.command_executor.apply_toml_url(
            jid=actor_jid,
            room_jid=normalized_room or None,
            url=url,
        )

    def handle_room_invite(self, *, room_jid: str, inviter_jid: str) -> bool:
        """Authorize trusted room invite and ensure room binding exists."""
        normalized_room = _normalize_jid(room_jid)
        normalized_inviter = _normalize_jid(inviter_jid)
        if not normalized_room or not normalized_inviter:
            return False
        if not self.is_authorized(normalized_inviter):
            return False
        self.command_executor.ensure_room_binding(normalized_room)
        return True

    def handle_audio_message(
        self,
        *,
        jid: str,
        message_type: str,
        audio_url: str,
        room_jid: Optional[str] = None,
        sender_jid: Optional[str] = None,
    ) -> Optional[str]:
        """Queue voice transcription job and return immediate acknowledgement."""
        normalized_type = str(message_type or "").strip().lower()
        normalized_room = _normalize_jid(room_jid or "")
        if normalized_type == "groupchat":
            if not normalized_room:
                return None
            if not self.command_executor.is_room_bound(normalized_room):
                return None
            conversation_id = normalized_room
        elif normalized_type == "chat":
            if not self.is_authorized(jid):
                return None
            conversation_id = _normalize_jid(jid)
        else:
            return None
        if not self.voice_transcriber.enabled:
            return "Voice transcription is disabled."

        audio_url = str(audio_url or "").strip()
        if not audio_url:
            return "Error: audio URL is required."

        effective_sender = _normalize_jid(sender_jid or jid)
        digest = hashlib.sha1(audio_url.encode("utf-8")).hexdigest()[:16]
        artifact_path = (
            Path(XMPP_IMAGE_STORAGE_DIR).expanduser() / conversation_id.replace("/", "_")
        )
        file_path = artifact_path / f"transcript_{digest}.audio"
        pending = self.transcript_manager.create_pending_transcript(
            jid=conversation_id,
            audio_url=audio_url,
            audio_path=str(file_path),
        )
        self.voice_transcriber.enqueue(
            TranscriptionJob(
                jid=conversation_id,
                transcript_id=pending.session_transcript_id,
                audio_url=audio_url,
                audio_path=str(file_path),
                sender_jid=effective_sender,
            )
        )
        return (
            f"Queued transcription job #at{pending.session_transcript_id} for audio #a{pending.session_transcript_id}. "
            "I will notify you when it is ready."
        )

    def handle_image_message(
        self,
        *,
        jid: str,
        message_type: str,
        image_url: str,
        room_jid: Optional[str] = None,
    ) -> Optional[str]:
        """Queue image transcription job and return immediate acknowledgement."""
        normalized_type = str(message_type or "").strip().lower()
        normalized_room = _normalize_jid(room_jid or "")
        if normalized_type == "groupchat":
            if not normalized_room:
                return None
            if not self.command_executor.is_room_bound(normalized_room):
                return None
            conversation_id = normalized_room
        elif normalized_type == "chat":
            if not self.is_authorized(jid):
                return None
            conversation_id = _normalize_jid(jid)
        else:
            return None
        if not self.image_transcriber.enabled:
            return "Image transcription is disabled."

        image_url = str(image_url or "").strip()
        if not image_url:
            return "Error: image URL is required."

        digest = hashlib.sha1(image_url.encode("utf-8")).hexdigest()[:16]
        artifact_path = (
            Path(XMPP_VOICE_STORAGE_DIR).expanduser() / conversation_id.replace("/", "_")
        )
        file_path = artifact_path / f"image_{digest}.bin"
        pending = self.transcript_manager.create_pending_image_transcript(
            jid=conversation_id,
            image_url=image_url,
            image_path=str(file_path),
        )
        self.image_transcriber.enqueue(
            ImageTranscriptionJob(
                jid=conversation_id,
                image_id=pending.session_image_id,
                image_url=image_url,
                image_path=str(file_path),
            )
        )
        return (
            f"Queued image transcription #it{pending.session_image_id} for image #i{pending.session_image_id}. "
            "I will notify you when it is ready."
        )

    def handle_transcription_result(self, payload: dict) -> Optional[tuple[str, str]]:
        """Persist transcription completion and build user-facing notification."""
        jid = str(payload.get("jid", "") or "").strip()
        if not jid:
            return None
        sender_jid = str(payload.get("sender_jid", "") or "").strip()
        transcript_id = int(payload.get("transcript_id", 0) or 0)
        status = str(payload.get("status", "") or "").strip().lower()
        if status == "completed":
            text = str(payload.get("transcript_text", "") or "").strip()
            duration_seconds = payload.get("duration_seconds")
            record = self.transcript_manager.mark_transcript_completed(
                jid=jid,
                transcript_id=transcript_id,
                transcript_text=text,
                duration_seconds=duration_seconds,
            )
            if record is None:
                return None
            if self._should_auto_run_completed_transcript():
                self.transcript_manager.mark_used(jid=jid, transcript_id=transcript_id)
                if not text:
                    return (
                        jid,
                        (
                            f"Transcript #at{transcript_id} is empty. "
                            f"Use `transcript show #at{transcript_id}` to inspect."
                        ),
                    )
                answer = self.command_executor.execute_query_text(
                    jid=jid,
                    room_jid=(jid if self.command_executor.is_room_bound(jid) else None),
                    query_text=text,
                )
                return (jid, answer)
            self._pending_transcript_confirmation[(jid, sender_jid)] = transcript_id
            preview = record.transcript_text or ""
            return (
                jid,
                (
                    f"Transcript #at{transcript_id} of audio #a{transcript_id} ready.\n"
                    f"{preview}\n\n"
                    f"Reply 'yes' to run transcript #at{transcript_id} as a query now.\n"
                    f"Reply 'no' to keep it for later.\n"
                    f"Or run: transcript use #at{transcript_id}"
                ),
            )

        error_text = str(payload.get("error", "") or "Unknown transcription error")
        self.transcript_manager.mark_transcript_failed(
            jid=jid,
            transcript_id=transcript_id,
            error=error_text,
        )
        return (jid, f"Transcript #at{transcript_id} failed: {error_text}")

    def handle_image_transcription_result(self, payload: dict) -> Optional[tuple[str, str]]:
        """Persist image transcription completion and build user-facing notification."""
        jid = str(payload.get("jid", "") or "").strip()
        if not jid:
            return None
        image_id = int(payload.get("image_id", 0) or 0)
        status = str(payload.get("status", "") or "").strip().lower()
        if status == "completed":
            text = str(payload.get("transcript_text", "") or "").strip()
            duration_seconds = payload.get("duration_seconds")
            record = self.transcript_manager.mark_image_transcript_completed(
                jid=jid,
                image_id=image_id,
                transcript_text=text,
                duration_seconds=duration_seconds,
            )
            if record is None:
                return None
            return (
                jid,
                f"transcript #it{image_id} of image #i{image_id}:\n{text}",
            )

        error_text = str(payload.get("error", "") or "Unknown image transcription error")
        self.transcript_manager.mark_image_transcript_failed(
            jid=jid,
            image_id=image_id,
            error=error_text,
        )
        return (jid, f"Transcript #it{image_id} failed: {error_text}")

    def _handle_confirmation_shortcut(
        self,
        conversation_key: str,
        text: str,
        sender_jid: str = "",
    ) -> Optional[str]:
        pending_key = (conversation_key, sender_jid)
        pending_id = self._pending_transcript_confirmation.get(pending_key)
        if pending_id is None:
            return None
        normalized = text.strip().lower()
        if normalized in YES_TOKENS:
            self._pending_transcript_confirmation.pop(pending_key, None)
            room_jid = (
                conversation_key
                if self.command_executor.is_room_bound(conversation_key)
                else None
            )
            return self.command_executor.execute_command_text(
                jid=conversation_key,
                room_jid=room_jid,
                command_text=f"transcript use #at{pending_id}",
            )
        if normalized in NO_TOKENS:
            self._pending_transcript_confirmation.pop(pending_key, None)
            return (
                f"Transcript #at{pending_id} kept without running. "
                f"Use `transcript use #at{pending_id}` anytime."
            )
        return None

    def _should_auto_run_completed_transcript(self) -> bool:
        if not self.voice_auto_yes_without_interface_model:
            return False
        return not self.interface_planner.enabled

    def _handle_preset_invocation(
        self,
        *,
        jid: str,
        room_jid: Optional[str],
        text: str,
    ) -> str:
        expansion = expand_preset_invocation(text)
        if not expansion.matched:
            return self.command_executor.execute_query_text(
                jid=jid,
                room_jid=room_jid,
                query_text=text,
            )
        if expansion.command_text == "\\presets":
            return list_presets_text()
        if expansion.error:
            return f"Error: {expansion.error}"
        command_text = str(expansion.command_text or "").strip()
        if not command_text:
            return "Error: preset expansion produced an empty command."
        return self.command_executor.execute_command_text(
            jid=jid,
            room_jid=room_jid,
            command_text=command_text,
        )


def _looks_like_command(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    first_token = stripped.split(maxsplit=1)[0].lower()
    command_tokens = {
        "/session",
        "transcript",
        "history",
        "session",
        "--history",
        "-h",
        "--print-answer",
        "-pa",
        "--print-session",
        "-ps",
        "--query-corpus",
        "--summarize-section",
        "-r",
        "--research",
        "-ss",
        "--sticky-session",
        "-rs",
        "--resume-session",
    }
    return first_token.startswith("-") or first_token in command_tokens


def _normalize_jid(value: str) -> str:
    return str(value or "").strip()


def _bare_jid(value: str) -> str:
    normalized = _normalize_jid(value)
    if "/" in normalized:
        return normalized.split("/", 1)[0].strip()
    return normalized
