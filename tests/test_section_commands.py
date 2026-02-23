"""Tests for manual section listing/summarization CLI commands."""

from unittest.mock import MagicMock, patch

from asky.cli.section_commands import run_summarize_section_command


@patch("asky.cli.section_commands.build_section_index")
@patch("asky.cli.section_commands.ResearchCache")
def test_run_summarize_section_lists_sections_without_query(
    mock_cache_cls,
    mock_build_index,
):
    cache = MagicMock()
    cache.list_cached_sources.return_value = [{"id": 7, "title": "Book", "url": "local://book"}]
    cache.get_cached_by_id.return_value = {"content": "body", "title": "Book"}
    mock_cache_cls.return_value = cache

    mock_build_index.return_value = {
        "sections": [
            {"id": "preface-001", "title": "PREFACE", "char_count": 1200},
            {"id": "chapter-002", "title": "CHAPTER 1", "char_count": 3000},
        ]
    }

    console = MagicMock()
    status = run_summarize_section_command(
        section_query=None,
        section_source="corpus://cache/7",
        console=console,
    )

    assert status == 0
    assert console.print.called


@patch("asky.cli.section_commands._summarize_content", return_value="Detailed summary")
@patch("asky.cli.section_commands.slice_section_content")
@patch("asky.cli.section_commands.match_section_strict")
@patch("asky.cli.section_commands.build_section_index")
@patch("asky.cli.section_commands.ResearchCache")
def test_run_summarize_section_returns_summary_for_strict_match(
    mock_cache_cls,
    mock_build_index,
    mock_match_strict,
    mock_slice,
    mock_summarize,
):
    cache = MagicMock()
    cache.list_cached_sources.return_value = [{"id": 7, "title": "Book", "url": "local://book"}]
    cache.get_cached_by_id.return_value = {"content": "body", "title": "Book"}
    mock_cache_cls.return_value = cache

    mock_build_index.return_value = {
        "sections": [
            {
                "id": "learning-001",
                "title": "WHY LEARNING IS STILL A SLOG AFTER FIFTY YEARS OF MOORE'S LAW",
                "char_count": 5000,
            }
        ]
    }
    mock_match_strict.return_value = {
        "matched": True,
        "confidence": 0.97,
        "section": mock_build_index.return_value["sections"][0],
        "suggestions": [],
    }
    mock_slice.return_value = {
        "content": "section content " * 40,
        "truncated": False,
        "available_chunks": 1,
        "section": mock_build_index.return_value["sections"][0],
        "resolved_section_id": "learning-001",
        "requested_section_id": "learning-001",
        "auto_promoted": False,
    }

    console = MagicMock()
    status = run_summarize_section_command(
        section_query="WHY LEARNING IS STILL A SLOG AFTER FIFTY YEARS OF MOORE'S LAW",
        section_source="corpus://cache/7",
        section_detail="balanced",
        console=console,
    )

    assert status == 0
    assert mock_summarize.called
    assert console.print.called


@patch("asky.cli.section_commands._summarize_content", return_value="Detailed summary")
@patch("asky.cli.section_commands.slice_section_content")
@patch("asky.cli.section_commands.match_section_strict")
@patch("asky.cli.section_commands.build_section_index")
@patch("asky.cli.section_commands.ResearchCache")
def test_run_summarize_section_section_id_bypasses_query_match(
    mock_cache_cls,
    mock_build_index,
    mock_match_strict,
    mock_slice,
    mock_summarize,
):
    cache = MagicMock()
    cache.list_cached_sources.return_value = [{"id": 7, "title": "Book", "url": "local://book"}]
    cache.get_cached_by_id.return_value = {"content": "body", "title": "Book"}
    mock_cache_cls.return_value = cache

    mock_build_index.return_value = {
        "sections": [
            {"id": "learning-014", "title": "WHY LEARNING", "char_count": 62},
            {"id": "learning-038", "title": "WHY LEARNING", "char_count": 86438},
        ],
        "canonical_sections": [
            {"id": "learning-038", "title": "WHY LEARNING", "char_count": 86438},
        ],
        "alias_map": {"learning-014": "learning-038", "learning-038": "learning-038"},
    }
    mock_slice.return_value = {
        "content": "section content " * 50,
        "truncated": False,
        "available_chunks": 1,
        "section": mock_build_index.return_value["canonical_sections"][0],
        "resolved_section_id": "learning-038",
        "requested_section_id": "learning-014",
        "auto_promoted": True,
    }

    console = MagicMock()
    status = run_summarize_section_command(
        section_query=None,
        section_source="corpus://cache/7",
        section_id="learning-014",
        console=console,
    )

    assert status == 0
    assert not mock_match_strict.called
    assert mock_summarize.called


