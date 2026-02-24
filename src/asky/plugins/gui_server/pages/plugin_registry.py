"""Plugin page extension registry for GUI plugin."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, List

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RegisteredPage:
    """One plugin-provided UI page descriptor."""

    route: str
    title: str
    render: Callable[[Any], None]


class PluginPageRegistry:
    """Collects extension pages and mounts them safely."""

    def __init__(self) -> None:
        self._pages: List[RegisteredPage] = []

    def register_page(
        self,
        *,
        route: str,
        title: str,
        render: Callable[[Any], None],
    ) -> None:
        """Register an extension page."""
        normalized_route = _normalize_route(route)
        self._pages.append(
            RegisteredPage(
                route=normalized_route,
                title=str(title or normalized_route),
                render=render,
            )
        )

    def list_pages(self) -> List[RegisteredPage]:
        """Return registered pages in order."""
        return list(self._pages)

    def mount_pages(self, ui: Any) -> None:
        """Mount all pages; per-page failures are isolated."""
        for page in self._pages:
            try:
                route = page.route
                render_fn = page.render

                @ui.page(route)
                def _mounted_page(render_fn: Callable[[Any], None] = render_fn) -> None:
                    render_fn(ui)

            except Exception:
                logger.exception(
                    "Failed to mount GUI page route=%s title=%s",
                    page.route,
                    page.title,
                )


def mount_plugin_registry_page(ui: Any, registry: PluginPageRegistry) -> None:
    """Mount a simple index page listing extension routes."""

    @ui.page("/plugins")
    def _plugin_pages_index() -> None:
        ui.label("Plugin UI Pages")
        pages = registry.list_pages()
        if not pages:
            ui.label("No plugin pages registered.")
            return
        for page in pages:
            ui.link(page.title, page.route)


def _normalize_route(route: str) -> str:
    normalized = str(route or "").strip()
    if not normalized:
        return "/"
    if not normalized.startswith("/"):
        return "/" + normalized
    return normalized


_GLOBAL_PAGE_REGISTRY = PluginPageRegistry()


def get_plugin_page_registry() -> PluginPageRegistry:
    """Return process-global page registry for extension hooks."""
    return _GLOBAL_PAGE_REGISTRY
