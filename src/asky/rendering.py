"""Browser rendering utilities for asky."""

import logging
import tempfile
import webbrowser
from pathlib import Path

logger = logging.getLogger(__name__)


def render_to_browser(content: str) -> None:
    """Render markdown content in a browser using a template."""
    try:
        from asky.config import TEMPLATE_PATH

        if not TEMPLATE_PATH.exists():
            logger.info(f"Error: Template not found at {TEMPLATE_PATH}")
            return

        with open(TEMPLATE_PATH, "r") as f:
            template = f.read()

        # Escape backticks for JS template literal
        safe_content = content.replace("`", "\\`").replace("${", "\\${")

        html_content = template.replace("{{CONTENT}}", safe_content)

        with tempfile.NamedTemporaryFile(
            "w", delete=False, suffix=".html", prefix="temp_asky_"
        ) as f:
            f.write(html_content)
            temp_path = f.name

        logger.info(f"[Opening browser: {temp_path}]")
        webbrowser.open(f"file://{temp_path}")
    except Exception as e:
        logger.info(f"Error rendering to browser: {e}")
