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


def test_save_html_report_session_deduplication():
    """Test that saving multiple reports for the same session ID overwrites instead of appending."""
    content1 = "# First Turn"
    content2 = "# Second Turn"

    import json
    from unittest.mock import MagicMock

    with tempfile.TemporaryDirectory() as temp_dir:
        archive_dir = Path(temp_dir)

        with (
            patch("asky.rendering.ARCHIVE_DIR", archive_dir),
            patch("asky.rendering._create_html_content", return_value="<html></html>"),
            patch("asky.rendering.generate_slug", return_value="test_slug"),
            patch("asky.rendering.datetime") as mock_datetime,
        ):
            mock_now = MagicMock()
            mock_now.strftime.side_effect = ["20230101_120000", "2023-01-01 12:00", "20230101_120001", "2023-01-01 12:01"]
            mock_now.isoformat.side_effect = ["2023-01-01T12:00:00", "2023-01-01T12:01:00"]
            mock_datetime.now.return_value = mock_now

            # First save
            path_str1, _ = save_html_report(content1, "Test Slug Input", session_name="Sess", session_id=42)
            assert "_s42.html" in path_str1
            assert Path(path_str1).exists()

            # Second save
            path_str2, _ = save_html_report(content2, "Test Slug Input", session_name="Sess", session_id=42)
            assert "_s42.html" in path_str2
            assert Path(path_str2).exists()
            assert not Path(path_str1).exists()  # Old file should be deleted
            
            # Check sidebar entries
            index_path = archive_dir / "index.html"
            content = index_path.read_text()
            marker_start = "/* ENTRIES_JSON_START */"
            marker_end = "/* ENTRIES_JSON_END */"
            json_str = content.split(marker_start)[1].split(marker_end)[0].strip()
            entries = json.loads(json_str)

            assert len(entries) == 1
            assert entries[0]["session_id"] == 42
            assert entries[0]["filename"] == f"results/{Path(path_str2).name}"


def test_save_html_report_deletes_all_superseded_session_snapshots():
    """Test that a new save removes all prior files for the same session_id if they exist in the index."""
    import json
    from unittest.mock import MagicMock

    with tempfile.TemporaryDirectory() as temp_dir:
        archive_dir = Path(temp_dir)
        results_dir = archive_dir / "results"
        results_dir.mkdir()

        # Pre-seed index.html with two existing entries for session 42
        f1_name = "results/old_1_s42.html"
        f2_name = "results/old_2_s42.html"
        (archive_dir / f1_name).write_text("old1")
        (archive_dir / f2_name).write_text("old2")

        entries = [
            {"filename": f1_name, "title": "Old 1", "session_id": 42},
            {"filename": f2_name, "title": "Old 2", "session_id": 42},
            {"filename": "results/other.html", "title": "Other", "session_id": 99}
        ]
        entries_json = json.dumps(entries)
        base_html = f"/* ENTRIES_JSON_START */ {entries_json} /* ENTRIES_JSON_END */"
        (archive_dir / "index.html").write_text(base_html)

        with (
            patch("asky.rendering.ARCHIVE_DIR", archive_dir),
            patch("asky.rendering._create_html_content", return_value="<html></html>"),
            patch("asky.rendering.generate_slug", return_value="test_slug"),
        ):
            # Save new report for session 42
            path_str_new, _ = save_html_report("# New Turn", "Hint", session_name="Sess", session_id=42)
            assert Path(path_str_new).exists()
            
            # The old files should be deleted
            assert not (archive_dir / f1_name).exists()
            assert not (archive_dir / f2_name).exists()

            # Check sidebar entries
            index_path = archive_dir / "index.html"
            content = index_path.read_text()
            marker_start = "/* ENTRIES_JSON_START */"
            marker_end = "/* ENTRIES_JSON_END */"
            json_str = content.split(marker_start)[1].split(marker_end)[0].strip()
            new_entries = json.loads(json_str)

            # Should be exactly one entry for session 42, plus the other session's entry
            assert len(new_entries) == 2
            s42_entries = [e for e in new_entries if e.get("session_id") == 42]
            assert len(s42_entries) == 1
            assert s42_entries[0]["filename"] == f"results/{Path(path_str_new).name}"


def test_save_html_report_absorbs_converted_history():
    """Test that a converted history message's report is absorbed by the session."""
    import json

    with tempfile.TemporaryDirectory() as temp_dir:
        archive_dir = Path(temp_dir)

        with (
            patch("asky.rendering.ARCHIVE_DIR", archive_dir),
            patch("asky.rendering._create_html_content", return_value="<html></html>"),
            patch("asky.rendering.generate_slug", return_value="test_slug"),
        ):
            # Save single-turn report
            path_str1, _ = save_html_report("# Single Turn", "Hint", message_id=99)
            assert Path(path_str1).exists()

            # Save session report after conversion
            path_str2, _ = save_html_report("# Session Turn", "Hint", session_name="Sess", session_id=42, converted_message_id=99)
            assert Path(path_str2).exists()
            assert not Path(path_str1).exists()  # Single-turn report should be deleted
            
            # Check sidebar entries
            index_path = archive_dir / "index.html"
            content = index_path.read_text()
            marker_start = "/* ENTRIES_JSON_START */"
            marker_end = "/* ENTRIES_JSON_END */"
            json_str = content.split(marker_start)[1].split(marker_end)[0].strip()
            entries = json.loads(json_str)

            assert len(entries) == 1
            assert entries[0]["session_id"] == 42
            assert entries[0]["filename"] == f"results/{Path(path_str2).name}"
