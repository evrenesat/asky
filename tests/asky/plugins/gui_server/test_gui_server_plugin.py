from __future__ import annotations

import asyncio
import inspect
import threading
import time
import logging
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from asky.plugins.base import PluginContext
from asky.plugins.gui_server.pages.general_settings import (
    load_general_settings,
    save_general_settings,
    validate_general_updates,
)
from asky.plugins.gui_server.pages.plugin_registry import PluginPageRegistry
from asky.plugins.gui_server.plugin import GUIServerPlugin
from asky.plugins.gui_server.server import NiceGUIServer
from asky.plugins.hook_types import DaemonServerRegisterContext
from asky.plugins.hooks import HookRegistry


class _FakeUI:
    def __init__(self):
        self.routes = []

    def page(self, route):
        def decorator(func):
            self.routes.append(route)
            func()
            return func

        return decorator

    def label(self, *_args, **_kwargs):
        return None

    def link(self, *_args, **_kwargs):
        return None


def _plugin_context(tmp_path: Path, hooks: HookRegistry) -> PluginContext:
    return PluginContext(
        plugin_name="gui_server",
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        config={"host": "127.0.0.1", "port": 9900},
        hook_registry=hooks,
        logger=logging.getLogger("test.gui_server"),
    )


def test_gui_plugin_registers_daemon_server_spec(tmp_path: Path):
    hooks = HookRegistry()
    plugin = GUIServerPlugin()
    plugin.activate(_plugin_context(tmp_path, hooks))

    payload = DaemonServerRegisterContext(service=object())
    hooks.invoke("DAEMON_SERVER_REGISTER", payload)

    assert len(payload.servers) == 1
    assert payload.servers[0].name == "nicegui_server"


def test_general_settings_validation_and_safe_write(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "general.toml").write_text(
        """
[general]
default_model = "gf"
max_turns = 5

[api.default]
url = "https://example.com"
""",
        encoding="utf-8",
    )

    errors = validate_general_updates({"max_turns": 0})
    assert errors

    save_general_settings(
        config_dir,
        {
            "default_model": "gpt-4o",
            "max_turns": 9,
            "summarization_model": "gpt-4o-mini",
            "log_level": "INFO",
        },
    )

    loaded = load_general_settings(config_dir)
    assert loaded["default_model"] == "gpt-4o"
    assert loaded["max_turns"] == 9
    rendered = (config_dir / "general.toml").read_text(encoding="utf-8")
    assert "[api.default]" in rendered


def test_plugin_page_registry_isolation_for_bad_page():
    from asky.plugins.hook_types import GUIPageSpec
    registry = PluginPageRegistry()
    ui = _FakeUI()

    registry.register_page(GUIPageSpec(route="/good", title="Good", render=lambda ui_obj: ui_obj.label("ok")))

    def _bad(_ui):
        raise RuntimeError("boom")

    registry.register_page(GUIPageSpec(route="/bad", title="Bad", render=_bad))

    registry.mount_pages(ui)
    assert "/good" in ui.routes


def test_plugin_page_registry_mounts_signatures_without_phantom_query_params():
    from asky.plugins.hook_types import GUIPageSpec
    from nicegui import app, ui

    registry = PluginPageRegistry()
    route_suffix = uuid4().hex
    static_route = f"/sessions-signature-{route_suffix}"
    dynamic_route = f"/personas-signature-{route_suffix}" + "/{name}"
    original_routes = list(app.routes)

    registry.register_page(
        GUIPageSpec(route=static_route, title="Sessions", render=lambda ui_obj: None)
    )
    registry.register_page(
        GUIPageSpec(
            route=dynamic_route,
            title="Persona: {name}",
            render=lambda ui_obj, name: None,
        )
    )

    try:
        registry.mount_pages(ui)
        mounted_routes = {
            route.path: route for route in app.routes if getattr(route, "path", None) in {static_route, dynamic_route}
        }
    finally:
        app.routes[:] = original_routes

    static_signature = inspect.signature(mounted_routes[static_route].endpoint)
    assert list(static_signature.parameters) == ["request"]

    dynamic_signature = inspect.signature(mounted_routes[dynamic_route].endpoint)
    assert list(dynamic_signature.parameters) == ["request", "name"]
    assert dynamic_signature.parameters["name"].annotation == "str"


def test_nicegui_server_lifecycle_non_blocking():
    started = threading.Event()
    stopped = threading.Event()

    def _runner(_host, _port, _config_dir, _data_dir, _registry, _password, _queue):
        started.set()
        stopped.wait(timeout=2)

    def _shutdown():
        stopped.set()

    server = NiceGUIServer(
        config_dir=Path("."),
        data_dir=Path("."),
        page_registry=PluginPageRegistry(),
        password="test-password",
        job_queue=None,
        runner=_runner,
        shutdown=_shutdown,
    )

    server.start()
    assert started.wait(timeout=1)
    assert server.health_check()["running"] is True

    server.stop()
    assert server.health_check()["running"] is False