@patch("asky.cli.section_commands.ResearchCache")
def test_run_summarize_section_requires_source_when_multiple_cached_sources(
    mock_cache_cls,
):
    cache = MagicMock()
    cache.list_cached_sources.return_value = [
        {"id": 7, "title": "Book A", "url": "local://a"},
        {"id": 8, "title": "Book B", "url": "local://b"},
    ]
    mock_cache_cls.return_value = cache

    console = MagicMock()
    status = run_summarize_section_command(
        section_query=None,
        section_source=None,
        console=console,
    )

    assert status == 1
    assert console.print.called


@patch("asky.cli.section_commands.slice_section_content")
@patch("asky.cli.section_commands.match_section_strict")
@patch("asky.cli.section_commands.build_section_index")
@patch("asky.cli.section_commands.ResearchCache")
def test_run_summarize_section_rejects_tiny_section_text(
    mock_cache_cls,
    mock_build_index,
    mock_match_strict,
    mock_slice,
):
    cache = MagicMock()
    cache.list_cached_sources.return_value = [{"id": 7, "title": "Book", "url": "local://book"}]
    cache.get_cached_by_id.return_value = {"content": "body", "title": "Book"}
    mock_cache_cls.return_value = cache

    mock_build_index.return_value = {
        "sections": [{"id": "learning-001", "title": "WHY LEARNING", "char_count": 5000}]
    }
    mock_match_strict.return_value = {
        "matched": True,
        "confidence": 0.97,
        "section": mock_build_index.return_value["sections"][0],
        "suggestions": [],
    }
    mock_slice.return_value = {
        "content": "tiny",
        "truncated": False,
        "available_chunks": 1,
        "section": mock_build_index.return_value["sections"][0],
        "resolved_section_id": "learning-001",
        "requested_section_id": "learning-001",
        "auto_promoted": False,
    }

    console = MagicMock()
    status = run_summarize_section_command(
        section_query="why learning",
        section_source="corpus://cache/7",
        console=console,
    )

    assert status == 1


@patch("asky.cli.section_commands.match_section_strict")
@patch("asky.cli.section_commands.build_section_index")
@patch("asky.cli.section_commands.ResearchCache")
def test_run_summarize_section_returns_suggestions_on_ambiguous_match(
    mock_cache_cls,
    mock_build_index,
    mock_match_strict,
):
    cache = MagicMock()
    cache.list_cached_sources.return_value = [{"id": 7, "title": "Book", "url": "local://book"}]
    cache.get_cached_by_id.return_value = {"content": "body", "title": "Book"}
    mock_cache_cls.return_value = cache

    mock_build_index.return_value = {
        "sections": [
            {"id": "learning-001", "title": "WHY LEARNING IS STILL A SLOG", "char_count": 5000}
        ]
    }
    mock_match_strict.return_value = {
        "matched": False,
        "confidence": 0.61,
        "reason": "low_confidence",
        "suggestions": [
            {"id": "learning-001", "title": "WHY LEARNING IS STILL A SLOG", "confidence": 0.61}
        ],
    }

    console = MagicMock()
    status = run_summarize_section_command(
        section_query="learning after moore law",
        section_source="corpus://cache/7",
        console=console,
    )

    assert status == 1
    assert console.print.called
