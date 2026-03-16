"""Plugin page extension registry for GUI plugin."""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, List

from asky.plugins.gui_server.pages.layout import page_layout
from asky.plugins.hook_types import GUIPageSpec

logger = logging.getLogger(__name__)


class PluginPageRegistry:
    """Collects extension pages and mounts them safely."""

    def __init__(self) -> None:
        self._pages: List[GUIPageSpec] = []

    def register_page(self, spec: GUIPageSpec) -> None:
        """Register an extension page."""
        normalized_route = _normalize_route(spec.route)
        self._pages.append(
            GUIPageSpec(
                route=normalized_route,
                title=str(spec.title or normalized_route),
                render=spec.render,
                nav_title=spec.nav_title,
            )
        )

    def list_pages(self) -> List[GUIPageSpec]:
        """Return registered pages in order."""
        return list(self._pages)

    def mount_pages(self, ui: Any) -> None:
        """Mount all pages; per-page failures are isolated."""
        for page in self._pages:
            try:
                route = page.route
                mounted_page = _build_page_handler(ui, page.title, page.render, route)
                ui.page(route)(mounted_page)

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
        with page_layout("Plugin Extensions"):
            pages = registry.list_pages()
            if not pages:
                ui.label("No plugin pages registered.").classes("text-slate-500 italic")
                return

            with ui.column().classes("gap-4"):
                for page in pages:
                    with ui.card().classes("w-full asky-card"):
                        with ui.row().classes("items-center justify-between w-full"):
                            with ui.column():
                                ui.label(page.title).classes("text-xl font-semibold")
                                ui.label(page.route).classes("text-sm text-slate-500")
                            ui.button(
                                "Open", on_click=lambda p=page: ui.navigate.to(p.route)
                            ).props("outline")


def _normalize_route(route: str) -> str:
    normalized = str(route or "").strip()
    if not normalized:
        return "/"
    if not normalized.startswith("/"):
        return "/" + normalized
    return normalized


def _path_parameter_names(route: str) -> list[str]:
    return [match.group(1).split(":", 1)[0] for match in re.finditer(r"{([^}]+)}", route)]


def _build_page_handler(
    ui: Any,
    title: str,
    render_fn: Callable[..., None],
    route: str,
) -> Callable[..., None]:
    path_parameter_names = _path_parameter_names(route)
    namespace: dict[str, Any] = {
        "page_layout": page_layout,
        "render_fn": render_fn,
        "title": title,
        "ui": ui,
    }
    parameters = ", ".join(f"{name}: str" for name in path_parameter_names)
    title_kwargs = ", ".join(f"{name}={name}" for name in path_parameter_names)
    render_kwargs = ", ".join(f"{name}={name}" for name in path_parameter_names)

    if path_parameter_names:
        source = f"""
def _mounted_page({parameters}) -> None:
    try:
        display_title = title.format({title_kwargs})
    except KeyError:
        display_title = title
    with page_layout(display_title):
        render_fn(ui, {render_kwargs})
"""
    else:
        source = """
def _mounted_page() -> None:
    with page_layout(title):
        render_fn(ui)
"""

    exec(source, namespace)
    return namespace["_mounted_page"]


_GLOBAL_PAGE_REGISTRY = PluginPageRegistry()


def get_plugin_page_registry() -> PluginPageRegistry:
    """Return process-global page registry for extension hooks."""
    return _GLOBAL_PAGE_REGISTRY