def test_nicegui_server_restart_resets_middleware_and_skips_remount():
    """_default_runner logic: pages mounted once; on restart middleware state is reset."""
    import asky.plugins.gui_server.server as server_mod

    original_flag = server_mod._nicegui_pages_mounted
    server_mod._nicegui_pages_mounted = False

    mount_calls = []

    class _FakeApp:
        middleware_stack = object()  # non-None to simulate "started" state
        middleware = ["existing"]
        storage = type("storage", (), {"user": {}})
        def middleware(self, *a, **kw):
            return lambda fn: fn

    class _FakeCore:
        app = _FakeApp()

    class _FakeUI:
        def page(self, route):
            def dec(fn):
                return fn
            return dec
        def row(self):
            return type("row", (), {"__enter__": lambda s: s, "__exit__": lambda s, *a: None})()
        def card(self):
            return type("card", (), {"__enter__": lambda s: s, "__exit__": lambda s, *a: None})()
        def column(self):
            return type("column", (), {"__enter__": lambda s: s, "__exit__": lambda s, *a: None})()
        def label(self, *a, **kw): pass
        def button(self, *a, **kw): pass
        def navigate(self): pass

    fake_ui = _FakeUI()
    fake_core = _FakeCore()

    import sys
    sys.modules["nicegui"] = type(sys)("nicegui")
    sys.modules["nicegui"].ui = fake_ui
    sys.modules["nicegui"].app = _FakeApp()
    sys.modules["nicegui.core"] = fake_core

    original_mount_general = server_mod.mount_general_settings_page
    original_mount_registry = server_mod.mount_plugin_registry_page
    original_mount_jobs = server_mod.mount_jobs_page

    def _fake_mount_general(ui, *, config_dir):
        mount_calls.append("general")

    def _fake_mount_registry(ui, registry):
        mount_calls.append("registry")

    def _fake_mount_jobs(ui, queue):
        mount_calls.append("jobs")

    server_mod.mount_general_settings_page = _fake_mount_general
    server_mod.mount_plugin_registry_page = _fake_mount_registry
    server_mod.mount_jobs_page = _fake_mount_jobs

    try:
        registry = PluginPageRegistry()

        # First call: pages should be mounted, middleware untouched
        server_mod._default_runner.__globals__["_nicegui_pages_mounted"] = False

        # Patch ui.run to be a no-op
        fake_ui.run = lambda **kw: None

        server_mod._nicegui_pages_mounted = False
        server_mod._default_runner("127.0.0.1", 9900, Path("."), Path("."), registry, "pwd", None)

        assert "general" in mount_calls
        assert "registry" in mount_calls
        assert "jobs" in mount_calls
        assert server_mod._nicegui_pages_mounted is True
        first_mount_count = len(mount_calls)

        # Second call (restart): middleware should be reset, no remounting
        fake_core.app.middleware_stack = object()  # simulate re-started state
        fake_core.app.middleware = ["gzip"]

        server_mod._default_runner("127.0.0.1", 9900, Path("."), Path("."), registry, "pwd", None)

        assert len(mount_calls) == first_mount_count, "pages must not be remounted on restart"
        assert fake_core.app.middleware_stack is None, "middleware_stack must be reset on restart"
        assert fake_core.app.middleware == [], "middleware list must be cleared on restart"
    finally:
        server_mod._nicegui_pages_mounted = original_flag
        server_mod.mount_general_settings_page = original_mount_general
        server_mod.mount_plugin_registry_page = original_mount_registry
        server_mod.mount_jobs_page = original_mount_jobs
        for mod in ("nicegui", "nicegui.core"):
            sys.modules.pop(mod, None)


