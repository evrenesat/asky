import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from asky.rendering import save_html_report, _create_html_content


def test_create_html_content_basic():
    """Test standard HTML wrapping."""
    with patch("asky.config.TEMPLATE_PATH") as mock_path:
        mock_path.exists.return_value = True
        # Mock open() on the template path
        with patch("builtins.open", new_callable=MagicMock) as mock_open:
            mock_file = MagicMock()
            mock_file.read.return_value = "<html><body>{{CONTENT}}</body></html>"
            mock_open.return_value.__enter__.return_value = mock_file

            result = _create_html_content("# Hello")
            assert "<html><body># Hello</body></html>" in result


def test_create_html_content_no_template():
    """Test fallback when template is missing."""
    with patch("asky.config.TEMPLATE_PATH") as mock_path:
        mock_path.exists.return_value = False
        result = _create_html_content("# Hello")
        assert "<pre># Hello</pre>" in result


def test_save_html_report():
    """Test saving the HTML report to the archive directory with timestamp."""
    content = "# Test Content"

    with tempfile.TemporaryDirectory() as temp_dir:
        archive_dir = Path(temp_dir)

        # Mock ARCHIVE_DIR, datetime, and create_html_content
        with (
            patch("asky.rendering.ARCHIVE_DIR", archive_dir),
            patch(
                "asky.rendering._create_html_content",
                return_value="<htmled># Test Content</htmled>",
            ),
            patch("asky.rendering.generate_slug", return_value="test_slug"),
            patch("asky.rendering.datetime") as mock_datetime,
        ):
            # Mock datetime.now()
            mock_now = MagicMock()
            mock_now.strftime.side_effect = [
                "20230101_120000",  # for filename
                "2023-01-01 12:00",  # for timestamp_str
            ]
            mock_now.isoformat.return_value = "2023-01-01T12:00:00"
            mock_datetime.now.return_value = mock_now

            # Call
            path_str, sidebar_url = save_html_report(
                content, "Test Slug Input", session_name="Test Session"
            )

            # Verify
            expected_filename = "test_slug_20230101_120000.html"
            expected_path = archive_dir / "results" / expected_filename

            assert path_str == str(expected_path)
            assert expected_path.exists()
            assert expected_path.read_text() == "<htmled># Test Content</htmled>"

            # Verify sidebar index
            index_path = archive_dir / "index.html"
            assert index_path.exists()
            index_content = index_path.read_text()
            assert "results/test_slug_20230101_120000.html" in index_content
            assert "Test Slug Input" in index_content
            assert '"session_name": "Test Session"' in index_content
            assert '"prefix": "test slug input"' in index_content


def test_save_html_report_no_hint():
    """Test saving without a hint extracts H1 title from content."""
    # Content with H1 header - title should be extracted
    content = "# Test Content"

    with tempfile.TemporaryDirectory() as temp_dir:
        archive_dir = Path(temp_dir)

        with (
            patch("asky.rendering.ARCHIVE_DIR", archive_dir),
            patch(
                "asky.rendering._create_html_content",
                return_value="<htmled># Test Content</htmled>",
            ),
            patch(
                "asky.rendering.generate_slug",
                side_effect=lambda t, max_words: (
                    "untitled" if t == "untitled" else "test_content"
                ),
            ),
            patch("asky.rendering.datetime") as mock_datetime,
        ):
            mock_now = MagicMock()
            mock_now.strftime.side_effect = ["20230101_120000", "2023-01-01 12:00"]
            mock_now.isoformat.return_value = "2023-01-01T12:00:00"
            mock_datetime.now.return_value = mock_now

            path_str, sidebar_url = save_html_report(content)

            # Now extracts "Test Content" from H1 header
            expected_filename = "test_content_20230101_120000.html"
            assert Path(path_str).name == expected_filename

            # Verify prefix in sidebar
            index_path = archive_dir / "index.html"
            index_content = index_path.read_text()
            assert '"prefix": "test content"' in index_content


def test_sidebar_groups_and_sorting():
    """Test that updating the sidebar accumulates entries correctly."""
    from asky.rendering import _update_sidebar_index
    import json

    with tempfile.TemporaryDirectory() as temp_dir:
        archive_dir = Path(temp_dir)

        with patch("asky.rendering.ARCHIVE_DIR", archive_dir):
            # First entry
            _update_sidebar_index(
                "slug_one_20230101_120000.html", "Title One", "Session A"
            )
            # Second entry (same session)
            _update_sidebar_index(
                "slug_two_20230101_130000.html", "Title Two", "Session A"
            )
            # Third entry (same prefix, different session)
            _update_sidebar_index(
                "slug_one_more_20230101_140000.html", "Title Three", "Session B"
            )

            index_path = archive_dir / "index.html"

            content = index_path.read_text()
            marker_start = "/* ENTRIES_JSON_START */"
            marker_end = "/* ENTRIES_JSON_END */"
            json_str = content.split(marker_start)[1].split(marker_end)[0].strip()
            entries = json.loads(json_str)

            assert len(entries) == 3
            # Most recent first
            assert (
                entries[0]["filename"] == "results/slug_one_more_20230101_140000.html"
            )
            assert entries[0]["session_name"] == "Session B"
            assert entries[0]["prefix"] == "title three"

            assert entries[1]["filename"] == "results/slug_two_20230101_130000.html"
            assert entries[1]["prefix"] == "title two"

            assert entries[2]["filename"] == "results/slug_one_20230101_120000.html"
            assert entries[2]["session_name"] == "Session A"
            assert entries[2]["prefix"] == "title one"


def test_extract_markdown_title():
    """Test title extraction from markdown content with headers and heuristics."""
    from asky.rendering import extract_markdown_title

    # Basic H1 extraction
    assert extract_markdown_title("# Hello World\n\nSome content") == "Hello World"

    # H1 with trailing spaces
    assert extract_markdown_title("# Trailing   \n\nContent") == "Trailing"

    # H1 not at beginning (H2 first) - H1 should still win if H2 is generic
    assert (
        extract_markdown_title("## Query\n\n# Main Title\n\nContent") == "Main Title"
    )

    # H2 extraction when H1 is missing
    assert extract_markdown_title("## My Detailed Topic\n\nSome body") == "My Detailed Topic"

    # Heuristic extraction (first non-empty line)
    assert (
        extract_markdown_title("This is a plain text response\nwith multiple lines.")
        == "This is a plain text response"
    )

    # Filter generic headers
    assert extract_markdown_title("## Query\n\nSome body") == "Some body"

    # Empty/None input
    assert extract_markdown_title("") is None
    assert extract_markdown_title(None) is None
