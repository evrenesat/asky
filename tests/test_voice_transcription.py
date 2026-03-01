"""Voice transcription service and worker tests."""

import os
import platform
from pathlib import Path
from typing import Iterable
from unittest.mock import MagicMock

import pytest

from asky.plugins.voice_transcriber.service import (
    GENERIC_BINARY_MIME_TYPE,
    VoiceTranscriberService,
    VoiceTranscriptionJob,
    VoiceTranscriberWorker,
    UnsupportedOSStrategy,
    MacOSMLXWhisperStrategy,
)


def test_unsupported_os_strategy_raises_runtime_error():
    strategy = UnsupportedOSStrategy()
    with pytest.raises(RuntimeError, match="Voice transcription is not yet supported"):
        strategy.transcribe(Path("test.mp3"), "model", None)


def test_service_download_audio_accepts_octet_stream_with_extension(monkeypatch, tmp_path):
    service = VoiceTranscriberService(
        model="m",
        allowed_mime_types=["audio/x-m4a"],
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
            chunks=[b"audio-data"]
        )

    monkeypatch.setattr("requests.get", _fake_get)
    target = tmp_path / "test.m4a"
    path = service.download_audio("https://example.com/test.m4a", target)
    assert path.exists()
    assert path.read_bytes() == b"audio-data"


def test_service_download_audio_rejects_unsupported_mime(monkeypatch, tmp_path):
    service = VoiceTranscriberService(
        model="m",
        allowed_mime_types=["audio/x-m4a"],
    )

    def _fake_get(url, **kwargs):
        class _Resp:
            headers = {"Content-Type": "text/plain"}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def raise_for_status(self): pass
        return _Resp()

    monkeypatch.setattr("requests.get", _fake_get)
    with pytest.raises(RuntimeError, match="Unsupported audio MIME type"):
        service.download_audio("https://example.com/test.txt", tmp_path / "test.txt")


def test_worker_pool_lifecycle(tmp_path):
    service = MagicMock(spec=VoiceTranscriberService)
    events = []
    worker = VoiceTranscriberWorker(
        service=service,
        workers=2,
        completion_callback=events.append
    )
    
    worker.start()
    assert len(worker._threads) == 2
    for t in worker._threads:
        assert t.is_alive()
        
    worker.shutdown()
    assert len(worker._threads) == 0


def test_macos_strategy_applies_hf_token(monkeypatch):
    strategy = MacOSMLXWhisperStrategy()
    monkeypatch.delenv("HF_TOKEN", raising=False)
    
    # Mock mlx_whisper to avoid actual transcription
    mock_mlx = MagicMock()
    monkeypatch.setitem(platform.sys.modules, "mlx_whisper", mock_mlx)
    
    strategy.transcribe(
        Path("test.mp3"), 
        "model", 
        None, 
        hf_token="test-token",
        hf_token_env="CUSTOM_HF_TOKEN"
    )
    
    assert os.environ["CUSTOM_HF_TOKEN"] == "test-token"
    assert os.environ["HF_TOKEN"] == "test-token"
