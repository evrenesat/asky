"""Background image transcription workers for daemon mode."""

from __future__ import annotations

import base64
import logging
import mimetypes
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

import requests

from asky.config import MODELS
from asky.core.api_client import get_llm_msg

logger = logging.getLogger(__name__)
DOWNLOAD_TIMEOUT_SECONDS = 60
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
GENERIC_BINARY_MIME_TYPE = "application/octet-stream"
EXTENSION_TO_IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
INFERRED_MIME_ALIASES = {
    "image/jpg": "image/jpeg",
}


@dataclass(frozen=True)
class ImageTranscriptionJob:
    """Queued image transcription request."""

    jid: str
    image_id: int
    image_url: str
    image_path: str


class ImageTranscriber:
    """Consumes image URLs asynchronously and emits transcription callbacks."""

    def __init__(
        self,
        *,
        enabled: bool,
        workers: int,
        max_size_mb: int,
        model_alias: str,
        prompt_text: str,
        storage_dir: Path,
        allowed_mime_types: list[str],
        completion_callback: Callable[[dict], None],
    ):
        self.enabled = bool(enabled)
        self.workers = max(1, int(workers))
        self.max_size_bytes = max(1, int(max_size_mb)) * 1024 * 1024
        self.model_alias = str(model_alias or "").strip()
        self.prompt_text = str(prompt_text or "Explain this image briefly.").strip()
        self.storage_dir = Path(storage_dir).expanduser()
        self.allowed_mime_types = {
            str(item).strip().lower() for item in allowed_mime_types if str(item).strip()
        }
        self.completion_callback = completion_callback
        self._queue: queue.Queue[Optional[ImageTranscriptionJob]] = queue.Queue()
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
                name=f"asky-image-transcriber-{index+1}",
                daemon=True,
            )
            thread.start()
            self._workers.append(thread)

    def enqueue(self, job: ImageTranscriptionJob) -> None:
        """Queue a new image transcription request."""
        if not self.enabled:
            self._emit(
                jid=job.jid,
                image_id=job.image_id,
                status="failed",
                error="Image transcription is disabled.",
                image_path=job.image_path,
            )
            return
        if not self.model_alias:
            self._emit(
                jid=job.jid,
                image_id=job.image_id,
                status="failed",
                error="No image model is configured.",
                image_path=job.image_path,
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
                logger.exception("image transcription worker failure: %s", exc)
                self._emit(
                    jid=job.jid,
                    image_id=job.image_id,
                    status="failed",
                    error=str(exc),
                    image_path=job.image_path,
                )
            finally:
                self._queue.task_done()

    def _run_job(self, job: ImageTranscriptionJob) -> None:
        model = MODELS.get(self.model_alias)
        if not model:
            self._emit(
                jid=job.jid,
                image_id=job.image_id,
                status="failed",
                error=f"Image model alias '{self.model_alias}' does not exist.",
                image_path=job.image_path,
            )
            return
        if not bool(model.get("image_support", False)):
            self._emit(
                jid=job.jid,
                image_id=job.image_id,
                status="failed",
                error=f"Model '{self.model_alias}' does not support image input.",
                image_path=job.image_path,
            )
            return

        file_path, mime_type = self._download_image(job.image_url, Path(job.image_path))
        started = time.perf_counter()
        transcript_text = self._transcribe_file(file_path, mime_type)
        elapsed_seconds = time.perf_counter() - started
        self._emit(
            jid=job.jid,
            image_id=job.image_id,
            status="completed",
            transcript_text=transcript_text,
            duration_seconds=elapsed_seconds,
            image_path=str(file_path),
        )

    def _download_image(self, url: str, target_path: Path) -> tuple[Path, str]:
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
                raise RuntimeError(f"Unsupported image MIME type: {content_type}")
            content_length = response.headers.get("Content-Length")
            if content_length:
                total_size = int(content_length)
                if total_size > self.max_size_bytes:
                    raise RuntimeError(
                        f"Image payload exceeds size limit ({total_size} bytes > {self.max_size_bytes})."
                    )

            written = 0
            with target_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > self.max_size_bytes:
                        raise RuntimeError(
                            f"Image payload exceeds size limit ({written} bytes > {self.max_size_bytes})."
                        )
                    handle.write(chunk)
        return target_path, normalized_content_type

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
        extension_mime = EXTENSION_TO_IMAGE_MIME.get(Path(url_path).suffix.lower(), "")
        if extension_mime:
            return extension_mime

        guessed_from_url, _ = mimetypes.guess_type(url_path)
        if guessed_from_url:
            normalized = self._normalize_inferred_mime(str(guessed_from_url))
            if normalized:
                return normalized

        extension_mime = EXTENSION_TO_IMAGE_MIME.get(target_path.suffix.lower(), "")
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

    def _transcribe_file(self, file_path: Path, mime_type: str) -> str:
        model = MODELS[self.model_alias]
        model_id = str(model.get("id", "")).strip()
        if not model_id:
            raise RuntimeError(f"Image model '{self.model_alias}' has no model ID.")

        encoded = base64.b64encode(file_path.read_bytes()).decode("ascii")
        data_url = f"data:{mime_type};base64,{encoded}"
        response = get_llm_msg(
            model_id,
            [
                {"role": "system", "content": "You are an image captioning assistant."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self.prompt_text},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            use_tools=False,
            model_alias=self.model_alias,
            parameters=model.get("parameters"),
        )
        return self._extract_response_text(response)

    def _extract_response_text(self, response: dict) -> str:
        content = response.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text_value = str(item.get("text", "") or "").strip()
                    if text_value:
                        parts.append(text_value)
            return "\n".join(parts).strip()
        return str(content or "").strip()

    def _emit(
        self,
        *,
        jid: str,
        image_id: int,
        status: str,
        transcript_text: str = "",
        error: str = "",
        duration_seconds: Optional[float] = None,
        image_path: str = "",
    ) -> None:
        payload = {
            "jid": jid,
            "image_id": image_id,
            "status": status,
            "transcript_text": transcript_text,
            "error": error,
            "duration_seconds": duration_seconds,
            "image_path": image_path,
        }
        try:
            self.completion_callback(payload)
        except Exception:
            logger.exception("image completion callback failed")