def test_default_runner_auth_middleware_redirects_with_http_response():
    """Protected requests redirect with RedirectResponse instead of ui.navigate.to()."""
    import asky.plugins.gui_server.server as server_mod

    original_flag = server_mod._nicegui_pages_mounted
    server_mod._nicegui_pages_mounted = False
    middleware_holder = {}

    class _FakeCoreApp:
        def __init__(self):
            self.middleware_stack = None
            self.middleware = []

    class _FakeNiceGUIApp:
        def __init__(self):
            self.storage = SimpleNamespace(user={})

        def middleware(self, *_args, **_kwargs):
            def decorator(fn):
                middleware_holder["middleware"] = fn
                return fn

            return decorator

    class _FakeElement:
        def classes(self, *_args, **_kwargs):
            return self

        def on(self, *_args, **_kwargs):
            return self

        def props(self, *_args, **_kwargs):
            return self

    class _FakeContainer:
        def classes(self, *_args, **_kwargs):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    class _FakeUI:
        navigate = SimpleNamespace(to=lambda *_args, **_kwargs: None)

        def page(self, _route):
            def decorator(fn):
                return fn

            return decorator

        def card(self):
            return _FakeContainer()

        def row(self):
            return _FakeContainer()

        def label(self, *_args, **_kwargs):
            return _FakeElement()

        def input(self, *_args, **_kwargs):
            element = _FakeElement()
            element.value = ""
            return element

        def button(self, *_args, **_kwargs):
            return _FakeElement()

        def notify(self, *_args, **_kwargs):
            return None

        def run(self, **_kwargs):
            return None

    import sys

    fake_app = _FakeNiceGUIApp()
    fake_core = type("core", (), {"app": _FakeCoreApp()})()
    fake_ui = _FakeUI()

    sys.modules["nicegui"] = type(sys)("nicegui")
    sys.modules["nicegui"].app = fake_app
    sys.modules["nicegui"].ui = fake_ui
    sys.modules["nicegui.core"] = fake_core

    original_mount_general = server_mod.mount_general_settings_page
    original_mount_registry = server_mod.mount_plugin_registry_page
    original_mount_jobs = server_mod.mount_jobs_page

    server_mod.mount_general_settings_page = lambda *_args, **_kwargs: None
    server_mod.mount_plugin_registry_page = lambda *_args, **_kwargs: None
    server_mod.mount_jobs_page = lambda *_args, **_kwargs: None

    try:
        registry = PluginPageRegistry()
        server_mod._default_runner(
            "127.0.0.1",
            9900,
            Path("."),
            Path("."),
            registry,
            "pwd",
            None,
        )

        async def _call_next(_request):
            raise AssertionError("auth middleware should short-circuit unauthenticated requests")

        request = SimpleNamespace(url=SimpleNamespace(path="/plugins"))
        response = asyncio.run(middleware_holder["middleware"](request, _call_next))

        assert response.status_code == 307
        assert response.headers["location"] == "/login"
        assert fake_app.storage.user["referrer"] == "/plugins"
    finally:
        server_mod._nicegui_pages_mounted = original_flag
        server_mod.mount_general_settings_page = original_mount_general
        server_mod.mount_plugin_registry_page = original_mount_registry
        server_mod.mount_jobs_page = original_mount_jobs
        for mod in ("nicegui", "nicegui.core"):
            sys.modules.pop(mod, None)


class _RenderElement:
    def classes(self, *_args, **_kwargs):
        return self

    def props(self, *_args, **_kwargs):
        return self

    def on(self, *_args, **_kwargs):
        return self

    def hide(self):
        return self

    def show(self):
        return self

    def clear(self):
        return self


class _RenderContext(_RenderElement):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class _RenderUI:
    def label(self, *_args, **_kwargs):
        return _RenderElement()

    def markdown(self, *_args, **_kwargs):
        return _RenderElement()

    def button(self, *_args, **_kwargs):
        return _RenderElement()

    def input(self, *_args, **_kwargs):
        element = _RenderElement()
        element.value = ""
        return element

    def select(self, *_args, **_kwargs):
        return _RenderElement()

    def notify(self, *_args, **_kwargs):
        return None

    def link(self, *_args, **_kwargs):
        return _RenderElement()

    def separator(self):
        return _RenderElement()

    def row(self):
        return _RenderContext()

    def column(self):
        return _RenderContext()

    def card(self):
        return _RenderContext()

    def tabs(self):
        return _RenderContext()

    def tab(self, *_args, **_kwargs):
        return object()

    def tab_panels(self, *_args, **_kwargs):
        return _RenderContext()

    def tab_panel(self, *_args, **_kwargs):
        return _RenderContext()

    def dialog(self):
        return _RenderContext()

    def element(self, *_args, **_kwargs):
        return _RenderContext()

    @property
    def navigate(self):
        return SimpleNamespace(to=lambda *_args, **_kwargs: None, reload=lambda: None)


