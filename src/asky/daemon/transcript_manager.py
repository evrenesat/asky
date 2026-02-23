"""Transcript/session lifecycle support for daemon mode."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from asky.config import XMPP_TRANSCRIPT_MAX_PER_SESSION
from asky.daemon.session_profile_manager import SessionProfileManager
from asky.storage import (
    create_image_transcript,
    create_transcript,
    get_image_transcript,
    get_transcript,
    list_image_transcripts,
    list_transcripts,
    prune_image_transcripts,
    prune_transcripts,
    update_image_transcript,
    update_transcript,
)
from asky.storage.interface import ImageTranscriptRecord, TranscriptRecord

logger = logging.getLogger(__name__)


class TranscriptManager:
    """Persist transcript state and map daemon senders to sessions."""

    def __init__(
        self,
        transcript_cap: Optional[int] = None,
        session_profile_manager: Optional[SessionProfileManager] = None,
    ):
        self.session_profile_manager = session_profile_manager or SessionProfileManager()
        self._transcript_cap = int(
            transcript_cap
            if transcript_cap is not None
            else XMPP_TRANSCRIPT_MAX_PER_SESSION
        )

    def get_or_create_session_id(self, jid: str) -> int:
        """Return persistent session id for a sender JID."""
        normalized_jid = str(jid).strip()
        if not normalized_jid:
            raise ValueError("jid is required")
        return self.session_profile_manager.get_or_create_direct_session_id(normalized_jid)

    def get_or_create_room_session_id(self, room_jid: str) -> int:
        """Return persistent session id for a room JID."""
        normalized = str(room_jid or "").strip()
        if not normalized:
            raise ValueError("room_jid is required")
        return self.session_profile_manager.get_or_create_room_session_id(normalized)

    def bind_room_to_session(self, *, room_jid: str, session_id: int) -> None:
        """Bind room to a specific existing session."""
        self.session_profile_manager.bind_room_to_session(
            room_jid=room_jid,
            session_id=session_id,
        )

    def is_room_bound(self, room_jid: str) -> bool:
        """Return whether room has a persisted session binding."""
        return self.session_profile_manager.is_room_bound(room_jid)

    def list_bound_room_jids(self) -> list[str]:
        """List persisted room JIDs with active session bindings."""
        return self.session_profile_manager.list_bound_room_jids()

    def create_pending_transcript(
        self,
        *,
        jid: str,
        audio_url: str,
        audio_path: str,
    ) -> TranscriptRecord:
        """Create a pending transcript row."""
        session_id = self.get_or_create_session_id(jid)
        record = create_transcript(
            session_id=session_id,
            jid=jid,
            audio_url=audio_url,
            audio_path=audio_path,
            status="pending",
        )
        self._prune_if_needed(session_id)
        return record

    def create_pending_image_transcript(
        self,
        *,
        jid: str,
        image_url: str,
        image_path: str,
    ) -> ImageTranscriptRecord:
        """Create a pending image transcript row."""
        session_id = self.get_or_create_session_id(jid)
        record = create_image_transcript(
            session_id=session_id,
            jid=jid,
            image_url=image_url,
            image_path=image_path,
            status="pending",
        )
        self._prune_if_needed(session_id)
        return record

    def mark_transcript_completed(
        self,
        *,
        jid: str,
        transcript_id: int,
        transcript_text: str,
        duration_seconds: Optional[float] = None,
    ) -> Optional[TranscriptRecord]:
        """Mark transcript as completed and persist text."""
        session_id = self.get_or_create_session_id(jid)
        updated = update_transcript(
            session_id=session_id,
            session_transcript_id=int(transcript_id),
            status="completed",
            transcript_text=transcript_text,
            duration_seconds=duration_seconds,
        )
        self._prune_if_needed(session_id)
        return updated

    def mark_transcript_failed(
        self,
        *,
        jid: str,
        transcript_id: int,
        error: str,
    ) -> Optional[TranscriptRecord]:
        """Mark transcript job as failed."""
        session_id = self.get_or_create_session_id(jid)
        updated = update_transcript(
            session_id=session_id,
            session_transcript_id=int(transcript_id),
            status="failed",
            error=error,
        )
        self._prune_if_needed(session_id)
        return updated

    def mark_image_transcript_completed(
        self,
        *,
        jid: str,
        image_id: int,
        transcript_text: str,
        duration_seconds: Optional[float] = None,
    ) -> Optional[ImageTranscriptRecord]:
        """Mark image transcript as completed and persist text."""
        session_id = self.get_or_create_session_id(jid)
        updated = update_image_transcript(
            session_id=session_id,
            session_image_id=int(image_id),
            status="completed",
            transcript_text=transcript_text,
            duration_seconds=duration_seconds,
        )
        self._prune_if_needed(session_id)
        return updated

    def mark_image_transcript_failed(
        self,
        *,
        jid: str,
        image_id: int,
        error: str,
    ) -> Optional[ImageTranscriptRecord]:
        """Mark image transcript job as failed."""
        session_id = self.get_or_create_session_id(jid)
        updated = update_image_transcript(
            session_id=session_id,
            session_image_id=int(image_id),
            status="failed",
            error=error,
        )
        self._prune_if_needed(session_id)
        return updated

    def list_for_jid(self, jid: str, limit: int = 20) -> list[TranscriptRecord]:
        """List transcript rows for one sender."""
        session_id = self.get_or_create_session_id(jid)
        return list_transcripts(session_id=session_id, limit=limit)

    def get_for_jid(self, jid: str, transcript_id: int) -> Optional[TranscriptRecord]:
        """Fetch one transcript by sender and session transcript id."""
        session_id = self.get_or_create_session_id(jid)
        return get_transcript(
            session_id=session_id,
            session_transcript_id=int(transcript_id),
        )

    def list_images_for_jid(self, jid: str, limit: int = 20) -> list[ImageTranscriptRecord]:
        """List image transcript rows for one sender."""
        session_id = self.get_or_create_session_id(jid)
        return list_image_transcripts(session_id=session_id, limit=limit)

    def get_image_for_jid(self, jid: str, image_id: int) -> Optional[ImageTranscriptRecord]:
        """Fetch one image transcript by sender and session image id."""
        session_id = self.get_or_create_session_id(jid)
        return get_image_transcript(
            session_id=session_id,
            session_image_id=int(image_id),
        )

    def mark_used(self, *, jid: str, transcript_id: int) -> Optional[TranscriptRecord]:
        """Mark one transcript as consumed by a user command."""
        session_id = self.get_or_create_session_id(jid)
        return update_transcript(
            session_id=session_id,
            session_transcript_id=int(transcript_id),
            status="completed",
            used=True,
        )

    def mark_image_used(
        self,
        *,
        jid: str,
        image_id: int,
    ) -> Optional[ImageTranscriptRecord]:
        """Mark one image transcript as consumed by pointer usage."""
        session_id = self.get_or_create_session_id(jid)
        return update_image_transcript(
            session_id=session_id,
            session_image_id=int(image_id),
            status="completed",
            used=True,
        )

    def clear_for_jid(self, jid: str) -> list[TranscriptRecord]:
        """Remove transcript records for one sender by pruning keep=0."""
        session_id = self.get_or_create_session_id(jid)
        deleted = prune_transcripts(session_id=session_id, keep=0)
        deleted_images = prune_image_transcripts(session_id=session_id, keep=0)
        self._delete_audio_artifacts(deleted)
        self._delete_image_artifacts(deleted_images)
        return deleted

    def _prune_if_needed(self, session_id: int) -> None:
        if self._transcript_cap < 0:
            return
        deleted = prune_transcripts(session_id=session_id, keep=self._transcript_cap)
        deleted_images = prune_image_transcripts(
            session_id=session_id, keep=self._transcript_cap
        )
        if deleted:
            self._delete_audio_artifacts(deleted)
        if deleted_images:
            self._delete_image_artifacts(deleted_images)

    def _delete_audio_artifacts(self, records: list[TranscriptRecord]) -> None:
        for record in records:
            path_str = str(record.audio_path or "").strip()
            if not path_str:
                continue
            path = Path(path_str).expanduser()
            if not path.exists():
                continue
            try:
                path.unlink()
            except Exception as exc:
                logger.debug("failed to delete transcript artifact '%s': %s", path, exc)

    def _delete_image_artifacts(self, records: list[ImageTranscriptRecord]) -> None:
        for record in records:
            path_str = str(record.image_path or "").strip()
            if not path_str:
                continue
            path = Path(path_str).expanduser()
            if not path.exists():
                continue
            try:
                path.unlink()
            except Exception as exc:
                logger.debug(
                    "failed to delete image transcript artifact '%s': %s", path, exc
                )
