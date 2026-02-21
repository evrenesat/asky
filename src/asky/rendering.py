"""Browser rendering utilities for asky."""

import logging
import re
import tempfile
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional

from asky.config import ARCHIVE_DIR
from asky.core.utils import generate_slug

logger = logging.getLogger(__name__)


# Regex pattern to extract H1 markdown header (# Title)
H1_PATTERN = re.compile(r"^#\s+(.+?)(?:\n|$)", re.MULTILINE)


def extract_markdown_title(content: str) -> Optional[str]:
    """Extract the first H1 markdown header from content.

    Args:
        content: The markdown content to search.

    Returns:
        The title text if found, None otherwise.
    """
    if not content:
        return None

    match = H1_PATTERN.search(content)
    if match:
        return match.group(1).strip()
    return None


def _create_html_content(content: str) -> str:
    """Wrap content in HTML template."""
    from asky.config import TEMPLATE_PATH

    if not TEMPLATE_PATH.exists():
        logger.warning(f"Template not found at {TEMPLATE_PATH}")
        return f"<html><body><pre>{content}</pre></body></html>"

    with open(TEMPLATE_PATH, "r") as f:
        template = f.read()

    # Escape backticks for JS template literal
    safe_content = content.replace("`", "\\`").replace("${", "\\${")
    return template.replace("{{CONTENT}}", safe_content)


def render_to_browser(content: str, filename_hint: Optional[str] = None) -> None:
    """Render markdown content in a browser using a template.

    Args:
        content: The markdown content to render.
        filename_hint: Optional text to help generate a meaningful filename.
                       If not provided, attempts to extract H1 title from content.
    """
    try:
        html_content = _create_html_content(content)
        file_path = _save_to_archive(html_content, content, filename_hint)

        logger.info(f"[Opening browser: {file_path}]")
        webbrowser.open(f"file://{file_path}")
    except Exception as e:
        logger.error(f"Error rendering to browser: {e}")


def save_html_report(content: str, filename_hint: Optional[str] = None) -> str:
    """
    Save markdown content as an HTML report in the archive directory.
    Returns the absolute path to the saved file.
    """
    try:
        html_content = _create_html_content(content)
        file_path = _save_to_archive(html_content, content, filename_hint)
        return str(file_path)
    except Exception as e:
        logger.error(f"Error saving HTML report: {e}")
        return ""


def _update_sidebar_index(filename: str, display_title: str) -> None:
    """Update the sidebar index HTML file with the latest generated report link.

    Args:
        filename: The filename of the newly generated HTML report.
        display_title: The title to display for the link.
    """
    if not ARCHIVE_DIR.exists():
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    index_path = ARCHIVE_DIR / "sidebar_index.html"
    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    link_html = f'      <li class="index-item"><a href="{filename}" target="_parent">{display_title} <span class="time">{timestamp_str}</span></a></li>'

    if not index_path.exists():
        # Create base index file
        base_html = f"""<!doctype html>
<html>
  <head>
    <meta charset="UTF-8" />
    <title>asky History</title>
    <style>
      body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        font-size: 14px;
        line-height: 1.5;
        margin: 0;
        padding: 20px;
        color: #333;
        background-color: transparent;
      }}
      h2 {{
        font-size: 1.2em;
        margin-top: 0;
        margin-bottom: 15px;
        border-bottom: 1px solid #eaecef;
        padding-bottom: 10px;
      }}
      ul {{
        list-style: none;
        padding: 0;
        margin: 0;
      }}
      li.index-item {{
        margin-bottom: 8px;
        padding-bottom: 8px;
        border-bottom: 1px solid #f6f8fa;
      }}
      li.index-item a {{
        color: #0056b3;
        text-decoration: none;
        display: block;
      }}
      li.index-item a:hover {{
        text-decoration: underline;
      }}
      .time {{
        display: block;
        font-size: 0.85em;
        color: #6a737d;
        margin-top: 2px;
      }}
      @media (prefers-color-scheme: dark) {{
        body {{ color: #e0e0e0; }}
        h2, li.index-item {{ border-color: #30363d; }}
        li.index-item a {{ color: #58a6ff; }}
        .time {{ color: #8b949e; }}
      }}
    </style>
  </head>
  <body>
    <h2>History Index</h2>
    <ul id="index-list">
{link_html}
    </ul>
  </body>
</html>
"""
        with open(index_path, "w") as f:
            f.write(base_html)
    else:
        # Update existing index file
        with open(index_path, "r") as f:
            content = f.read()

        # Inject new link just after the <ul id="index-list"> tag
        target_tag = '<ul id="index-list">\n'
        if target_tag in content:
            new_content = content.replace(target_tag, f"{target_tag}{link_html}\n", 1)
            with open(index_path, "w") as f:
                f.write(new_content)
        else:
            logger.warning("Could not find <ul id='index-list'> in sidebar_index.html")


def _save_to_archive(
    html_content: str,
    markdown_content: Optional[str] = None,
    filename_hint: Optional[str] = None,
) -> Path:
    """Save HTML content to the archive directory with a unique name.

    Args:
        html_content: The HTML content to save.
        markdown_content: Original markdown content for title extraction.
        filename_hint: Explicit hint for filename (overrides title extraction).
    """
    if not ARCHIVE_DIR.exists():
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Priority: 1. Explicit hint, 2. Extracted H1 title, 3. "untitled"
    slug_source = filename_hint
    if not slug_source and markdown_content:
        extracted_title = extract_markdown_title(markdown_content)
        if extracted_title:
            slug_source = extracted_title
            logger.debug(f"Extracted title for filename: {extracted_title}")

    slug = generate_slug(slug_source or "untitled", max_words=5)

    filename = f"{slug}_{timestamp}.html"
    file_path = ARCHIVE_DIR / filename

    with open(file_path, "w") as f:
        f.write(html_content)

    # Update the sidebar index
    # Note: slug_source should be the human-readable title without the timestamp suffix
    display_title = (
        slug_source if slug_source and slug_source != "untitled" else "Query Result"
    )
    _update_sidebar_index(filename, display_title)

    return file_path
