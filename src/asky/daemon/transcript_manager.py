"""Transcript/session lifecycle support for daemon mode."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from asky.config import DEFAULT_MODEL, XMPP_TRANSCRIPT_MAX_PER_SESSION
from asky.storage import (
    create_session,
    create_transcript,
    get_session_by_name,
    get_transcript,
    list_transcripts,
    prune_transcripts,
    update_transcript,
)
from asky.storage.interface import TranscriptRecord

logger = logging.getLogger(__name__)
JID_SESSION_PREFIX = "xmpp:"


class TranscriptManager:
    """Persist transcript state and map daemon senders to sessions."""

    def __init__(self, transcript_cap: Optional[int] = None):
        self._jid_to_session_id: dict[str, int] = {}
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
        cached = self._jid_to_session_id.get(normalized_jid)
        if cached is not None:
            return cached

        session_name = f"{JID_SESSION_PREFIX}{normalized_jid}"
        session = get_session_by_name(session_name)
        if session is None:
            session_id = create_session(model=DEFAULT_MODEL, name=session_name)
        else:
            session_id = int(session.id)
        self._jid_to_session_id[normalized_jid] = session_id
        return session_id

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

    def mark_used(self, *, jid: str, transcript_id: int) -> Optional[TranscriptRecord]:
        """Mark one transcript as consumed by a user command."""
        session_id = self.get_or_create_session_id(jid)
        return update_transcript(
            session_id=session_id,
            session_transcript_id=int(transcript_id),
            status="completed",
            used=True,
        )

    def clear_for_jid(self, jid: str) -> list[TranscriptRecord]:
        """Remove transcript records for one sender by pruning keep=0."""
        session_id = self.get_or_create_session_id(jid)
        deleted = prune_transcripts(session_id=session_id, keep=0)
        self._delete_artifacts(deleted)
        return deleted

    def _prune_if_needed(self, session_id: int) -> None:
        if self._transcript_cap < 0:
            return
        deleted = prune_transcripts(session_id=session_id, keep=self._transcript_cap)
        if deleted:
            self._delete_artifacts(deleted)

    def _delete_artifacts(self, records: list[TranscriptRecord]) -> None:
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
