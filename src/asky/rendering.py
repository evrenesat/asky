"""Browser rendering utilities for asky."""

import logging
import re
import tempfile
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

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


def save_html_report(
    content: str, filename_hint: Optional[str] = None, session_name: str = ""
) -> Tuple[str, str]:
    """
    Save markdown content as an HTML report in the archive directory.
    Returns a tuple of (absolute_path_to_file, absolute_path_to_sidebar_wrapped_file).
    """
    try:
        html_content = _create_html_content(content)
        file_path = _save_to_archive(
            html_content, content, filename_hint, session_name=session_name
        )

        index_path = ARCHIVE_DIR / "sidebar_index.html"
        sidebar_url = f"file://{index_path}#{file_path.name}"

        return str(file_path), sidebar_url
    except Exception as e:
        logger.error(f"Error saving HTML report: {e}")
        return "", ""


def _update_sidebar_index(
    filename: str, display_title: str, session_name: str = ""
) -> None:
    """Update the sidebar index HTML file with the latest generated report.

    Args:
        filename: The filename of the newly generated HTML report.
        display_title: The title to display for the link.
        session_name: The name of the session this report belongs to.
    """
    if not ARCHIVE_DIR.exists():
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    index_path = ARCHIVE_DIR / "sidebar_index.html"
    now = datetime.now()
    timestamp_str = now.strftime("%Y-%m-%d %H:%M")
    iso_timestamp = now.isoformat()

    # Create prefix (first 3 words of filename slug)
    # Filename format: {slug}_{timestamp}.html
    slug_part = filename.rsplit("_", 2)[0]
    prefix = " ".join(slug_part.replace("_", " ").split()[:3]).lower()

    new_entry = {
        "filename": filename,
        "title": display_title,
        "timestamp": timestamp_str,
        "iso_timestamp": iso_timestamp,
        "session_name": session_name,
        "prefix": prefix,
    }

    import json

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
            logger.warning(f"Could not parse existing sidebar_index.html: {e}")

    # Add new entry (avoid duplicates)
    if not any(e.get("filename") == filename for e in entries):
        entries.insert(0, new_entry)

    # Clean up entries (keep them unique and sorted by date by default)
    # We always rewrite the file to ensure the JS logic is up to date
    entries_json = json.dumps(entries, indent=2)

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
        padding: 0;
        color: #333;
        background-color: #f6f8fa;
        display: flex;
        height: 100vh;
        overflow: hidden;
      }}
      .sidebar {{
        width: 320px;
        flex-shrink: 0;
        background-color: #fff;
        border-right: 1px solid #eaecef;
        display: flex;
        flex-direction: column;
        height: 100%;
      }}
      .sidebar-header {{
        padding: 15px;
        border-bottom: 1px solid #eaecef;
        background: #fff;
      }}
      .sidebar-header h2 {{
        font-size: 1.1em;
        margin: 0 0 10px 0;
      }}
      .controls {{
        display: flex;
        gap: 5px;
        margin-bottom: 5px;
      }}
      .btn {{
        background: #f3f4f6;
        border: 1px solid #d1d5db;
        border-radius: 4px;
        padding: 4px 8px;
        font-size: 11px;
        cursor: pointer;
        color: #374151;
      }}
      .btn:hover {{ background: #e5e7eb; }}
      .btn.active {{ background: #0366d6; color: #fff; border-color: #0366d6; }}

      .index-list-container {{
        flex-grow: 1;
        overflow-y: auto;
        padding: 0;
      }}
      ul {{
        list-style: none;
        padding: 0;
        margin: 0;
      }}
      .index-item {{
        border-bottom: 1px solid #f6f8fa;
      }}
      .index-item a {{
        color: #0056b3;
        text-decoration: none;
        display: block;
        padding: 10px 15px;
        transition: background 0.1s;
      }}
      .index-item a:hover {{ background-color: #f6f8fa; }}
      .index-item a.active {{ background-color: #eaf5ff; border-left: 3px solid #0366d6; font-weight: 500; }}
      .time {{ display: block; font-size: 0.8em; color: #6a737d; margin-top: 2px; }}
      .session-tag {{ font-size: 0.75em; color: #0366d6; background: #eaf5ff; padding: 1px 4px; border-radius: 3px; display: inline-block; margin-top: 3px; }}

      .group-header {{
        background: #f1f5f9;
        padding: 6px 15px;
        font-weight: 600;
        font-size: 0.85em;
        cursor: pointer;
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 1px solid #e2e8f0;
      }}
      .group-header:hover {{ background: #e2e8f0; }}
      .badge {{ background: #64748b; color: white; border-radius: 10px; padding: 1px 6px; font-size: 0.75em; }}

      .content-area {{
        flex-grow: 1;
        height: 100%;
        background: #fff;
      }}
      #content-frame {{
        width: 100%;
        height: 100%;
        border: none;
      }}
      @media (prefers-color-scheme: dark) {{
        body {{ background-color: #0d1117; color: #e0e0e0; }}
        .sidebar, .sidebar-header, .content-area, .group-header {{ background-color: #161b22; color: #c9d1d9; }}
        .sidebar, .sidebar-header, .index-item, .btn, .group-header {{ border-color: #30363d; }}
        .btn {{ background: #21262d; color: #c9d1d9; }}
        .index-item a {{ color: #58a6ff; }}
        .index-item a:hover {{ background-color: #21262d; }}
        .index-item a.active {{ background-color: #172a3a; }}
        .time {{ color: #8b949e; }}
        .session-tag {{ background: #11263d; color: #58a6ff; }}
        .group-header:hover {{ background: #21262d; }}
      }}
    </style>
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

      const list = document.getElementById('index-list');
      const frame = document.getElementById('content-frame');
      const state = {{
        sort: 'date',
        group: false,
        collapsedGroups: new Set()
      }};

      function render() {{
        let items = [...ENTRIES];

        if (state.sort === 'alpha') {{
          items.sort((a, b) => a.title.localeCompare(b.title));
        }} else {{
          items.sort((a, b) => b.iso_timestamp.localeCompare(a.iso_timestamp));
        }}

        list.innerHTML = '';

        if (state.group) {{
          const groups = [];
          items.forEach(item => {{
            const groupId = item.session_name || item.prefix || 'Other';
            let group = groups.find(g => g.id === groupId);
            if (!group) {{
               group = {{ id: groupId, name: groupId, items: [] }};
               groups.push(group);
            }}
            group.items.push(item);
          }});

          groups.forEach(group => {{
            const groupEl = document.createElement('div');
            const isCollapsed = state.collapsedGroups.has(group.id);

            groupEl.innerHTML = `
              <div class="group-header" onclick="toggleGroup('${{group.id}}')">
                <span>${{group.name}}</span>
                <span class="badge">${{group.items.length}}</span>
              </div>
            `;
            if (!isCollapsed) {{
              const ul = document.createElement('ul');
              group.items.forEach(item => ul.appendChild(createItemEl(item)));
              groupEl.appendChild(ul);
            }}
            list.appendChild(groupEl);
          }});
        }} else {{
          items.forEach(item => list.appendChild(createItemEl(item)));
        }}
        highlightActive();
      }}

      function createItemEl(item) {{
        const li = document.createElement('li');
        li.className = 'index-item';
        const sessionHtml = item.session_name ? `<span class="session-tag">${{item.session_name}}</span>` : '';
        li.innerHTML = `
          <a href="#${{item.filename}}" onclick="window.location.hash='${{item.filename}}'; return false;">
            ${{item.title}}
            ${{sessionHtml}}
            <span class="time">${{item.timestamp}}</span>
          </a>
        `;
        return li;
      }}

      function toggleGroup(id) {{
        if (state.collapsedGroups.has(id)) state.collapsedGroups.delete(id);
        else state.collapsedGroups.add(id);
        render();
      }}

      function highlightActive() {{
        const hash = window.location.hash.substring(1);
        list.querySelectorAll('a').forEach(a => {{
          if (a.getAttribute('href') === '#' + hash) a.classList.add('active');
          else a.classList.remove('active');
        }});
      }}

      document.getElementById('sort-date').onclick = (e) => {{
        state.sort = 'date';
        e.target.classList.add('active');
        document.getElementById('sort-alpha').classList.remove('active');
        render();
      }};
      document.getElementById('sort-alpha').onclick = (e) => {{
        state.sort = 'alpha';
        e.target.classList.add('active');
        document.getElementById('sort-date').classList.remove('active');
        render();
      }};
      document.getElementById('toggle-group').onclick = (e) => {{
        state.group = !state.group;
        e.target.classList.toggle('active', state.group);
        render();
      }};

      function loadFromHash() {{
        const hash = window.location.hash.substring(1);
        if (hash) {{
          frame.src = hash;
          highlightActive();
        }} else if (ENTRIES.length > 0) {{
          window.location.hash = ENTRIES[0].filename;
        }}
      }}

      window.addEventListener('hashchange', loadFromHash);
      window.onload = () => {{ loadFromHash(); render(); }};
    </script>
  </body>
</html>
"""
    with open(index_path, "w") as f:
        f.write(base_html)


def _save_to_archive(
    html_content: str,
    markdown_content: Optional[str] = None,
    filename_hint: Optional[str] = None,
    session_name: str = "",
) -> Path:
    """Save HTML content to the archive directory with a unique name.

    Args:
        html_content: The HTML content to save.
        markdown_content: Original markdown content for title extraction.
        filename_hint: Explicit hint for filename (overrides title extraction).
        session_name: The name of the session this report belongs to.
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
    _update_sidebar_index(filename, display_title, session_name=session_name)

    return file_path
