"""Background voice transcription workers for daemon mode."""

from __future__ import annotations

import logging
import mimetypes
import os
import platform
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)
DOWNLOAD_TIMEOUT_SECONDS = 60
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
TRANSCRIPTION_ERROR_MACOS_ONLY = "Voice transcription currently supports macOS only."
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
class TranscriptionJob:
    """Queued transcription request."""

    jid: str
    transcript_id: int
    audio_url: str
    audio_path: str
    sender_jid: str = ""


class VoiceTranscriber:
    """Consumes audio URLs asynchronously and emits transcription callbacks."""

    def __init__(
        self,
        *,
        enabled: bool,
        workers: int,
        max_size_mb: int,
        model: str,
        language: str,
        storage_dir: Path,
        allowed_mime_types: list[str],
        completion_callback: Callable[[dict], None],
        hf_token_env: str = HF_TOKEN_ENV_DEFAULT,
        hf_token: str = "",
    ):
        self.enabled = bool(enabled)
        self.workers = max(1, int(workers))
        self.max_size_bytes = max(1, int(max_size_mb)) * 1024 * 1024
        self.model = str(model or "").strip()
        self.language = str(language or "").strip()
        self.storage_dir = Path(storage_dir).expanduser()
        self.hf_token_env = str(hf_token_env or HF_TOKEN_ENV_DEFAULT).strip()
        self.hf_token = str(hf_token or "").strip()
        self.allowed_mime_types = {str(item).strip().lower() for item in allowed_mime_types if str(item).strip()}
        self.completion_callback = completion_callback
        self._queue: queue.Queue[Optional[TranscriptionJob]] = queue.Queue()
        self._started = False
        self._shutdown = False
        self._workers: list[threading.Thread] = []

    def start(self) -> None:
        """Start background worker threads once."""
        if self._started:
            return
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._started = True
        for index in range(self.workers):
            thread = threading.Thread(
                target=self._worker_loop,
                name=f"asky-transcriber-{index+1}",
                daemon=True,
            )
            thread.start()
            self._workers.append(thread)

    def enqueue(self, job: TranscriptionJob) -> None:
        """Queue a new transcription request."""
        if not self.enabled:
            self._emit(
                jid=job.jid,
                transcript_id=job.transcript_id,
                status="failed",
                error="Voice transcription is disabled.",
                audio_path=job.audio_path,
                sender_jid=job.sender_jid,
            )
            return
        self.start()
        self._queue.put(job)

    def shutdown(self, timeout: float = 5.0) -> None:
        """Signal worker threads to exit and wait for them to finish."""
        if not self._started:
            return
        self._shutdown = True
        for _ in self._workers:
            self._queue.put(None)
        for thread in self._workers:
            thread.join(timeout=timeout)
        self._workers.clear()

    def _worker_loop(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                self._queue.task_done()
                break
            try:
                self._run_job(job)
            except Exception as exc:
                logger.exception("voice transcription worker failure: %s", exc)
                self._emit(
                    jid=job.jid,
                    transcript_id=job.transcript_id,
                    status="failed",
                    error=str(exc),
                    audio_path=job.audio_path,
                    sender_jid=job.sender_jid,
                )
            finally:
                self._queue.task_done()

    def _run_job(self, job: TranscriptionJob) -> None:
        if platform.system().lower() != "darwin":
            self._emit(
                jid=job.jid,
                transcript_id=job.transcript_id,
                status="failed",
                error=TRANSCRIPTION_ERROR_MACOS_ONLY,
                audio_path=job.audio_path,
                sender_jid=job.sender_jid,
            )
            return

        file_path = self._download_audio(job.audio_url, Path(job.audio_path))
        started = time.perf_counter()
        transcript_text = self._transcribe_file(file_path)
        elapsed_seconds = time.perf_counter() - started
        self._emit(
            jid=job.jid,
            transcript_id=job.transcript_id,
            status="completed",
            transcript_text=transcript_text,
            duration_seconds=elapsed_seconds,
            audio_path=str(file_path),
            sender_jid=job.sender_jid,
        )

    def _download_audio(self, url: str, target_path: Path) -> Path:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            response.raise_for_status()
            content_type = str(response.headers.get("Content-Type", "")).split(";")[0].strip().lower()
            normalized_content_type = self._resolve_content_type(
                content_type=content_type,
                url=url,
                target_path=target_path,
            )
            if (
                self.allowed_mime_types
                and normalized_content_type
                and normalized_content_type not in self.allowed_mime_types
            ):
                raise RuntimeError(f"Unsupported audio MIME type: {content_type}")
            content_length = response.headers.get("Content-Length")
            if content_length:
                total_size = int(content_length)
                if total_size > self.max_size_bytes:
                    raise RuntimeError(
                        f"Audio payload exceeds size limit ({total_size} bytes > {self.max_size_bytes})."
                    )

            written = 0
            with target_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > self.max_size_bytes:
                        raise RuntimeError(
                            f"Audio payload exceeds size limit ({written} bytes > {self.max_size_bytes})."
                        )
                    handle.write(chunk)
        return target_path

    def _resolve_content_type(
        self,
        *,
        content_type: str,
        url: str,
        target_path: Path,
    ) -> str:
        normalized = self._normalize_inferred_mime(content_type)
        if normalized != GENERIC_BINARY_MIME_TYPE:
            return normalized

        inferred = self._infer_mime_type_from_url_or_path(url=url, target_path=target_path)
        if not inferred:
            return normalized
        return inferred

    def _infer_mime_type_from_url_or_path(self, *, url: str, target_path: Path) -> str:
        parsed = urlparse(str(url or ""))
        url_path = parsed.path or ""
        extension_mime = EXTENSION_TO_AUDIO_MIME.get(Path(url_path).suffix.lower(), "")
        if extension_mime:
            return extension_mime

        guessed_from_url, _ = mimetypes.guess_type(url_path)
        if guessed_from_url:
            normalized = self._normalize_inferred_mime(str(guessed_from_url))
            if normalized:
                return normalized

        extension_mime = EXTENSION_TO_AUDIO_MIME.get(target_path.suffix.lower(), "")
        if extension_mime:
            return extension_mime
        guessed_from_path, _ = mimetypes.guess_type(str(target_path))
        if guessed_from_path:
            normalized = self._normalize_inferred_mime(str(guessed_from_path))
            if normalized:
                return normalized
        return ""

    def _normalize_inferred_mime(self, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if not normalized:
            return ""
        return INFERRED_MIME_ALIASES.get(normalized, normalized)

    def _transcribe_file(self, file_path: Path) -> str:
        self._apply_hf_token_env()
        try:
            import mlx_whisper  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "mlx-whisper is required for voice transcription. Install asky-cli[voice]."
            ) from exc

        kwargs = {"path_or_hf_repo": self.model}
        if self.language:
            kwargs["language"] = self.language
        result = mlx_whisper.transcribe(str(file_path), **kwargs)
        if isinstance(result, dict):
            text = str(result.get("text", "") or "").strip()
            if text:
                return text
        return ""

    def _apply_hf_token_env(self) -> None:
        token = str(self.hf_token or "").strip()
        if not token:
            return

        custom_env = str(self.hf_token_env or HF_TOKEN_ENV_DEFAULT).strip()
        if custom_env:
            os.environ[custom_env] = token
        for env_name in HF_TOKEN_ENV_ALIASES:
            os.environ[env_name] = token

    def _emit(
        self,
        *,
        jid: str,
        transcript_id: int,
        status: str,
        transcript_text: str = "",
        error: str = "",
        duration_seconds: Optional[float] = None,
        audio_path: str = "",
        sender_jid: str = "",
    ) -> None:
        payload = {
            "jid": jid,
            "transcript_id": transcript_id,
            "status": status,
            "transcript_text": transcript_text,
            "error": error,
            "duration_seconds": duration_seconds,
            "audio_path": audio_path,
            "sender_jid": sender_jid,
        }
        try:
            self.completion_callback(payload)
        except Exception:
            logger.exception("voice completion callback failed")
