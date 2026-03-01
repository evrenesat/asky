"""Core voice transcription service and OS-strategy abstraction."""

from __future__ import annotations

import logging
import mimetypes
import os
import platform
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Set
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT_SECONDS = 60
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
GENERIC_BINARY_MIME_TYPE = "application/octet-stream"

EXTENSION_TO_AUDIO_MIME = {
    ".m4a": "audio/x-m4a",
    ".mp3": "audio/mpeg",
    ".mp4": "audio/mp4",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".opus": "audio/ogg",
}

INFERRED_MIME_ALIASES = {
    "audio/mp4a-latm": "audio/x-m4a",
    "video/mp4": "audio/mp4",
    "video/webm": "audio/webm",
    "audio/x-flac": "audio/flac",
    "audio/x-wav": "audio/wav",
    "audio/wave": "audio/wav",
    "application/ogg": "audio/ogg",
}

HF_TOKEN_ENV_DEFAULT = "HF_TOKEN"
HF_TOKEN_ENV_ALIASES = ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN")


@dataclass(frozen=True)
class VoiceTranscriptionJob:
    """Queued transcription request."""

    jid: str
    transcript_id: int
    audio_url: str
    audio_path: str
    sender_jid: str = ""


class TranscriptionStrategy(Protocol):
    """Protocol for platform-specific transcription implementations."""

    def transcribe(
        self,
        file_path: Path,
        model: str,
        language: Optional[str],
        hf_token: Optional[str] = None,
        hf_token_env: Optional[str] = None,
    ) -> str:
        """Transcribe an audio file to text."""
        ...


class MacOSMLXWhisperStrategy:
    """Transcription strategy using mlx-whisper on macOS."""

    def transcribe(
        self,
        file_path: Path,
        model: str,
        language: Optional[str],
        hf_token: Optional[str] = None,
        hf_token_env: Optional[str] = None,
    ) -> str:
        if hf_token:
            self._apply_hf_token_env(hf_token, hf_token_env)

        try:
            import mlx_whisper  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "mlx-whisper is required for voice transcription. Install asky-cli[voice]."
            ) from exc

        kwargs: Dict[str, Any] = {"path_or_hf_repo": model}
        if language:
            kwargs["language"] = language

        result = mlx_whisper.transcribe(str(file_path), **kwargs)
        if isinstance(result, dict):
            text = str(result.get("text", "") or "").strip()
            if text:
                return text
        return ""

    def _apply_hf_token_env(self, token: str, custom_env: Optional[str]) -> None:
        token = token.strip()
        if not token:
            return

        env_key = str(custom_env or HF_TOKEN_ENV_DEFAULT).strip()
        os.environ[env_key] = token
        for alias in HF_TOKEN_ENV_ALIASES:
            os.environ[alias] = token


class UnsupportedOSStrategy:
    """Fallback strategy for unsupported operating systems."""

    def transcribe(
        self,
        file_path: Path,
        model: str,
        language: Optional[str],
        hf_token: Optional[str] = None,
        hf_token_env: Optional[str] = None,
    ) -> str:
        raise RuntimeError(
            f"Voice transcription is not yet supported on {platform.system()}."
        )


def get_transcription_strategy() -> TranscriptionStrategy:
    """Resolve the appropriate transcription strategy for the current OS."""
    if platform.system().lower() == "darwin":
        return MacOSMLXWhisperStrategy()
    return UnsupportedOSStrategy()


