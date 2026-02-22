import pytest
from unittest.mock import patch

from asky.cli.main import _resolve_research_corpus


def test_resolve_research_corpus_disabled():
    enabled, paths, leftover, source_mode, replace = _resolve_research_corpus(False)
    assert enabled is False
    assert paths is None
    assert leftover is None
    assert source_mode is None
    assert replace is False

    enabled, paths, leftover, source_mode, replace = _resolve_research_corpus(None)
    assert enabled is False
    assert paths is None
    assert leftover is None
    assert source_mode is None
    assert replace is False


def test_resolve_research_corpus_enabled_no_pointer():
    enabled, paths, leftover, source_mode, replace = _resolve_research_corpus(True)
    assert enabled is True
    assert paths is None
    assert leftover is None
    assert source_mode is None
    assert replace is False


def test_resolve_research_corpus_absolute_path(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    abs_file = root / "test.pdf"
    abs_file.touch()

    with patch("asky.cli.main.RESEARCH_LOCAL_DOCUMENT_ROOTS", [str(root)]):
        enabled, paths, leftover, source_mode, replace = _resolve_research_corpus(
            str(abs_file)
        )
    assert enabled is True
    assert paths == [str(abs_file.resolve())]
    assert leftover is None
    assert source_mode == "local_only"
    assert replace is True


def test_resolve_research_corpus_absolute_outside_roots_rejected(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.pdf"
    outside.touch()

    with patch("asky.cli.main.RESEARCH_LOCAL_DOCUMENT_ROOTS", [str(root)]):
        with pytest.raises(ValueError, match="outside configured local_document_roots"):
            _resolve_research_corpus(str(outside))


def test_resolve_research_corpus_root_lookup(tmp_path):
    root1 = tmp_path / "root1"
    root1.mkdir()
    root2 = tmp_path / "root2"
    root2.mkdir()

    target_file = root2 / "book.epub"
    target_file.touch()

    with patch("asky.cli.main.RESEARCH_LOCAL_DOCUMENT_ROOTS", [str(root1), str(root2)]):
        enabled, paths, leftover, source_mode, replace = _resolve_research_corpus(
            "book.epub"
        )
        assert enabled is True
        assert paths == [str(target_file.resolve())]
        assert leftover is None
        assert source_mode == "local_only"
        assert replace is True


def test_resolve_research_corpus_multi_pointer(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    f1 = root / "a.pdf"
    f1.touch()
    f2 = root / "b.epub"
    f2.touch()

    with patch("asky.cli.main.RESEARCH_LOCAL_DOCUMENT_ROOTS", [str(root)]):
        enabled, paths, leftover, source_mode, replace = _resolve_research_corpus(
            "a.pdf, b.epub"
        )
        assert enabled is True
        assert set(paths or []) == {str(f1.resolve()), str(f2.resolve())}
        assert leftover is None
        assert source_mode == "local_only"
        assert replace is True


def test_resolve_research_corpus_mixed_mode_with_web_token(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    f1 = root / "a.pdf"
    f1.touch()

    with patch("asky.cli.main.RESEARCH_LOCAL_DOCUMENT_ROOTS", [str(root)]):
        enabled, paths, leftover, source_mode, replace = _resolve_research_corpus(
            "a.pdf,web"
        )
        assert enabled is True
        assert paths == [str(f1.resolve())]
        assert leftover is None
        assert source_mode == "mixed"
        assert replace is True


def test_resolve_research_corpus_web_only_pointer():
    enabled, paths, leftover, source_mode, replace = _resolve_research_corpus("web")
    assert enabled is True
    assert paths == []
    assert leftover is None
    assert source_mode == "web_only"
    assert replace is True


def test_resolve_research_corpus_query_fallback():
    with patch("asky.cli.main.RESEARCH_LOCAL_DOCUMENT_ROOTS", []):
        enabled, paths, leftover, source_mode, replace = _resolve_research_corpus(
            "query"
        )
        assert enabled is True
        assert paths is None
        assert leftover == "query"
        assert source_mode is None
        assert replace is False


def test_resolve_research_corpus_not_found_error():
    with patch("asky.cli.main.RESEARCH_LOCAL_DOCUMENT_ROOTS", []):
        with pytest.raises(ValueError, match="could not be resolved"):
            _resolve_research_corpus("/missing.pdf")

        with pytest.raises(ValueError, match="could not be resolved"):
            _resolve_research_corpus("a.pdf,b.pdf")


def test_resolve_research_corpus_directory(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    subdir = root / "papers"
    subdir.mkdir()

    with patch("asky.cli.main.RESEARCH_LOCAL_DOCUMENT_ROOTS", [str(root)]):
        enabled, paths, leftover, source_mode, replace = _resolve_research_corpus(
            "papers"
        )
        assert enabled is True
        assert paths == [str(subdir.resolve())]
        assert leftover is None
        assert source_mode == "local_only"
        assert replace is True
