from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from asky.plugins.base import PluginContext
from asky.plugins.gui_server.pages.plugin_registry import get_plugin_page_registry
from asky.plugins.gui_server.plugin import GUIServerPlugin
from asky.plugins.manual_persona_creator.plugin import ManualPersonaCreatorPlugin
from asky.plugins.persona_manager.plugin import PersonaManagerPlugin
from asky.plugins.hooks import HookRegistry
from asky.plugins.hook_types import DAEMON_SERVER_REGISTER, DaemonServerRegisterContext


def _plugin_context(name: str, tmp_path: Path, hooks: HookRegistry) -> PluginContext:
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    config_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    return PluginContext(
        plugin_name=name,
        config_dir=config_dir,
        data_dir=data_dir,
        config={"host": "127.0.0.1", "port": 9900, "password": "pwd"},
        hook_registry=hooks,
        logger=logging.getLogger(f"test.{name}"),
    )


def test_gui_extension_registration_integration(tmp_path: Path):
    """
    Verify that activating all GUI-related plugins and invoking registration
    completes without error and registers expected routes.
    """
    hooks = HookRegistry()
    gui_plugin = GUIServerPlugin()
    manual_plugin = ManualPersonaCreatorPlugin()
    manager_plugin = PersonaManagerPlugin()

    # Activate all
    gui_ctx = _plugin_context("gui_server", tmp_path, hooks)
    gui_plugin.activate(gui_ctx)
    manual_plugin.activate(_plugin_context("manual_persona_creator", tmp_path, hooks))
    manager_plugin.activate(_plugin_context("persona_manager", tmp_path, hooks))

    # Trigger registration via DAEMON_SERVER_REGISTER
    payload = DaemonServerRegisterContext(service=object())
    hooks.invoke(DAEMON_SERVER_REGISTER, payload)

    # Assert no exception was raised and routes are registered
    registry = get_plugin_page_registry()
    pages = registry.list_pages()
    routes = {p.route for p in pages}

    # Persona routes
    assert "/personas" in routes
    assert "/personas/{name}" in routes
    # Session routes
    assert "/sessions" in routes
    # Web review routes
    assert "/web-review/{collection_id}" in routes
    assert "/web-review/{collection_id}/{page_id}" in routes

    # Assert job handlers are registered in the queue
    # We can check via gui_plugin._queue which was initialized during activate
    queue = gui_plugin._queue
    assert queue is not None
    assert "authored_book_ingest" in queue._handlers
    assert "source_ingest" in queue._handlers


def test_registered_pages_render_without_error(tmp_path: Path):
    """Verify that the render functions of registered pages can be called with a fake UI."""
    hooks = HookRegistry()
    gui_plugin = GUIServerPlugin()
    manual_plugin = ManualPersonaCreatorPlugin()
    manager_plugin = PersonaManagerPlugin()

    gui_plugin.activate(_plugin_context("gui_server", tmp_path, hooks))
    manual_plugin.activate(_plugin_context("manual_persona_creator", tmp_path, hooks))
    manager_plugin.activate(_plugin_context("persona_manager", tmp_path, hooks))

    # Trigger registration
    payload = DaemonServerRegisterContext(service=object())
    hooks.invoke(DAEMON_SERVER_REGISTER, payload)

    registry = get_plugin_page_registry()
    
    class FakeUI:
        def __init__(self):
            self.elements = []
        def label(self, text, **kwargs):
            self.elements.append(("label", text))
            return self
        def classes(self, *args, **kwargs): return self
        def props(self, *args, **kwargs): return self
        def on(self, *args, **kwargs): return self
        def set_text(self, *args): return self

        def button(self, text=None, icon=None, on_click=None, **kwargs):
            self.elements.append(("button", text or icon))
            return self
        def link(self, *a, **kw): return self
        def select(self, *a, **kw): return self
        def row(self):
            class Context:
                def __enter__(self): return self
                def __exit__(self, *a): pass
                def classes(self, *s): return self
            return Context()
        def column(self):
            class Context:
                def __enter__(self): return self
                def __exit__(self, *a): pass
                def classes(self, *s): return self
            return Context()
        def card(self):
            class Context:
                def __enter__(self): return self
                def __exit__(self, *a): pass
                def classes(self, *s): return self
                def on(self, *a, **kw): return self
            return Context()
        def tabs(self):
            class Context:
                def __enter__(self): return self
                def __exit__(self, *a): pass
                def classes(self, *s): return self
            return Context()
        def tab(self, *a, **kw): pass
        def tab_panels(self, *a, **kw):
            class Context:
                def __enter__(self): return self
                def __exit__(self, *a): pass
                def classes(self, *s): return self
            return Context()
        def tab_panel(self, *a, **kw):
            class Context:
                def __enter__(self): return self
                def __exit__(self, *a): pass
                def classes(self, *s): return self
            return Context()
        def separator(self): pass
        def markdown(self, *a, **kw): return self
        def element(self, tag, **kw):
            class Context:
                def __enter__(self): return self
                def __exit__(self, *a): pass
                def classes(self, *s): return self
                def set_text(self, *a): pass
            return Context()
        def notify(self, *a, **kw): pass
        @property
        def navigate(self):
            class Nav:
                def to(self, *a): pass
                def reload(self): pass
            return Nav()

    ui = FakeUI()
    for page in registry.list_pages():
        # Test render with appropriate arguments
        if "{" in page.route:
            # Dynamic route
            if "name" in page.route:
                page.render(ui, name="test-persona")
            elif "page_id" in page.route:
                page.render(ui, collection_id="c1", page_id="p1")
            elif "collection_id" in page.route:
                page.render(ui, collection_id="c1")
        else:
            page.render(ui)
