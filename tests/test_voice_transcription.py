"""Voice transcription worker tests."""

import os
from pathlib import Path
from typing import Iterable

from asky.daemon.voice_transcriber import (
    GENERIC_BINARY_MIME_TYPE,
    TRANSCRIPTION_ERROR_MACOS_ONLY,
    TranscriptionJob,
    VoiceTranscriber,
)


def test_enqueue_disabled_emits_failure(tmp_path):
    events = []
    transcriber = VoiceTranscriber(
        enabled=False,
        workers=1,
        max_size_mb=10,
        model="m",
        language="",
        storage_dir=tmp_path,
        allowed_mime_types=[],
        completion_callback=events.append,
    )
    transcriber.enqueue(
        TranscriptionJob(
            jid="jid",
            transcript_id=1,
            audio_url="https://example.com/a.m4a",
            audio_path=str(tmp_path / "a.m4a"),
        )
    )
    assert events
    assert events[0]["status"] == "failed"


def test_non_macos_fails_fast(monkeypatch, tmp_path):
    events = []
    transcriber = VoiceTranscriber(
        enabled=True,
        workers=1,
        max_size_mb=10,
        model="m",
        language="",
        storage_dir=tmp_path,
        allowed_mime_types=[],
        completion_callback=events.append,
    )
    monkeypatch.setattr("asky.daemon.voice_transcriber.platform.system", lambda: "Linux")
    transcriber._run_job(
        TranscriptionJob(
            jid="jid",
            transcript_id=2,
            audio_url="https://example.com/a.m4a",
            audio_path=str(Path(tmp_path) / "a.m4a"),
        )
    )
    assert events
    assert events[0]["status"] == "failed"
    assert TRANSCRIPTION_ERROR_MACOS_ONLY in events[0]["error"]


class _FakeResponse:
    def __init__(self, *, headers: dict[str, str], chunks: Iterable[bytes]):
        self.headers = headers
        self._chunks = list(chunks)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=None):
        for chunk in self._chunks:
            yield chunk


def test_download_audio_accepts_octet_stream_when_url_extension_is_audio(monkeypatch, tmp_path):
    transcriber = VoiceTranscriber(
        enabled=True,
        workers=1,
        max_size_mb=10,
        model="m",
        language="",
        storage_dir=tmp_path,
        allowed_mime_types=["audio/x-m4a", "audio/mp4"],
        completion_callback=lambda _payload: None,
    )

    def _fake_get(url, stream, timeout):
        return _FakeResponse(
            headers={"Content-Type": GENERIC_BINARY_MIME_TYPE},
            chunks=[b"audio-bytes"],
        )

    monkeypatch.setattr("asky.daemon.voice_transcriber.requests.get", _fake_get)
    target = tmp_path / "sample.audio"
    path = transcriber._download_audio(
        "https://share.conversations.im/file/example.m4a",
        target,
    )
    assert path.exists()
    assert path.read_bytes() == b"audio-bytes"


def test_download_audio_rejects_octet_stream_without_audio_extension(monkeypatch, tmp_path):
    transcriber = VoiceTranscriber(
        enabled=True,
        workers=1,
        max_size_mb=10,
        model="m",
        language="",
        storage_dir=tmp_path,
        allowed_mime_types=["audio/x-m4a", "audio/mp4"],
        completion_callback=lambda _payload: None,
    )

    def _fake_get(url, stream, timeout):
        return _FakeResponse(
            headers={"Content-Type": GENERIC_BINARY_MIME_TYPE},
            chunks=[b"not-audio"],
        )

    monkeypatch.setattr("asky.daemon.voice_transcriber.requests.get", _fake_get)

    try:
        transcriber._download_audio(
            "https://share.conversations.im/file/no-extension",
            tmp_path / "sample.audio",
        )
    except RuntimeError as exc:
        assert GENERIC_BINARY_MIME_TYPE in str(exc)
    else:
        raise AssertionError("Expected octet-stream without inferable audio extension to fail.")


def test_apply_hf_token_env_sets_standard_aliases(monkeypatch, tmp_path):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    monkeypatch.delenv("ASKY_HF_TOKEN", raising=False)
    transcriber = VoiceTranscriber(
        enabled=True,
        workers=1,
        max_size_mb=10,
        model="m",
        language="",
        storage_dir=tmp_path,
        hf_token_env="ASKY_HF_TOKEN",
        hf_token="token-123",
        allowed_mime_types=[],
        completion_callback=lambda _payload: None,
    )

    transcriber._apply_hf_token_env()
    assert transcriber.hf_token == "token-123"
    assert transcriber.hf_token_env == "ASKY_HF_TOKEN"
    assert os.environ["ASKY_HF_TOKEN"] == "token-123"
    assert os.environ["HF_TOKEN"] == "token-123"
    assert os.environ["HUGGING_FACE_HUB_TOKEN"] == "token-123"


def test_apply_hf_token_env_noop_without_token(monkeypatch, tmp_path):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    transcriber = VoiceTranscriber(
        enabled=True,
        workers=1,
        max_size_mb=10,
        model="m",
        language="",
        storage_dir=tmp_path,
        hf_token_env="HF_TOKEN",
        hf_token="",
        allowed_mime_types=[],
        completion_callback=lambda _payload: None,
    )

    transcriber._apply_hf_token_env()
    assert "HF_TOKEN" not in os.environ
