import sys
from types import SimpleNamespace

import pytest

from asky.cli.daemon_config import DaemonSettings
from asky.daemon import menubar
from asky.daemon import startup as startup_module
from asky.daemon.tray_protocol import TrayPluginEntry
from asky.plugins.hooks import HookRegistry


class _FakeResponse:
    def __init__(self, clicked=True, text=""):
        self.clicked = clicked
        self.text = text


class _FakeWindow:
    responses = []

    def __init__(self, *args, **kwargs):
        _ = (args, kwargs)

    def run(self):
        if _FakeWindow.responses:
            return _FakeWindow.responses.pop(0)
        return _FakeResponse(clicked=False, text="")


class _FakeMenuItem:
    def __init__(self, title, callback=None):
        self.title = title
        self.callback = callback

    def trigger(self):
        if callable(self.callback):
            self.callback(self)


class _FakeApp:
    last_instance = None

    def __init__(self, *args, **kwargs):
        _ = (args, kwargs)
        self.menu = []
        _FakeApp.last_instance = self

    def run(self):
        return None


def _fake_rumps_module():
    alerts = []

    return SimpleNamespace(
        App=_FakeApp,
        MenuItem=_FakeMenuItem,
        Window=_FakeWindow,
        alert=lambda message: alerts.append(message),
        quit_application=lambda: None,
        alerts=alerts,
    )


def _fake_startup(*, supported=True, enabled=False):
    return startup_module.StartupStatus(
        supported=supported,
        enabled=enabled,
        active=enabled,
        platform_name="darwin",
        details="",
    )


def _no_runtime():
    return None


def _fake_runtime_with_hooks(hooks: HookRegistry):
    return SimpleNamespace(
        hooks=hooks,
        get_startup_warnings=lambda: [],
    )


def test_run_menubar_app_requires_macos(monkeypatch):
    monkeypatch.setattr("asky.daemon.menubar.platform.system", lambda: "Linux")
    with pytest.raises(RuntimeError):
        menubar.run_menubar_app()


def test_run_menubar_app_uses_fake_rumps(monkeypatch, tmp_path):
    monkeypatch.setattr("asky.daemon.menubar.platform.system", lambda: "Darwin")
    fake_rumps = _fake_rumps_module()
    monkeypatch.setitem(sys.modules, "rumps", fake_rumps)
    original_acquire = menubar.acquire_menubar_singleton_lock
    lock_path = tmp_path / "menubar.lock"
    monkeypatch.setattr(
        "asky.daemon.menubar.acquire_menubar_singleton_lock",
        lambda: original_acquire(lock_path),
    )
    monkeypatch.setattr("asky.plugins.runtime.get_or_create_plugin_runtime", _no_runtime)
    monkeypatch.setattr(
        "asky.daemon.tray_controller.startup.get_status",
        lambda: _fake_startup(),
    )

    menubar.run_menubar_app()
    assert _FakeApp.last_instance is not None
    app = _FakeApp.last_instance
    assert app.action_startup.title == "Enable Run at Login"


def test_run_menubar_app_rejects_duplicate_instance(monkeypatch, tmp_path):
    monkeypatch.setattr("asky.daemon.menubar.platform.system", lambda: "Darwin")
    monkeypatch.setitem(sys.modules, "rumps", _fake_rumps_module())
    lock_path = tmp_path / "menubar.lock"
    original_acquire = menubar.acquire_menubar_singleton_lock
    held_lock = original_acquire(lock_path)
    monkeypatch.setattr(
        "asky.daemon.menubar.acquire_menubar_singleton_lock",
        lambda: original_acquire(lock_path),
    )
    try:
        with pytest.raises(menubar.DaemonUserError) as excinfo:
            menubar.run_menubar_app()
    finally:
        held_lock.release()
    assert menubar.MENUBAR_ALREADY_RUNNING_MESSAGE in excinfo.value.user_message


