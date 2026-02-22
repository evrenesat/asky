import json
import logging
import re
import shutil
import webbrowser
from datetime import datetime
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Optional, Tuple

from asky.config import ARCHIVE_DIR
from asky.core.utils import generate_slug

logger = logging.getLogger(__name__)

# Source directory for static archive assets (JS, icons)
_DATA_DIR = Path(__file__).parent / "data"
_ICON_SRC = Path(__file__).parent.parent.parent / "assets" / "asky_icon_small.png"


# Helper functions to get dynamic archive paths (ensures reactivity to config changes/mocking)
def _get_assets_dir() -> Path:
    return ARCHIVE_DIR / "assets"


def _get_results_dir() -> Path:
    return ARCHIVE_DIR / "results"


def _get_results_assets_dir() -> Path:
    return _get_results_dir() / "assets"


def _asky_version() -> str:
    """Get the current version of the asky-cli package."""
    try:
        return _pkg_version("asky-cli")
    except Exception:
        return "0.0.0"


def _ensure_archive_assets() -> None:
    """Copy shared static assets to the archive directory if not already present.

    - Unversioned assets (CSS, icons) are copied only if missing (never overwritten).
    - Versioned assets (JS) are updated if a file with a different version exists.
    """
    if not ARCHIVE_DIR.exists():
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    current_ver = _asky_version()

    # Asset specifications: (src_name, dst_dir, dst_stem, is_versioned)
    specs = [
        ("asky-report.js", _get_results_assets_dir(), "asky-report", True),
        ("asky-report.css", _get_results_assets_dir(), "asky-report", False),
        ("asky-sidebar.js", _get_assets_dir(), "asky-sidebar", True),
        ("asky-sidebar.css", _get_assets_dir(), "asky-sidebar", False),
    ]

    for src_name, dst_dir, dst_stem, is_versioned in specs:
        if not dst_dir.exists():
            dst_dir.mkdir(parents=True, exist_ok=True)

        src_path = _DATA_DIR / src_name
        if not src_path.exists():
            continue

        ext = src_path.suffix  # e.g., .js or .css

        if is_versioned:
            # Look for any existing version of this asset in the destination dir
            pattern = f"{dst_stem}_v*{ext}"
            existing_files = list(dst_dir.glob(pattern))
            target_filename = f"{dst_stem}_v{current_ver}{ext}"
            target_path = dst_dir / target_filename

            # If no version of this file exists, or if the current version is missing
            if not target_path.exists():
                # Remove any OLD versions first
                for old_file in existing_files:
                    logger.debug(f"Removing stale asset: {old_file.name}")
                    old_file.unlink()
                # Copy current version
                shutil.copy2(src_path, target_path)
                logger.debug(f"Installed versioned asset: {target_filename}")
        else:
            # Unversioned: just check if <stem>.<ext> exists
            target_path = dst_dir / f"{dst_stem}{ext}"
            if not target_path.exists():
                shutil.copy2(src_path, target_path)
                logger.debug(f"Installed unversioned asset: {target_path.name}")

    # Special handling for icon (always unversioned, in sidebar assets)
    assets_dir = _get_assets_dir()
    icon_dst = assets_dir / "asky-icon.png"
    if _ICON_SRC.exists() and not icon_dst.exists():
        if not assets_dir.exists():
            assets_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_ICON_SRC, icon_dst)


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


def _create_html_content(content: str, title: str = "asky Output") -> str:
    """Wrap content in HTML template.

    Args:
        content: The markdown content to render.
        title: The page title shown in the browser tab.
    """
    from asky.config import TEMPLATE_PATH

    if not TEMPLATE_PATH.exists():
        logger.warning(f"Template not found at {TEMPLATE_PATH}")
        return f"<html><body><pre>{content}</pre></body></html>"

    with open(TEMPLATE_PATH, "r") as f:
        template = f.read()

    # Escape backticks for JS template literal
    safe_content = content.replace("`", "\\`").replace("${", "\\${")
    return (
        template.replace("{{TITLE}}", title)
        .replace("{{CONTENT}}", safe_content)
        .replace("{{ASSET_VERSION}}", _asky_version())
    )


def render_to_browser(content: str, filename_hint: Optional[str] = None) -> None:
    """Render markdown content in a browser using a template.

    Args:
        content: The markdown content to render.
        filename_hint: Optional text to help generate a meaningful filename.
                       If not provided, attempts to extract H1 title from content.
    """
    try:
        file_path = _save_to_archive(content, filename_hint)

        logger.info(f"[Opening browser: {file_path}]")
        webbrowser.open(f"file://{file_path}")
    except Exception as e:
        logger.error(f"Error rendering to browser: {e}")


