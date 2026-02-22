"""Tests for builtin local-source loading helpers."""

from unittest.mock import patch


def test_fetch_source_via_adapter_returns_none_for_web_targets():
    """Non-local targets should not be handled by local ingestion helpers."""
    from asky.research.adapters import fetch_source_via_adapter

    assert fetch_source_via_adapter("https://example.com") is None


def test_builtin_local_adapter_reads_text_file(tmp_path):
    """Builtin local loader should read plain text files."""
    from asky.research.adapters import fetch_source_via_adapter

    source_file = tmp_path / "notes.txt"
    source_file.write_text("local research text", encoding="utf-8")

    with patch("asky.research.adapters.RESEARCH_LOCAL_DOCUMENT_ROOTS", [str(tmp_path)]):
        result = fetch_source_via_adapter(str(source_file), operation="read")

    assert result is not None
    assert result["error"] is None
    assert result["title"] == "notes.txt"
    assert "local research text" in result["content"]


def test_builtin_local_adapter_discovers_directory_files(tmp_path):
    """Builtin local loader should expose supported files as local:// links."""
    from asky.research.adapters import fetch_source_via_adapter

    source_dir = tmp_path / "corpus"
    source_dir.mkdir()
    (source_dir / "a.txt").write_text("A", encoding="utf-8")
    (source_dir / "b.md").write_text("B", encoding="utf-8")
    (source_dir / "ignored.bin").write_bytes(b"\x00\x01")

    with patch("asky.research.adapters.RESEARCH_LOCAL_DOCUMENT_ROOTS", [str(tmp_path)]):
        result = fetch_source_via_adapter(
            str(source_dir),
            operation="discover",
            max_links=10,
        )

    assert result is not None
    assert result["error"] is None
    hrefs = {item["href"] for item in result["links"]}
    assert len(result["links"]) == 2
    assert any(href.endswith("/a.txt") for href in hrefs)
    assert any(href.endswith("/b.md") for href in hrefs)


def test_builtin_local_adapter_pdf_requires_pymupdf(tmp_path):
    """PDF/EPUB local reads should fail with explicit dependency guidance when missing."""
    from asky.research.adapters import fetch_source_via_adapter

    source_file = tmp_path / "paper.pdf"
    source_file.write_bytes(b"%PDF-1.4\n")

    with (
        patch("asky.research.adapters.RESEARCH_LOCAL_DOCUMENT_ROOTS", [str(tmp_path)]),
        patch("asky.research.adapters._load_pymupdf_module", return_value=None),
    ):
        result = fetch_source_via_adapter(str(source_file), operation="read")

    assert result is not None
    assert result["error"] == "PyMuPDF is required to read PDF/EPUB local sources."


def test_builtin_local_adapter_requires_document_roots(tmp_path):
    """Builtin local loader should reject local reads when roots are not configured."""
    from asky.research.adapters import fetch_source_via_adapter

    source_file = tmp_path / "notes.txt"
    source_file.write_text("local research text", encoding="utf-8")

    with patch("asky.research.adapters.RESEARCH_LOCAL_DOCUMENT_ROOTS", []):
        result = fetch_source_via_adapter(str(source_file), operation="read")

    assert result is not None
    assert result["error"] is not None
    assert "local_document_roots" in result["error"]


def test_builtin_local_adapter_allows_absolute_targets_inside_roots(tmp_path):
    """Absolute paths inside configured roots should resolve and ingest."""
    from asky.research.adapters import fetch_source_via_adapter

    nested_dir = tmp_path / "corpus" / "nested"
    nested_dir.mkdir(parents=True)
    source_file = nested_dir / "doc.txt"
    source_file.write_text("nested doc", encoding="utf-8")

    with patch(
        "asky.research.adapters.RESEARCH_LOCAL_DOCUMENT_ROOTS", [str(tmp_path / "corpus")]
    ):
        result = fetch_source_via_adapter(str(source_file), operation="read")

    assert result is not None
    assert result["error"] is None
    assert "nested doc" in result["content"]


def test_builtin_local_adapter_rejects_absolute_targets_outside_roots(tmp_path):
    """Absolute paths outside configured roots should be rejected."""
    from asky.research.adapters import fetch_source_via_adapter

    roots_dir = tmp_path / "roots"
    roots_dir.mkdir()
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("outside", encoding="utf-8")

    with patch("asky.research.adapters.RESEARCH_LOCAL_DOCUMENT_ROOTS", [str(roots_dir)]):
        result = fetch_source_via_adapter(str(outside_file), operation="read")

    assert result is not None
    assert result["error"] is not None
    assert "outside configured document roots" in result["error"]


def test_builtin_local_adapter_supports_root_relative_leading_slash(tmp_path):
    """Root-relative corpus paths (with leading slash) should resolve under roots."""
    from asky.research.adapters import fetch_source_via_adapter

    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    nested = corpus_dir / "nested"
    nested.mkdir()
    source_file = nested / "doc.txt"
    source_file.write_text("from root relative", encoding="utf-8")

    with patch("asky.research.adapters.RESEARCH_LOCAL_DOCUMENT_ROOTS", [str(corpus_dir)]):
        result = fetch_source_via_adapter("/nested/doc.txt", operation="read")

    assert result is not None
    assert result["error"] is None
    assert "from root relative" in result["content"]


def test_extract_local_source_targets_parses_path_tokens():
    """Local target extraction should find scheme and filesystem tokens."""
    from asky.research.adapters import extract_local_source_targets

    text = 'review "local:///tmp/a.pdf" and ./notes.md plus /tmp/report.txt.'
    targets = extract_local_source_targets(text)

    assert "local:///tmp/a.pdf" in targets
    assert "./notes.md" in targets
    assert "/tmp/report.txt" in targets


def test_redact_local_source_targets_removes_path_tokens():
    """Local path tokens should be stripped from model-visible query text."""
    from asky.research.adapters import redact_local_source_targets

    redacted = redact_local_source_targets(
        "Summarize /tmp/report.txt and compare with ./notes.md for me."
    )

    assert "/tmp/report.txt" not in redacted
    assert "./notes.md" not in redacted
    assert "Summarize" in redacted