def test_menubar_actions_use_state_aware_labels(monkeypatch, tmp_path):
    """Plugin-contributed action entries use dynamic labels reflecting current state."""
    monkeypatch.setattr("asky.daemon.menubar.platform.system", lambda: "Darwin")
    fake_rumps = _fake_rumps_module()
    monkeypatch.setitem(sys.modules, "rumps", fake_rumps)
    current_state = {
        "voice_enabled": False,
        "startup_enabled": False,
        "startup_supported": True,
    }
    original_acquire = menubar.acquire_menubar_singleton_lock
    lock_path = tmp_path / "menubar.lock"
    monkeypatch.setattr(
        "asky.daemon.menubar.acquire_menubar_singleton_lock",
        lambda: original_acquire(lock_path),
    )
    monkeypatch.setattr(
        "asky.daemon.tray_controller.startup.get_status",
        lambda: _fake_startup(
            supported=current_state["startup_supported"],
            enabled=current_state["startup_enabled"],
        ),
    )

    hooks = HookRegistry()

    def _register(ctx):
        ctx.status_entries.append(
            TrayPluginEntry(
                get_label=lambda: "XMPP: connected"
                if ctx.is_service_running()
                else "XMPP: stopped"
            )
        )
        ctx.action_entries.append(
            TrayPluginEntry(
                get_label=lambda: "Stop XMPP"
                if ctx.is_service_running()
                else "Start XMPP",
                on_action=lambda: None,
            )
        )
        ctx.action_entries.append(
            TrayPluginEntry(
                get_label=lambda: "Disable Voice"
                if current_state["voice_enabled"]
                else "Enable Voice",
                on_action=lambda: None,
            )
        )

    hooks.register("TRAY_MENU_REGISTER", _register, plugin_name="xmpp_test")

    monkeypatch.setattr(
        "asky.plugins.runtime.get_or_create_plugin_runtime",
        lambda: _fake_runtime_with_hooks(hooks),
    )

    menubar.run_menubar_app()
    app = _FakeApp.last_instance
    assert app is not None

    action_xmpp_item = app._plugin_action_menu_items[0][1]
    action_voice_item = app._plugin_action_menu_items[1][1]
    assert action_xmpp_item.title == "Start XMPP"
    assert action_voice_item.title == "Enable Voice"
    assert app.action_startup.title == "Enable Run at Login"

    app._controller._service_thread = SimpleNamespace(is_alive=lambda: True)
    app._refresh_status()
    assert action_xmpp_item.title == "Stop XMPP"

    current_state["voice_enabled"] = True
    app._refresh_status()
    assert action_voice_item.title == "Disable Voice"

    current_state["startup_enabled"] = True
    app._refresh_status()
    assert app.action_startup.title == "Disable Run at Login"


def test_start_service_with_daemon_user_error_shows_alert(monkeypatch):
    """TrayController.start_service surfaces DaemonUserError via on_error."""
    from asky.daemon.errors import DaemonUserError
    from asky.daemon.tray_controller import TrayController

    errors = []
    state_changes = []
    controller = TrayController(
        on_state_change=lambda: state_changes.append(1),
        on_error=lambda msg: errors.append(msg),
    )

    def _raise():
        raise DaemonUserError(
            "XMPP configuration is incomplete. "
            "Run `asky --edit-daemon` to configure JID, password, and allowed users."
        )

    monkeypatch.setattr("asky.daemon.tray_controller.DaemonService", _raise)
    controller.start_service()
    assert errors
    assert "--edit-daemon" in errors[0]


def test_start_service_initializes_xmpp_logging(monkeypatch):
    """TrayController.start_service configures xmpp log handler in menubar mode."""
    from asky.daemon.errors import DaemonUserError
    from asky.daemon.tray_controller import TrayController

    setup_calls = []
    monkeypatch.setattr(
        "asky.daemon.tray_controller.setup_xmpp_logging",
        lambda: setup_calls.append(1),
    )

    def _raise():
        raise DaemonUserError("daemon unavailable")

    monkeypatch.setattr("asky.daemon.tray_controller.DaemonService", _raise)

    controller = TrayController(on_state_change=lambda: None, on_error=lambda _: None)
    controller.start_service()
    assert setup_calls == [1]


