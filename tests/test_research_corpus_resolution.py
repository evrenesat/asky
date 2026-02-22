import pytest
import os
from unittest.mock import patch
from asky.cli.main import _resolve_research_corpus


def test_resolve_research_corpus_disabled():
    enabled, paths, leftover = _resolve_research_corpus(False)
    assert enabled is False
    assert paths is None
    assert leftover is None

    enabled, paths, leftover = _resolve_research_corpus(None)
    assert enabled is False
    assert paths is None
    assert leftover is None


def test_resolve_research_corpus_enabled_no_pointer():
    enabled, paths, leftover = _resolve_research_corpus(True)
    assert enabled is True
    assert paths is None
    assert leftover is None


def test_resolve_research_corpus_absolute_path(tmp_path):
    # Success: absolute path exists
    abs_file = tmp_path / "test.pdf"
    abs_file.touch()
    enabled, paths, leftover = _resolve_research_corpus(str(abs_file))
    assert enabled is True
    assert paths == [str(abs_file)]
    assert leftover is None


def test_resolve_research_corpus_root_lookup(tmp_path):
    # Setup corpus roots
    root1 = tmp_path / "root1"
    root1.mkdir()
    root2 = tmp_path / "root2"
    root2.mkdir()

    target_file = root2 / "book.epub"
    target_file.touch()

    with patch("asky.cli.main.RESEARCH_LOCAL_DOCUMENT_ROOTS", [str(root1), str(root2)]):
        enabled, paths, leftover = _resolve_research_corpus("book.epub")
        assert enabled is True
        assert paths == [str(target_file)]
        assert leftover is None


def test_resolve_research_corpus_multi_pointer(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    f1 = root / "a.pdf"
    f1.touch()
    f2 = root / "b.epub"
    f2.touch()

    with patch("asky.cli.main.RESEARCH_LOCAL_DOCUMENT_ROOTS", [str(root)]):
        enabled, paths, leftover = _resolve_research_corpus("a.pdf, b.epub")
        assert enabled is True
        assert set(paths) == {str(f1), str(f2)}
        assert leftover is None


def test_resolve_research_corpus_query_fallback():
    with patch("asky.cli.main.RESEARCH_LOCAL_DOCUMENT_ROOTS", []):
        # "query" is NOT a path (/...) and NOT a list (,), so it's a leftover
        enabled, paths, leftover = _resolve_research_corpus("query")
        assert enabled is True
        assert paths is None
        assert leftover == "query"


def test_resolve_research_corpus_not_found_error():
    with patch("asky.cli.main.RESEARCH_LOCAL_DOCUMENT_ROOTS", []):
        # Starts with / -> explicit path, fails if missing
        with pytest.raises(ValueError, match="could not be resolved"):
            _resolve_research_corpus("/missing.pdf")

        # Contains , -> explicit list, fails if missing
        with pytest.raises(ValueError, match="could not be resolved"):
            _resolve_research_corpus("a.pdf,b.pdf")


def test_resolve_research_corpus_directory(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    subdir = root / "papers"
    subdir.mkdir()

    with patch("asky.cli.main.RESEARCH_LOCAL_DOCUMENT_ROOTS", [str(root)]):
        enabled, paths, leftover = _resolve_research_corpus("papers")
        assert enabled is True
        assert paths == [str(subdir)]
        assert leftover is None
