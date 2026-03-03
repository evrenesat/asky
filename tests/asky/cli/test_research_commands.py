"""Tests for manual research corpus CLI commands."""

from unittest.mock import MagicMock, patch

from asky.cli.research_commands import run_manual_corpus_query_command


@patch("asky.cli.research_commands.execute_get_relevant_content")
@patch("asky.cli.research_commands.preload_local_research_sources")
def test_run_manual_corpus_query_uses_explicit_targets(
    mock_preload_local,
    mock_get_relevant,
):
    mock_preload_local.return_value = {
        "ingested": [
            {"source_handle": "corpus://cache/5"},
        ],
        "warnings": [],
    }
    mock_get_relevant.return_value = {"corpus://cache/5": {"chunks": []}}

    console = MagicMock()
    status = run_manual_corpus_query_command(
        query="learning slog",
        explicit_targets=["/tmp/books/book.epub"],
        max_sources=10,
        max_chunks=2,
        console=console,
    )

    assert status == 0
    mock_get_relevant.assert_called_once_with(
        {
            "query": "learning slog",
            "corpus_urls": ["corpus://cache/5"],
            "max_chunks": 2,
        }
    )


@patch("asky.cli.research_commands.execute_get_relevant_content")
@patch("asky.cli.research_commands.ResearchCache")
def test_run_manual_corpus_query_uses_cached_sources_when_no_explicit_targets(
    mock_cache_cls,
    mock_get_relevant,
):
    cache = MagicMock()
    cache.list_cached_sources.return_value = [{"id": 9}, {"id": 11}]
    mock_cache_cls.return_value = cache
    mock_get_relevant.return_value = {
        "corpus://cache/9": {"chunks": []},
        "corpus://cache/11": {"chunks": []},
    }

    console = MagicMock()
    status = run_manual_corpus_query_command(
        query="moore law",
        explicit_targets=None,
        max_sources=2,
        max_chunks=1,
        console=console,
    )

    assert status == 0
    mock_get_relevant.assert_called_once_with(
        {
            "query": "moore law",
            "corpus_urls": ["corpus://cache/9", "corpus://cache/11"],
            "max_chunks": 1,
        }
    )


@patch("asky.cli.research_commands.ResearchCache")
def test_run_manual_corpus_query_returns_error_when_no_sources(mock_cache_cls):
    cache = MagicMock()
    cache.list_cached_sources.return_value = []
    mock_cache_cls.return_value = cache

    console = MagicMock()
    status = run_manual_corpus_query_command(
        query="anything",
        explicit_targets=None,
        console=console,
    )

    assert status == 1
