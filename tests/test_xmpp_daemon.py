"""Daemon service/unit tests."""

from asky.daemon.chunking import chunk_text
from asky.daemon.service import _should_process_text_body, run_xmpp_daemon_foreground


def test_chunk_text_splits_in_order():
    text = "A" * 7000
    chunks = chunk_text(text, 3000)
    assert len(chunks) == 3
    assert "".join(chunks) == text


def test_run_xmpp_daemon_requires_enabled(monkeypatch):
    monkeypatch.setattr("asky.daemon.service.XMPP_ENABLED", False)
    try:
        run_xmpp_daemon_foreground()
    except RuntimeError as exc:
        assert "disabled" in str(exc).lower()
    else:
        raise AssertionError("Expected RuntimeError when XMPP daemon is disabled.")


def test_audio_message_url_body_is_not_processed_as_text():
    assert (
        _should_process_text_body(
            audio_url="https://share.example/file/audio.m4a",
            body="https://share.example/file/audio.m4a",
        )
        is False
    )


def test_audio_message_with_caption_still_processes_text():
    assert (
        _should_process_text_body(
            audio_url="https://share.example/file/audio.m4a",
            body="Please summarize this after transcribing.",
        )
        is True
    )
