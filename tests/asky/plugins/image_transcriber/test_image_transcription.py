"""Image transcription service and worker tests."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from asky.plugins.image_transcriber.service import (
    GENERIC_BINARY_MIME_TYPE,
    ImageTranscriberService,
    ImageTranscriptionJob,
    ImageTranscriberWorker,
)


def test_service_download_image_accepts_octet_stream_with_extension(monkeypatch, tmp_path):
    service = ImageTranscriberService(
        model_alias="m",
        allowed_mime_types=["image/png"],
    )

    class _FakeResponse:
        def __init__(self, headers: dict, chunks: list):
            self.headers = headers
            self.chunks = chunks
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def iter_content(self, **kwargs):
            for c in self.chunks: yield c

    def _fake_get(url, **kwargs):
        return _FakeResponse(
            headers={"Content-Type": GENERIC_BINARY_MIME_TYPE},
            chunks=[b"image-data"]
        )

    monkeypatch.setattr("requests.get", _fake_get)
    target = tmp_path / "test.png"
    path, mime = service.download_image("https://example.com/test.png", target)
    assert path.exists()
    assert mime == "image/png"
    assert path.read_bytes() == b"image-data"


def test_service_transcribe_file_uses_llm_msg(monkeypatch, tmp_path):
    service = ImageTranscriberService(model_alias="vision-model")
    
    mock_models = {"vision-model": {"id": "actual-id", "image_support": True}}
    monkeypatch.setattr("asky.plugins.image_transcriber.service.MODELS", mock_models)
    
    mock_get_llm_msg = MagicMock(return_value={"content": "a beautiful landscape"})
    monkeypatch.setattr("asky.plugins.image_transcriber.service.get_llm_msg", mock_get_llm_msg)
    
    image_path = tmp_path / "test.jpg"
    image_path.write_bytes(b"fake-image")
    
    result = service.transcribe_file(image_path, "image/jpeg")
    assert result == "a beautiful landscape"
    assert mock_get_llm_msg.called


def test_worker_pool_lifecycle():
    service = MagicMock(spec=ImageTranscriberService)
    worker = ImageTranscriberWorker(
        service=service,
        workers=1,
        completion_callback=lambda _: None
    )
    
    worker.start()
    assert len(worker._threads) == 1
    worker.shutdown()
    assert len(worker._threads) == 0
