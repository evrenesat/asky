"""XMPP daemon plugin unit tests."""

from asky.plugins.xmpp_daemon.chunking import chunk_text
from asky.plugins.xmpp_daemon.xmpp_service import (
    XMPPService,
    _extract_urls_from_text,
    _extract_toml_urls,
    _split_media_urls,
    _should_process_text_body,
)
from asky.plugins.xmpp_daemon.document_ingestion import (
    redact_document_urls,
    split_document_urls,
)


def test_chunk_text_splits_in_order():
    text = "A" * 7000
    chunks = chunk_text(text, 3000)
    assert len(chunks) == 3
    assert "".join(chunks) == text


def test_xmpp_plugin_transport_register_raises_when_disabled(monkeypatch):
    monkeypatch.setattr("asky.plugins.xmpp_daemon.plugin.XMPP_ENABLED", False)
    from asky.daemon.errors import DaemonUserError
    from asky.plugins.hook_types import DaemonTransportRegisterContext
    from asky.plugins.xmpp_daemon.plugin import XMPPDaemonPlugin

    plugin = XMPPDaemonPlugin()
    context = DaemonTransportRegisterContext(double_verbose=False)
    try:
        plugin._on_daemon_transport_register(context)
    except DaemonUserError as exc:
        assert "disabled" in str(exc).lower()
    else:
        raise AssertionError("Expected DaemonUserError when XMPP daemon is disabled.")


def test_audio_message_url_body_is_not_processed_as_text():
    assert (
        _should_process_text_body(
            has_media=True,
            body="https://share.example/file/audio.m4a",
        )
        is False
    )


def test_audio_message_with_caption_still_processes_text():
    assert (
        _should_process_text_body(
            has_media=True,
            body="Please summarize this after transcribing.",
        )
        is True
    )


def test_extract_toml_urls_filters_non_toml_payloads():
    payload = {
        "oob_urls": [
            "https://example.com/user.toml",
            "https://example.com/audio.m4a",
            "https://example.com/general.toml?download=1",
        ]
    }
    urls = _extract_toml_urls(payload)
    assert urls == [
        "https://example.com/user.toml",
        "https://example.com/general.toml?download=1",
    ]


def test_split_media_urls_detects_audio_and_images():
    audio_urls, image_urls = _split_media_urls(
        [
            "https://example.com/a.m4a",
            "https://example.com/b.jpg",
            "https://example.com/c.txt",
        ]
    )
    assert audio_urls == ["https://example.com/a.m4a"]
    assert image_urls == ["https://example.com/b.jpg"]


def test_extract_urls_from_text_handles_pasted_url():
    urls = _extract_urls_from_text("https://example.com/file/audio.m4a")
    assert urls == ["https://example.com/file/audio.m4a"]


def test_split_media_urls_detects_query_filename_extension():
    audio_urls, image_urls = _split_media_urls(
        [
            "https://example.com/download?id=1&filename=voice.ogg",
            "https://example.com/download?name=image.webp",
        ]
    )
    assert audio_urls == ["https://example.com/download?id=1&filename=voice.ogg"]
    assert image_urls == ["https://example.com/download?name=image.webp"]


def test_split_document_urls_detects_supported_types():
    doc_urls = split_document_urls(
        [
            "https://example.com/a.pdf",
            "https://example.com/b.epub?download=1",
            "https://example.com/c.jpg",
            "http://example.com/d.pdf",
            "https://example.com/download?filename=paper.md",
        ]
    )
    assert "https://example.com/a.pdf" in doc_urls
    assert "https://example.com/b.epub?download=1" in doc_urls
    assert "https://example.com/download?filename=paper.md" in doc_urls
    assert "https://example.com/c.jpg" in doc_urls

    assert "http://example.com/d.pdf" in doc_urls


def test_redact_document_urls_removes_uploaded_urls_from_query():
    query = "answer this https://example.com/a.pdf and compare to https://example.com/b.epub now"
    redacted = redact_document_urls(
        query,
        ["https://example.com/a.pdf", "https://example.com/b.epub"],
    )
    assert "a.pdf" not in redacted
    assert "b.epub" not in redacted
    assert "answer this" in redacted


def test_media_url_list_body_is_not_processed_as_text():
    assert (
        _should_process_text_body(
            has_media=True,
            body="https://example.com/a.m4a https://example.com/b.jpg",
        )
        is False
    )


def test_document_url_only_body_is_not_processed_as_text():
    assert (
        _should_process_text_body(
            has_media=True,
            body="https://example.com/uploaded.pdf",
        )
        is False
    )


def test_service_stop_logs_and_delegates_to_client():
    class _Client:
        def __init__(self):
            self.stop_called = False

        def stop(self):
            self.stop_called = True

    class _FakeTranscriber:
        def __init__(self):
            self.shutdown_called = False

        def shutdown(self):
            self.shutdown_called = True

    service = XMPPService.__new__(XMPPService)
    service._client = _Client()
    service.voice_transcriber = _FakeTranscriber()
    service.image_transcriber = _FakeTranscriber()
    service.stop()
    assert service._client.stop_called is True
    assert service.voice_transcriber.shutdown_called is True
    assert service.image_transcriber.shutdown_called is True