def test_menubar_shows_plugin_contributed_status_and_action_items(monkeypatch, tmp_path):
    """TrayController collects status and action entries via TRAY_MENU_REGISTER."""
    monkeypatch.setattr("asky.daemon.menubar.platform.system", lambda: "Darwin")
    fake_rumps = _fake_rumps_module()
    monkeypatch.setitem(sys.modules, "rumps", fake_rumps)
    original_acquire = menubar.acquire_menubar_singleton_lock
    lock_path = tmp_path / "menubar.lock"
    monkeypatch.setattr(
        "asky.daemon.menubar.acquire_menubar_singleton_lock",
        lambda: original_acquire(lock_path),
    )
    monkeypatch.setattr(
        "asky.daemon.tray_controller.startup.get_status",
        lambda: _fake_startup(),
    )

    hooks = HookRegistry()

    def _register(ctx):
        ctx.status_entries.append(TrayPluginEntry(get_label=lambda: "Status Item"))
        ctx.action_entries.append(
            TrayPluginEntry(get_label=lambda: "Action Item", on_action=lambda: None)
        )

    hooks.register("TRAY_MENU_REGISTER", _register, plugin_name="test_plugin")

    monkeypatch.setattr(
        "asky.plugins.runtime.get_or_create_plugin_runtime",
        lambda: _fake_runtime_with_hooks(hooks),
    )

    menubar.run_menubar_app()
    app = _FakeApp.last_instance
    assert app is not None
    assert len(app._plugin_status_menu_items) == 1
    assert app._plugin_status_menu_items[0][1].title == "Status Item"
    assert len(app._plugin_action_menu_items) == 1
    assert app._plugin_action_menu_items[0][1].title == "Action Item"


def test_tray_controller_with_no_hook_registry_has_empty_entries():
    from asky.daemon.tray_controller import TrayController

    controller = TrayController(on_state_change=lambda: None, on_error=lambda _: None)
    assert controller._plugin_status_entries == []
    assert controller._plugin_action_entries == []


def test_tray_controller_with_hook_registry_collects_entries():
    from asky.daemon.tray_controller import TrayController

    hooks = HookRegistry()
    hooks.register(
        "TRAY_MENU_REGISTER",
        lambda ctx: ctx.status_entries.append(
            TrayPluginEntry(get_label=lambda: "Status")
        ),
        plugin_name="test",
    )

    controller = TrayController(
        on_state_change=lambda: None,
        on_error=lambda _: None,
        hook_registry=hooks,
    )
    assert len(controller._plugin_status_entries) == 1
    assert controller._plugin_status_entries[0].get_label() == "Status"


def test_startup_warnings_displayed_and_cleared(monkeypatch, tmp_path):
    """Startup warnings are shown via alert on first refresh then cleared."""
    monkeypatch.setattr("asky.daemon.menubar.platform.system", lambda: "Darwin")
    fake_rumps = _fake_rumps_module()
    monkeypatch.setitem(sys.modules, "rumps", fake_rumps)
    original_acquire = menubar.acquire_menubar_singleton_lock
    lock_path = tmp_path / "menubar.lock"
    monkeypatch.setattr(
        "asky.daemon.menubar.acquire_menubar_singleton_lock",
        lambda: original_acquire(lock_path),
    )
    monkeypatch.setattr(
        "asky.daemon.tray_controller.startup.get_status", lambda: _fake_startup()
    )

    fake_runtime = SimpleNamespace(
        hooks=None,
        get_startup_warnings=lambda: ["Plugin 'foo' requires 'bar' (disabled)."],
    )
    monkeypatch.setattr(
        "asky.plugins.runtime.get_or_create_plugin_runtime",
        lambda: fake_runtime,
    )

    menubar.run_menubar_app()
    assert any("bar" in alert for alert in fake_rumps.alerts)
    app = _FakeApp.last_instance
    assert app._controller._startup_warnings == []