def test_session_page_render_with_rows_uses_supported_ui_api(tmp_path: Path):
    import asky.plugins.gui_server.pages.sessions as sessions_pages

    captured = {}
    original_list_sessions = sessions_pages.list_sessions_with_bindings
    original_list_persona_names = sessions_pages.list_persona_names

    sessions_pages.list_sessions_with_bindings = lambda _data_dir, limit=100: [
        {"id": 1, "name": "UI Route Smoke", "model": "gpt-4o", "persona_binding": None}
    ]
    sessions_pages.list_persona_names = lambda _data_dir: []

    try:
        sessions_pages.register_session_pages(
            lambda spec: captured.setdefault(spec.route, spec),
            tmp_path,
        )
        captured["/sessions"].render(_RenderUI())
    finally:
        sessions_pages.list_sessions_with_bindings = original_list_sessions
        sessions_pages.list_persona_names = original_list_persona_names


def test_persona_detail_page_render_with_tables_uses_supported_ui_api(tmp_path: Path):
    import asky.plugins.gui_server.pages.personas as personas_pages

    captured = {}
    original_get_persona_detail = personas_pages.get_persona_detail
    personas_pages.get_persona_detail = lambda _data_dir, _name: {
        "metadata": {
            "persona": {"description": "desc"},
            "behavior_prompt": "prompt",
        },
        "books": [
            {
                "title": "Book",
                "authors": ["Author"],
                "publication_year": 2024,
                "viewpoint_count": 2,
            }
        ],
        "approved_sources": [
            {"label": "Source", "kind": "manual", "review_status": "approved"}
        ],
        "pending_sources": [],
        "web_collections": [],
    }

    try:
        personas_pages.register_persona_pages(
            lambda spec: captured.setdefault(spec.route, spec),
            tmp_path,
            queue=SimpleNamespace(),
        )
        captured["/personas/{name}"].render(_RenderUI(), name="test-persona")
    finally:
        personas_pages.get_persona_detail = original_get_persona_detail


def test_gui_plugin_registers_tray_menu_entries(tmp_path: Path):
    """GUIServerPlugin contributes Start/Stop Web GUI and Open Web Console tray entries."""
    hooks = HookRegistry()
    plugin = GUIServerPlugin()
    plugin.activate(_plugin_context(tmp_path, hooks))

    from asky.daemon.tray_protocol import TrayPluginEntry
    from asky.plugins.hook_types import TRAY_MENU_REGISTER, TrayMenuRegisterContext

    action_entries = []
    ctx = TrayMenuRegisterContext(
        status_entries=[],
        action_entries=action_entries,
        start_service=lambda: None,
        stop_service=lambda: None,
        is_service_running=lambda: False,
        on_error=lambda _: None,
    )
    hooks.invoke(TRAY_MENU_REGISTER, ctx)

    assert len(action_entries) == 2
    labels = [e.get_label() for e in action_entries]
    assert "Start Web GUI" in labels
    assert "Open Web Console" in labels


def test_gui_plugin_tray_toggle_no_longer_requires_xmpp(tmp_path: Path):
    """Clicking Start Web GUI when XMPP is stopped no longer shows an error if password exists."""
    hooks = HookRegistry()
    plugin = GUIServerPlugin()
    
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    
    ctx = PluginContext(
        plugin_name="gui_server",
        config_dir=config_dir,
        data_dir=tmp_path / "data",
        config={"host": "127.0.0.1", "port": 9900, "password": "pwd"},
        hook_registry=hooks,
        logger=logging.getLogger("test.gui_server"),
    )
    plugin.activate(ctx)

    from asky.plugins.hook_types import TRAY_MENU_REGISTER, TrayMenuRegisterContext

    errors = []
    action_entries = []
    tray_ctx = TrayMenuRegisterContext(
        status_entries=[],
        action_entries=action_entries,
        start_service=lambda: None,
        stop_service=lambda: None,
        is_service_running=lambda: False,
        on_error=lambda msg: errors.append(msg),
    )
    hooks.invoke(TRAY_MENU_REGISTER, tray_ctx)

    toggle_entry = action_entries[0]
    # This should now try to start the server instead of showing an XMPP error
    toggle_entry.on_action()
    assert not errors


def test_nicegui_server_fails_without_password():
    server = NiceGUIServer(
        config_dir=Path("."),
        data_dir=Path("."),
        page_registry=PluginPageRegistry(),
        password=None, # No password
    )
    import pytest
    with pytest.raises(RuntimeError, match="GUI password is not configured"):
        server.start()

def test_nicegui_server_port_conflict_sets_health_error():
    def _runner(_host, _port, _config_dir, _data_dir, _registry, _password, _queue):
        raise OSError("Address already in use")

    server = NiceGUIServer(
        config_dir=Path("."),
        data_dir=Path("."),
        page_registry=PluginPageRegistry(),
        password="pwd",
        job_queue=None,
        runner=_runner,
        shutdown=lambda: None,
    )
    server.start()
    time.sleep(0.1)

    health = server.health_check()
    assert health["running"] is False
    assert "Address already in use" in str(health["error"])
