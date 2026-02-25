"""Playwright Browser Plugin for asky."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import trafilatura

from asky.plugins.base import AskyPlugin, PluginContext
from asky.plugins.hook_types import FETCH_URL_OVERRIDE, FetchURLContext
from asky.plugins.playwright_browser.browser import PlaywrightBrowserManager
from asky.retrieval import MAX_TITLE_CHARS, _extract_and_normalize_links

logger = logging.getLogger(__name__)


class PlaywrightBrowserPlugin(AskyPlugin):
    """Plugin that uses Playwright to fetch URLs when certain conditions are met."""

    def activate(self, context: PluginContext) -> None:
        config = context.config or {}

        self._intercept = config.get("intercept", ["get_url_content", "get_url_details"])

        self._browser_manager = PlaywrightBrowserManager(
            data_dir=context.data_dir,
            browser_type=config.get("browser", "chromium"),
            persist_session=config.get("persist_session", True),
            same_site_min_delay_ms=config.get("same_site_min_delay_ms", 1500),
            same_site_max_delay_ms=config.get("same_site_max_delay_ms", 4000),
            page_timeout_ms=config.get("page_timeout_ms", 30000),
            network_idle_timeout_ms=config.get("network_idle_timeout_ms", 2000),
        )

        context.hook_registry.register(FETCH_URL_OVERRIDE, self._on_fetch_url_override)
        logger.debug("PlaywrightBrowserPlugin activated with intercept=%s", self._intercept)

    def deactivate(self) -> None:
        self._browser_manager.close()

    def _on_fetch_url_override(self, ctx: FetchURLContext) -> None:
        tc = ctx.trace_context or {}
        site = tc.get("tool_name") or tc.get("source", "")

        if site not in self._intercept:
            return

        logger.info("Playwright intercepting fetch for URL: %s (site=%s)", ctx.url, site)

        try:
            html, final_url = self._browser_manager.fetch_page(ctx.url)
        except Exception as e:
            logger.warning("Playwright fetch failed for %s: %s. Falling back to default pipeline.", ctx.url, e)
            return

        content = trafilatura.extract(
            html,
            url=ctx.url,
            output_format=ctx.output_format,
            include_comments=False,
            include_tables=False
        )
        if content is None:
            content = ""

        metadata = trafilatura.extract_metadata(html)
        title = ""
        date = None
        if metadata:
            title = (metadata.title or "")[:MAX_TITLE_CHARS]
            date = str(metadata.date) if metadata.date else None

        links: List[Dict[str, str]] = []
        if ctx.include_links:
            links = _extract_and_normalize_links(html, ctx.url, ctx.max_links)

        ctx.result = {
            "error": None,
            "requested_url": ctx.url,
            "final_url": final_url,
            "content": content,
            "text": content,
            "title": title,
            "date": date,
            "links": links,
            "source": "playwright",
            "output_format": ctx.output_format,
            "page_type": "article",
        }

    def run_login_session(self, url: str) -> None:
        """Manually trigger a login session."""
        self._browser_manager.open_login_session(url)
