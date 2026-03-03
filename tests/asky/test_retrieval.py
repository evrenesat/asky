"""Tests for retrieval portal detection and formatting."""

import pytest

from asky.retrieval import (
    PORTAL_DETECTION_MIN_VISIBLE_CHARS,
    _detect_page_type,
    _format_portal_content,
)


def test_detect_page_type_article_large_extraction():
    # Extracted content well above the minimum threshold → article regardless of ratio
    extracted = "word " * 500  # ~2500 chars
    visible_chars = 3000
    assert _detect_page_type(extracted, visible_chars) == "article"


def test_detect_page_type_portal_sparse():
    # Tiny extraction relative to large visible text → portal
    extracted = "Some short text."
    visible_chars = 10000
    assert _detect_page_type(extracted, visible_chars) == "portal"


def test_detect_page_type_portal_empty_extraction():
    # Empty extraction on a page with plenty of visible text → portal
    extracted = ""
    visible_chars = 5000
    assert _detect_page_type(extracted, visible_chars) == "portal"


def test_detect_page_type_article_small_page():
    # Visible text below minimum threshold → article (not enough signal)
    extracted = ""
    visible_chars = PORTAL_DETECTION_MIN_VISIBLE_CHARS - 1
    assert _detect_page_type(extracted, visible_chars) == "article"


def test_detect_page_type_article_good_ratio():
    # 50% extraction ratio → article
    extracted = "x" * 3000
    visible_chars = 6000
    assert _detect_page_type(extracted, visible_chars) == "article"


def test_format_portal_content_groups_by_section():
    html = """
    <h2>Top Stories</h2>
    <a href="https://example.com/1">Article One</a>
    <a href="https://example.com/2">Article Two</a>
    <h2>World</h2>
    <a href="https://example.com/3">Article Three</a>
    """
    content = _format_portal_content(html, "https://example.com", 100)

    assert "[Page type: news portal / content listing]" in content
    assert "## Top Stories" in content
    assert "Article One" in content
    assert "Article Two" in content
    assert "## World" in content
    assert "Article Three" in content
    # Links appear in markdown format
    assert "[Article One](https://example.com/1)" in content


def test_format_portal_content_deduplicates():
    html = """
    <h2>Section A</h2>
    <a href="https://example.com/1">Article</a>
    <h2>Section B</h2>
    <a href="https://example.com/1">Article again</a>
    """
    content = _format_portal_content(html, "https://example.com", 100)

    # URL should appear exactly once despite being in two sections
    assert content.count("example.com/1") == 1


def test_format_portal_content_respects_max_links():
    links_html = "".join(
        f'<a href="https://example.com/{i}">Link {i}</a>' for i in range(20)
    )
    html = f"<div>{links_html}</div>"
    content = _format_portal_content(html, "https://example.com", 5)

    # At most 5 distinct URLs
    assert content.count("example.com/") <= 5


def test_format_portal_content_zone_sections():
    html = """
    <nav><a href="https://example.com/uk">UK</a></nav>
    <h2>News</h2>
    <a href="https://example.com/story">Story</a>
    <footer><a href="https://example.com/about">About</a></footer>
    """
    content = _format_portal_content(html, "https://example.com", 100)

    assert "## Navigation" in content
    assert "## News" in content
    assert "## Footer" in content
    assert "[UK](https://example.com/uk)" in content
    assert "[Story](https://example.com/story)" in content
    assert "[About](https://example.com/about)" in content
