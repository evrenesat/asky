"""Document ingestion unit tests for XMPP daemon uploads."""

from pathlib import Path
from types import SimpleNamespace

from asky.plugins.xmpp_daemon import document_ingestion as di


def test_resolve_upload_root_bootstraps_when_no_roots(monkeypatch, tmp_path):
    monkeypatch.setattr(di.asky_config, "RESEARCH_LOCAL_DOCUMENT_ROOTS", [])
    captured = {}

    def _fake_persist(roots: list[str]) -> None:
        captured["roots"] = roots

    monkeypatch.setattr(di, "_persist_research_roots", _fake_persist)
    monkeypatch.setattr(di, "DEFAULT_BOOTSTRAP_ROOT", tmp_path / "bootstrap")

    upload_dir, bootstrapped = di._resolve_upload_root_entry()

    assert bootstrapped is True
    assert upload_dir == (tmp_path / "bootstrap" / di.UPLOADS_DIRNAME).resolve()
    assert captured["roots"] == [str((tmp_path / "bootstrap").resolve())]


def test_validate_extension_and_mime_enforces_pdf_mime():
    valid, reason = di._validate_extension_and_mime(".pdf", "application/pdf")
    assert valid is True
    assert reason is None

    valid, reason = di._validate_extension_and_mime(".pdf", "text/plain")
    assert valid is False
    assert "invalid" in str(reason).lower()


def test_ingest_rejects_non_https_urls(monkeypatch):
    service = di.DocumentIngestionService()
    monkeypatch.setattr(di, "list_session_uploaded_documents", lambda session_id: [])
    monkeypatch.setattr(
        di, "_resolve_upload_root_entry", lambda: (Path("/tmp/unused"), False)
    )
    report = service.ingest_for_session(
        session_id=1,
        urls=["http://example.com/a.pdf"],
    )
    assert report["processed_count"] == 1
    assert report["failed"]
    assert "https" in report["failed"][0]["error"].lower()


def test_ingest_dedupes_by_hash_and_links_session(monkeypatch, tmp_path):
    service = di.DocumentIngestionService()
    upload_dir = tmp_path / "uploads"
    existing_file = tmp_path / "existing.pdf"
    existing_file.write_bytes(b"same")

    existing_doc = SimpleNamespace(
        id=99,
        content_hash="abc",
        file_path=str(existing_file),
        original_filename="existing.pdf",
        file_extension=".pdf",
        mime_type="application/pdf",
        file_size=4,
    )
    links: list[tuple[int, int]] = []
    profile_updates = []

    monkeypatch.setattr(di, "_resolve_upload_root_entry", lambda: (upload_dir, False))
    monkeypatch.setattr(di, "list_session_uploaded_documents", lambda session_id: [])
    monkeypatch.setattr(di, "get_uploaded_document_by_url", lambda url: None)
    monkeypatch.setattr(di, "_download_document", lambda url: (b"same", "application/pdf"))
    monkeypatch.setattr(di, "get_uploaded_document_by_hash", lambda content_hash: existing_doc)
    monkeypatch.setattr(
        di,
        "save_uploaded_document_url",
        lambda url, document_id: None,
    )
    monkeypatch.setattr(
        di,
        "link_session_uploaded_document",
        lambda session_id, document_id: links.append((session_id, document_id)),
    )
    monkeypatch.setattr(
        di,
        "get_session_by_id",
        lambda session_id: SimpleNamespace(research_local_corpus_paths=[]),
    )
    monkeypatch.setattr(
        di,
        "update_session_research_profile",
        lambda session_id, **kwargs: profile_updates.append((session_id, kwargs)),
    )
    monkeypatch.setattr(
        di,
        "preload_local_research_sources",
        lambda user_prompt, explicit_targets: {"ingested": [{"source_handle": "h:1"}]},
    )

    report = service.ingest_for_session(
        session_id=7,
        urls=["https://example.com/a.pdf"],
    )

    assert report["processed_count"] == 1
    assert report["ingested_count"] == 0
    assert report["linked_count"] == 1
    assert report["skipped_count"] == 1
    assert links == [(7, 99)]
    assert profile_updates
    assert profile_updates[0][0] == 7
    assert str(existing_file) in profile_updates[0][1]["research_local_corpus_paths"]


def test_download_document_enforces_size_limit(monkeypatch):
    class _Response:
        headers = {"Content-Type": "application/pdf"}

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int):
            _ = chunk_size
            yield b"a" * (di.DOCUMENT_MAX_FILE_SIZE_BYTES + 1)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            _ = (exc_type, exc, tb)
            return False

    monkeypatch.setattr(di.requests, "get", lambda *args, **kwargs: _Response())

    try:
        di._download_document("https://example.com/a.pdf")
    except RuntimeError as exc:
        assert "size limit" in str(exc).lower()
    else:
        raise AssertionError("Expected size limit runtime error.")


def test_redact_document_urls_keeps_unrelated_url():
    body = "compare https://example.com/a.pdf with https://example.com/ref"
    redacted = di.redact_document_urls(body, ["https://example.com/a.pdf"])
    assert "a.pdf" not in redacted
    assert "https://example.com/ref" in redacted
