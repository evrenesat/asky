"""Core image transcription service."""

from __future__ import annotations

import base64
import logging
import mimetypes
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
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


class ImageTranscriberService:
    """Service for image captioning/transcription using multimodal LLMs."""

    def __init__(
        self,
        *,
        model_alias: str,
        prompt_text: str = "Explain this image briefly.",
        max_size_mb: int = 20,
        allowed_mime_types: Optional[List[str]] = None,
        preferred_workers: int = 1,
    ):
        self.model_alias = model_alias.strip()
        self.prompt_text = prompt_text.strip()
        self.max_size_bytes = max(1, int(max_size_mb)) * 1024 * 1024
        self.allowed_mime_types = {
            m.strip().lower() for m in (allowed_mime_types or []) if m.strip()
        }
        self.preferred_workers = max(1, int(preferred_workers))

    def transcribe_url(self, url: str, target_path: Path, prompt: Optional[str] = None) -> str:
        """Synchronously download and transcribe an image URL."""
        file_path, mime_type = self.download_image(url, target_path)
        return self.transcribe_file(file_path, mime_type, prompt=prompt)

    def download_image(self, url: str, target_path: Path) -> tuple[Path, str]:
        """Download image from URL with validation."""
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
                raise RuntimeError(f"Unsupported image MIME type: {normalized_mime}")

            content_length = response.headers.get("Content-Length")
            if content_length:
                if int(content_length) > self.max_size_bytes:
                    raise RuntimeError(
                        f"Image exceeds size limit ({content_length} bytes)."
                    )

            written = 0
            with target_path.open("wb") as f:
                for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > self.max_size_bytes:
                        raise RuntimeError("Image exceeds size limit during download.")
                    f.write(chunk)
        return target_path, normalized_mime

    def _resolve_mime(self, content_type: str, url: str, path: Path) -> str:
        mime = INFERRED_MIME_ALIASES.get(content_type, content_type)
        if mime != GENERIC_BINARY_MIME_TYPE:
            return mime

        ext = path.suffix.lower() or Path(urlparse(url).path).suffix.lower()
        return EXTENSION_TO_IMAGE_MIME.get(ext, GENERIC_BINARY_MIME_TYPE)

    def transcribe_file(self, file_path: Path, mime_type: str, prompt: Optional[str] = None) -> str:
        """Transcribe a local image file using multimodal LLM."""
        model = MODELS.get(self.model_alias)
        if not model:
            raise RuntimeError(f"Image model alias '{self.model_alias}' not found.")
        
        if not bool(model.get("image_support", False)):
            raise RuntimeError(f"Model '{self.model_alias}' does not support image input.")

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
                        {"type": "text", "text": prompt or self.prompt_text},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            use_tools=False,
            model_alias=self.model_alias,
            parameters=model.get("parameters"),
        )
        return self._extract_response_text(response)

    def _extract_response_text(self, response: Dict[str, Any]) -> str:
        content = response.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, dict):
                    text_value = str(item.get("text", "") or "").strip()
                    if text_value:
                        parts.append(text_value)
            return "\n".join(parts).strip()
        return str(content or "").strip()

    def create_worker(
        self,
        completion_callback: Callable[[Dict[str, Any]], None],
        workers: Optional[int] = None,
        enabled: bool = True,
    ) -> ImageTranscriberWorker:
        """Create a background worker for asynchronous jobs."""
        return ImageTranscriberWorker(
            service=self,
            workers=workers if workers is not None else self.preferred_workers,
            completion_callback=completion_callback,
            enabled=enabled,
        )


class ImageTranscriberWorker:
    """Background worker pool for processing ImageTranscriptionJob instances."""

    def __init__(
        self,
        service: ImageTranscriberService,
        workers: int,
        completion_callback: Callable[[Dict[str, Any]], None],
        enabled: bool = True,
    ):
        self.service = service
        self.workers = max(1, workers)
        self.completion_callback = completion_callback
        self.enabled = enabled
        self._queue: queue.Queue[Optional[ImageTranscriptionJob]] = queue.Queue()
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
                name=f"asky-image-worker-{i}",
                daemon=True,
            )
            t.start()
            self._threads.append(t)

    def enqueue(self, job: ImageTranscriptionJob | Dict[str, Any]) -> None:
        """Queue a job for background processing."""
        normalized_job = self._coerce_job(job)
        if not self.enabled:
            self._emit(normalized_job, "failed", error="Image transcription is disabled.")
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
                text = self.service.transcribe_url(job.image_url, Path(job.image_path))
                elapsed = time.perf_counter() - start_time
                self._emit(job, "completed", text=text, elapsed=elapsed)
            except Exception as exc:
                logger.exception("Image worker job failed")
                self._emit(job, "failed", error=str(exc))
            finally:
                self._queue.task_done()

    def _coerce_job(self, job: ImageTranscriptionJob | Dict[str, Any]) -> ImageTranscriptionJob:
        if isinstance(job, ImageTranscriptionJob):
            return job
        return ImageTranscriptionJob(
            jid=str(job["jid"]),
            image_id=int(job["image_id"]),
            image_url=str(job["image_url"]),
            image_path=str(job["image_path"]),
        )

    def _emit(
        self,
        job: ImageTranscriptionJob,
        status: str,
        text: str = "",
        error: str = "",
        elapsed: float = 0.0,
    ) -> None:
        payload = {
            "jid": job.jid,
            "image_id": job.image_id,
            "status": status,
            "transcript_text": text,
            "error": error,
            "duration_seconds": elapsed,
            "image_path": job.image_path,
        }
        try:
            self.completion_callback(payload)
        except Exception:
            logger.exception("Image worker callback failed")
