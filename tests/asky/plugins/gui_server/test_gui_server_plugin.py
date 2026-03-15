from __future__ import annotations

import threading
import time
import logging
from pathlib import Path

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


def test_nicegui_server_lifecycle_non_blocking():
    started = threading.Event()
    stopped = threading.Event()

    def _runner(_host, _port, _config_dir, _registry, _password, _queue):
        started.set()
        stopped.wait(timeout=2)

    def _shutdown():
        stopped.set()

    server = NiceGUIServer(
        config_dir=Path("."),
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
        server_mod._default_runner("127.0.0.1", 9900, Path("."), registry, "pwd", None)

        assert "general" in mount_calls
        assert "registry" in mount_calls
        assert "jobs" in mount_calls
        assert server_mod._nicegui_pages_mounted is True
        first_mount_count = len(mount_calls)

        # Second call (restart): middleware should be reset, no remounting
        fake_core.app.middleware_stack = object()  # simulate re-started state
        fake_core.app.middleware = ["gzip"]

        server_mod._default_runner("127.0.0.1", 9900, Path("."), registry, "pwd", None)

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
        page_registry=PluginPageRegistry(),
        password=None, # No password
    )
    import pytest
    with pytest.raises(RuntimeError, match="password"):
        server.start()


def test_nicegui_server_port_conflict_sets_health_error():
    def _runner(_host, _port, _config_dir, _registry, _password, _queue):
        raise OSError("Address already in use")

    server = NiceGUIServer(
        config_dir=Path("."),
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