class VoiceTranscriberService:
    """Service for audio transcription with support for synchronous and async jobs."""

    def __init__(
        self,
        *,
        model: str,
        language: str = "",
        max_size_mb: int = 500,
        allowed_mime_types: Optional[List[str]] = None,
        hf_token: str = "",
        hf_token_env: str = HF_TOKEN_ENV_DEFAULT,
        strategy: Optional[TranscriptionStrategy] = None,
        preferred_workers: int = 1,
    ):
        self.model = model.strip()
        self.language = language.strip()
        self.max_size_bytes = max(1, int(max_size_mb)) * 1024 * 1024
        self.allowed_mime_types = {
            m.strip().lower() for m in (allowed_mime_types or []) if m.strip()
        }
        self.hf_token = hf_token.strip()
        self.hf_token_env = hf_token_env.strip() or HF_TOKEN_ENV_DEFAULT
        self.strategy = strategy or get_transcription_strategy()
        self.preferred_workers = max(1, int(preferred_workers))

    def transcribe_url(self, url: str, target_path: Path) -> str:
        """Synchronously download and transcribe an audio URL."""
        file_path = self.download_audio(url, target_path)
        return self.strategy.transcribe(
            file_path,
            model=self.model,
            language=self.language,
            hf_token=self.hf_token,
            hf_token_env=self.hf_token_env,
        )

    def download_audio(self, url: str, target_path: Path) -> Path:
        """Download audio from URL with validation."""
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(
            url, stream=True, timeout=DOWNLOAD_TIMEOUT_SECONDS
        ) as response:
            response.raise_for_status()
            content_type = (
                str(response.headers.get("Content-Type", ""))
                .split(";")[0]
                .strip()
                .lower()
            )
            normalized_mime = self._resolve_mime(content_type, url, target_path)

            if (
                self.allowed_mime_types
                and normalized_mime
                and normalized_mime not in self.allowed_mime_types
            ):
                raise RuntimeError(f"Unsupported audio MIME type: {normalized_mime}")

            content_length = response.headers.get("Content-Length")
            if content_length:
                if int(content_length) > self.max_size_bytes:
                    raise RuntimeError(
                        f"Audio exceeds size limit ({content_length} bytes)."
                    )

            written = 0
            with target_path.open("wb") as f:
                for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > self.max_size_bytes:
                        raise RuntimeError("Audio exceeds size limit during download.")
                    f.write(chunk)
        return target_path

    def _resolve_mime(self, content_type: str, url: str, path: Path) -> str:
        mime = INFERRED_MIME_ALIASES.get(content_type, content_type)
        if mime != GENERIC_BINARY_MIME_TYPE:
            return mime

        # Infer from extension
        ext = path.suffix.lower() or Path(urlparse(url).path).suffix.lower()
        return EXTENSION_TO_AUDIO_MIME.get(ext, GENERIC_BINARY_MIME_TYPE)

    def create_worker(
        self,
        completion_callback: Callable[[Dict[str, Any]], None],
        workers: Optional[int] = None,
        enabled: bool = True,
    ) -> VoiceTranscriberWorker:
        """Create a background worker for asynchronous jobs."""
        return VoiceTranscriberWorker(
            service=self,
            workers=workers if workers is not None else self.preferred_workers,
            completion_callback=completion_callback,
            enabled=enabled,
        )


class VoiceTranscriberWorker:
    """Background worker pool for processing VoiceTranscriptionJob instances."""

    def __init__(
        self,
        service: VoiceTranscriberService,
        workers: int,
        completion_callback: Callable[[Dict[str, Any]], None],
        enabled: bool = True,
    ):
        self.service = service
        self.workers = max(1, workers)
        self.completion_callback = completion_callback
        self.enabled = enabled
        self._queue: queue.Queue[Optional[VoiceTranscriptionJob]] = queue.Queue()
        self._threads: List[threading.Thread] = []
        self._started = False
        self._shutdown = False

    def start(self) -> None:
        """Start background threads."""
        if self._started:
            return
        self._started = True
        for i in range(self.workers):
            t = threading.Thread(
                target=self._run_loop,
                name=f"asky-voice-worker-{i}",
                daemon=True,
            )
            t.start()
            self._threads.append(t)

    def enqueue(self, job: VoiceTranscriptionJob | Dict[str, Any]) -> None:
        """Queue a job for background processing."""
        normalized_job = self._coerce_job(job)
        if not self.enabled:
            self._emit(normalized_job, "failed", error="Voice transcription is disabled.")
            return
        self.start()
        self._queue.put(normalized_job)

    def shutdown(self, timeout: float = 5.0) -> None:
        """Stop all workers."""
        self._shutdown = True
        for _ in self._threads:
            self._queue.put(None)
        for t in self._threads:
            t.join(timeout=timeout)
        self._threads.clear()

    def _run_loop(self) -> None:
        while not self._shutdown:
            job = self._queue.get()
            if job is None:
                break
            try:
                start_time = time.perf_counter()
                text = self.service.transcribe_url(job.audio_url, Path(job.audio_path))
                elapsed = time.perf_counter() - start_time
                self._emit(job, "completed", text=text, elapsed=elapsed)
            except Exception as exc:
                logger.exception("Voice worker job failed")
                self._emit(job, "failed", error=str(exc))
            finally:
                self._queue.task_done()

    def _coerce_job(self, job: VoiceTranscriptionJob | Dict[str, Any]) -> VoiceTranscriptionJob:
        if isinstance(job, VoiceTranscriptionJob):
            return job
        return VoiceTranscriptionJob(
            jid=str(job["jid"]),
            transcript_id=int(job["transcript_id"]),
            audio_url=str(job["audio_url"]),
            audio_path=str(job["audio_path"]),
            sender_jid=str(job.get("sender_jid", "")),
        )

    def _emit(
        self,
        job: VoiceTranscriptionJob,
        status: str,
        text: str = "",
        error: str = "",
        elapsed: float = 0.0,
    ) -> None:
        payload = {
            "jid": job.jid,
            "transcript_id": job.transcript_id,
            "status": status,
            "transcript_text": text,
            "error": error,
            "duration_seconds": elapsed,
            "audio_path": job.audio_path,
            "sender_jid": job.sender_jid,
        }
        try:
            self.completion_callback(payload)
        except Exception:
            logger.exception("Voice worker callback failed")
