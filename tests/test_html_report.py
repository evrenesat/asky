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
            mock_now.strftime.return_value = "20230101_120000"
            mock_datetime.now.return_value = mock_now

            # Call
            path_str, sidebar_url = save_html_report(content, "Test Slug Input")

            # Verify
            expected_filename = "test_slug_20230101_120000.html"
            expected_path = archive_dir / expected_filename

            assert path_str == str(expected_path)
            assert expected_path.exists()
            assert expected_path.read_text() == "<htmled># Test Content</htmled>"


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
            mock_now.strftime.return_value = "20230101_120000"
            mock_datetime.now.return_value = mock_now

            path_str, sidebar_url = save_html_report(content)

            # Now extracts "Test Content" from H1 header
            expected_filename = "test_content_20230101_120000.html"
            assert Path(path_str).name == expected_filename


def test_save_html_report_no_hint_no_h1():
    """Test saving without a hint and no H1 falls back to untitled."""
    # Content without H1 header - should use "untitled"
    content = "Some plain text without a header"

    with tempfile.TemporaryDirectory() as temp_dir:
        archive_dir = Path(temp_dir)

        with (
            patch("asky.rendering.ARCHIVE_DIR", archive_dir),
            patch(
                "asky.rendering._create_html_content",
                return_value="<htmled>Some plain text</htmled>",
            ),
            patch(
                "asky.rendering.generate_slug",
                side_effect=lambda t, max_words: (
                    "untitled" if t == "untitled" else "slug"
                ),
            ),
            patch("asky.rendering.datetime") as mock_datetime,
        ):
            mock_now = MagicMock()
            mock_now.strftime.return_value = "20230101_120000"
            mock_datetime.now.return_value = mock_now

            path_str, sidebar_url = save_html_report(content)

            expected_filename = "untitled_20230101_120000.html"
            assert Path(path_str).name == expected_filename


def test_extract_markdown_title():
    """Test H1 title extraction from markdown content."""
    from asky.rendering import extract_markdown_title

    # Basic H1 extraction
    assert extract_markdown_title("# Hello World\n\nSome content") == "Hello World"

    # H1 with trailing spaces
    assert extract_markdown_title("# Trailing   \n\nContent") == "Trailing"

    # H1 not at beginning (H2 first)
    assert (
        extract_markdown_title("## Subheading\n\n# Main Title\n\nContent")
        == "Main Title"
    )

    # No H1 present
    assert extract_markdown_title("Just some text") is None
    assert extract_markdown_title("## Only H2") is None

    # Empty/None input
    assert extract_markdown_title("") is None
    assert extract_markdown_title(None) is None
