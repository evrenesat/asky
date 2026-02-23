"""Image transcription worker tests."""

from pathlib import Path
from typing import Iterable

from asky.daemon.image_transcriber import (
    GENERIC_BINARY_MIME_TYPE,
    ImageTranscriber,
    ImageTranscriptionJob,
)


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


def test_enqueue_disabled_emits_failure(tmp_path):
    events = []
    transcriber = ImageTranscriber(
        enabled=False,
        workers=1,
        max_size_mb=5,
        model_alias="gf",
        prompt_text="describe",
        storage_dir=tmp_path,
        allowed_mime_types=[],
        completion_callback=events.append,
    )
    transcriber.enqueue(
        ImageTranscriptionJob(
            jid="jid",
            image_id=1,
            image_url="https://example.com/a.jpg",
            image_path=str(tmp_path / "a.jpg"),
        )
    )
    assert events
    assert events[0]["status"] == "failed"


def test_download_image_accepts_octet_stream_when_url_extension_is_image(monkeypatch, tmp_path):
    transcriber = ImageTranscriber(
        enabled=True,
        workers=1,
        max_size_mb=5,
        model_alias="gf",
        prompt_text="describe",
        storage_dir=tmp_path,
        allowed_mime_types=["image/jpeg", "image/png"],
        completion_callback=lambda _payload: None,
    )

    def _fake_get(url, stream, timeout):
        return _FakeResponse(
            headers={"Content-Type": GENERIC_BINARY_MIME_TYPE},
            chunks=[b"image-bytes"],
        )

    monkeypatch.setattr("asky.daemon.image_transcriber.requests.get", _fake_get)
    target = tmp_path / "sample.image"
    path, mime_type = transcriber._download_image(
        "https://share.example/file/example.jpg",
        target,
    )
    assert path.exists()
    assert mime_type == "image/jpeg"
    assert path.read_bytes() == b"image-bytes"


def test_run_job_calls_multimodal_payload(monkeypatch, tmp_path):
    events = []
    transcriber = ImageTranscriber(
        enabled=True,
        workers=1,
        max_size_mb=5,
        model_alias="gf",
        prompt_text="Explain this image briefly.",
        storage_dir=tmp_path,
        allowed_mime_types=["image/jpeg"],
        completion_callback=events.append,
    )

    def _fake_get(url, stream, timeout):
        return _FakeResponse(
            headers={"Content-Type": "image/jpeg"},
            chunks=[b"\xff\xd8\xff\xdb"],
        )

    captured = {}

    def _fake_llm(model_id, messages, **kwargs):
        captured["model_id"] = model_id
        captured["messages"] = messages
        return {"content": "a tiny test image"}

    monkeypatch.setattr("asky.daemon.image_transcriber.requests.get", _fake_get)
    monkeypatch.setattr("asky.daemon.image_transcriber.get_llm_msg", _fake_llm)
    monkeypatch.setattr("asky.daemon.image_transcriber.MODELS", {"gf": {"id": "x", "image_support": True}})

    transcriber._run_job(
        ImageTranscriptionJob(
            jid="jid",
            image_id=1,
            image_url="https://example.com/a.jpg",
            image_path=str(Path(tmp_path) / "a.jpg"),
        )
    )

    assert captured["model_id"] == "x"
    user_message = captured["messages"][1]["content"]
    assert isinstance(user_message, list)
    assert user_message[1]["type"] == "image_url"
    assert "base64," in user_message[1]["image_url"]["url"]
    assert events
    assert events[0]["status"] == "completed"
    assert events[0]["transcript_text"] == "a tiny test image"