def save_html_report(
    content: str, filename_hint: Optional[str] = None, session_name: str = ""
) -> Tuple[str, str]:
    """
    Save markdown content as an HTML report in the archive directory.
    Returns a tuple of (absolute_path_to_file, absolute_path_to_sidebar_wrapped_file).
    """
    try:
        file_path = _save_to_archive(content, filename_hint, session_name=session_name)

        index_path = ARCHIVE_DIR / "index.html"
        # The URL should fragment should contain the results/ subtree path
        sidebar_url = f"file://{index_path}#results/{file_path.name}"

        return str(file_path), sidebar_url
    except Exception as e:
        logger.error(f"Error saving HTML report: {e}")
        return "", ""


def _update_sidebar_index(
    filename: str,
    display_title: str,
    session_name: str = "",
    message_id: Optional[int] = None,
    session_id: Optional[int] = None,
) -> None:
    """Update the sidebar index HTML file with the latest generated report.

    Args:
        filename: The filename of the newly generated HTML report.
        display_title: The title to display for the link.
        session_name: The name of the session this report belongs to.
    """
    if not ARCHIVE_DIR.exists():
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    timestamp_str = now.strftime("%Y-%m-%d %H:%M")
    iso_timestamp = now.isoformat()

    # Derive prefix from the display title (first 3 words), preserving original casing
    # of words so that the JS side can compute longest common prefix against full titles.
    title_words = display_title.split()
    prefix = " ".join(title_words[:3]).lower()

    new_entry = {
        "filename": f"results/{filename}",
        "title": display_title,
        "timestamp": timestamp_str,
        "iso_timestamp": iso_timestamp,
        "session_name": session_name,
        "prefix": prefix,
        "message_id": message_id,
        "session_id": session_id,
    }

    current_ver = _asky_version()
    index_path = ARCHIVE_DIR / "index.html"
    entries = []

    if index_path.exists():
        try:
            with open(index_path, "r") as f:
                content = f.read()
                # Extract JSON from the ENTRIES_JSON marker
                marker_start = "/* ENTRIES_JSON_START */"
                marker_end = "/* ENTRIES_JSON_END */"
                if marker_start in content and marker_end in content:
                    json_str = (
                        content.split(marker_start)[1].split(marker_end)[0].strip()
                    )
                    entries = json.loads(json_str)
        except Exception as e:
            logger.warning(f"Could not parse existing index.html: {e}")

    # Add new entry (avoid duplicates)
    if not any(e.get("filename") == new_entry["filename"] for e in entries):
        entries.insert(0, new_entry)

    # Clean up entries (keep them unique and sorted by date by default)
    # We always rewrite the file to ensure the JS logic is up to date
    entries_json = json.dumps(entries, indent=2)

    base_html = f"""<!doctype html>
<html>
  <head>
    <meta charset="UTF-8" />
    <title>asky History</title>
    <link rel="icon" type="image/png" href="assets/asky-icon.png">
    <link rel="stylesheet" href="assets/asky-sidebar.css">
  </head>
  <body>
    <div class="sidebar">
      <div class="sidebar-header">
        <h2>asky History</h2>
        <div class="controls">
          <button id="sort-date" class="btn active">By Date</button>
          <button id="sort-alpha" class="btn">A-Z</button>
          <button id="toggle-group" class="btn">Group</button>
        </div>
      </div>
      <div class="index-list-container">
        <ul id="index-list"></ul>
      </div>
    </div>
    <div class="content-area">
      <iframe id="content-frame" name="content-frame"></iframe>
    </div>

    <script>
      const ENTRIES = /* ENTRIES_JSON_START */ {entries_json} /* ENTRIES_JSON_END */;
    </script>
    <script src="assets/asky-sidebar_v{current_ver}.js"></script>
  </body>
</html>
"""
    with open(index_path, "w") as f:
        f.write(base_html)


def _save_to_archive(
    markdown_content: str,
    filename_hint: Optional[str] = None,
    session_name: str = "",
    message_id: Optional[int] = None,
    session_id: Optional[int] = None,
) -> Path:
    """Save markdown content as an HTML report in the archive directory.

    Args:
        markdown_content: The raw markdown to render and save.
        filename_hint: Explicit hint for the display title and filename.
        session_name: The name of the session this report belongs to.
    """
    _ensure_archive_assets()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Priority: 1. Explicit hint, 2. Extracted H1 title, 3. "untitled"
    slug_source = filename_hint
    if not slug_source:
        extracted_title = extract_markdown_title(markdown_content)
        if extracted_title:
            slug_source = extracted_title
            logger.debug(f"Extracted title for filename: {extracted_title}")

    slug = generate_slug(slug_source or "untitled", max_words=5)
    display_title = (
        slug_source if slug_source and slug_source != "untitled" else "Query Result"
    )

    html_content = _create_html_content(markdown_content, title=display_title)

    filename = f"{slug}_{timestamp}.html"
    file_path = _get_results_dir() / filename

    with open(file_path, "w") as f:
        f.write(html_content)

    _update_sidebar_index(
        filename,
        display_title,
        session_name=session_name,
        message_id=message_id,
        session_id=session_id,
    )

    return file_path
