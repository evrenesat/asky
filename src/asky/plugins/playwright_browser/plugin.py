"""Playwright Browser Plugin for asky."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from asky.plugins.base import AskyPlugin, PluginContext
from asky.plugins.hook_types import FETCH_URL_OVERRIDE, FetchURLContext

logger = logging.getLogger(__name__)


class PlaywrightBrowserPlugin(AskyPlugin):
    """Plugin that uses Playwright to fetch URLs when certain conditions are met."""

    @classmethod
    def get_cli_contributions(cls) -> list:
        from asky.plugins.base import CapabilityCategory, CLIContribution

        return [
            CLIContribution(
                category=CapabilityCategory.BROWSER_SETUP,
                flags=("--browser",),
                kwargs=dict(
                    dest="playwright_login",
                    metavar="URL",
                    default=None,
                    help="Open an interactive browser session at URL for login or extension setup.",
                ),
            ),
        ]

    def activate(self, context: PluginContext) -> None:
        from asky.plugins.playwright_browser.browser import PlaywrightBrowserManager

        config = context.config or {}

        self._intercept = config.get(
            "intercept",
            ["get_url_content", "get_url_details", "research", "shortlist", "default"],
        )

        self._browser_manager = PlaywrightBrowserManager(
            data_dir=context.data_dir,
            browser_type=config.get("browser", "chromium"),
            persist_session=config.get("persist_session", True),
            same_site_min_delay_ms=config.get("same_site_min_delay_ms", 1500),
            same_site_max_delay_ms=config.get("same_site_max_delay_ms", 4000),
            page_timeout_ms=config.get("page_timeout_ms", 30000),
            network_idle_timeout_ms=config.get("network_idle_timeout_ms", 2000),
            keep_browser_open=config.get("keep_browser_open", True),
        )

        context.hook_registry.register(
            FETCH_URL_OVERRIDE,
            self._on_fetch_url_override,
            plugin_name=context.plugin_name,
        )
        logger.debug("PlaywrightBrowserPlugin activated with intercept=%s", self._intercept)

    def deactivate(self) -> None:
        self._browser_manager.close()

    def _on_fetch_url_override(self, ctx: FetchURLContext) -> None:
        import trafilatura
        from asky.retrieval import (
            MAX_TITLE_CHARS,
            _extract_and_normalize_links,
            _extract_main_content,
            _derive_title,
        )

        tc = ctx.trace_context or {}
        site = tc.get("tool_name") or tc.get("source", "") or "default"

        if site not in self._intercept:
            return

        logger.info("Playwright intercepting fetch for URL: %s (site=%s)", ctx.url, site)

        try:
            html, final_url = self._browser_manager.fetch_page(ctx.url)
        except ImportError as e:
            if not getattr(self, "_has_warned_missing_dep", False):
                try:
                    from rich.console import Console
                    console = Console()
                    console.print()
                    console.print("[bold yellow]Playwright Plugin:[/bold yellow] [red]Playwright is not installed.[/red]")
                    console.print("To use browser-based retrieval, please run: [cyan]uv pip install 'asky-cli[playwright]'[/cyan]")
                    console.print("Falling back to default retrieval pipeline.\n")
                except ImportError:
                    import sys
                    print("\n[Playwright Plugin] Playwright is not installed.", file=sys.stderr)
                    print("[Playwright Plugin] To use browser-based retrieval, please run: uv pip install 'asky-cli[playwright]'", file=sys.stderr)
                    print("[Playwright Plugin] Falling back to default retrieval pipeline.\n", file=sys.stderr)
                self._has_warned_missing_dep = True
            logger.warning("Playwright fetch failed: %s. Falling back to default pipeline.", e)
            return
        except Exception as e:
            logger.warning("Playwright fetch failed for %s: %s. Falling back to default pipeline.", ctx.url, e)
            return

        extracted = _extract_main_content(
            html=html,
            source_url=final_url,
            output_format=ctx.output_format,
        )

        content = extracted.get("content", "")
        title = extracted.get("title", "") or _derive_title(content, final_url)
        warning = extracted.get("warning")
        page_type = extracted.get("page_type", "article")
        
        # We preserve Trafilatura metadata extraction for the date if possible
        date = None
        try:
            metadata = trafilatura.extract_metadata(html)
            if metadata and metadata.date:
                date = str(metadata.date)
            if metadata and not title and metadata.title:
                title = metadata.title[:MAX_TITLE_CHARS]
        except Exception:
            pass

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
            "source": f"playwright/{extracted.get('source', 'unknown')}",
            "output_format": ctx.output_format,
            "page_type": page_type,
            "warning": warning,
        }

    def run_login_session(self, url: str) -> None:
        """Manually trigger a login session."""
        self._browser_manager.open_login_session(url)
