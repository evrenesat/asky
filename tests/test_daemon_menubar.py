import sys
from types import SimpleNamespace

import pytest

from asky.cli.daemon_config import DaemonSettings
from asky.daemon import menubar


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


def _build_settings(
    *,
    enabled=False,
    jid="",
    password="",
    allowed_jids=None,
    voice_enabled=False,
):
    return DaemonSettings(
        enabled=enabled,
        jid=jid,
        password=password,
        password_env="ASKY_XMPP_PASSWORD",
        allowed_jids=list(allowed_jids or []),
        voice_enabled=voice_enabled,
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
    monkeypatch.setattr(
        "asky.daemon.menubar.get_daemon_settings",
        lambda: _build_settings(),
    )
    monkeypatch.setattr(
        "asky.daemon.menubar.startup.get_status",
        lambda: menubar.startup.StartupStatus(
            supported=True,
            enabled=False,
            active=False,
            platform_name="darwin",
            details="",
        ),
    )

    menubar.run_menubar_app()
    assert _FakeApp.last_instance is not None
    app = _FakeApp.last_instance
    assert app.action_daemon.title == "Start Daemon"
    assert app.action_voice.title == "Enable Voice"
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
    monkeypatch.setattr(
        "asky.daemon.menubar.get_daemon_settings",
        lambda: _build_settings(),
    )
    monkeypatch.setattr(
        "asky.daemon.menubar.startup.get_status",
        lambda: menubar.startup.StartupStatus(
            supported=True,
            enabled=False,
            active=False,
            platform_name="darwin",
            details="",
        ),
    )
    try:
        with pytest.raises(menubar.DaemonUserError) as excinfo:
            menubar.run_menubar_app()
    finally:
        held_lock.release()
    assert menubar.MENUBAR_ALREADY_RUNNING_MESSAGE in excinfo.value.user_message


def test_menubar_actions_use_state_aware_labels(monkeypatch, tmp_path):
    monkeypatch.setattr("asky.daemon.menubar.platform.system", lambda: "Darwin")
    fake_rumps = _fake_rumps_module()
    monkeypatch.setitem(sys.modules, "rumps", fake_rumps)
    current_state = {
        "enabled": False,
        "jid": "",
        "password": "",
        "allowed_jids": [],
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

    def _settings():
        return _build_settings(
            enabled=current_state["enabled"],
            jid=current_state["jid"],
            password=current_state["password"],
            allowed_jids=current_state["allowed_jids"],
            voice_enabled=current_state["voice_enabled"],
        )

    def _update(**kwargs):
        if "enabled" in kwargs:
            current_state["enabled"] = kwargs["enabled"]
        if "jid" in kwargs:
            current_state["jid"] = kwargs["jid"]
        if "password" in kwargs:
            current_state["password"] = kwargs["password"]
        if "allowed_jids" in kwargs:
            current_state["allowed_jids"] = kwargs["allowed_jids"]
        if "voice_enabled" in kwargs:
            current_state["voice_enabled"] = kwargs["voice_enabled"]
        return _settings()

    monkeypatch.setattr("asky.daemon.menubar.get_daemon_settings", _settings)
    monkeypatch.setattr("asky.daemon.menubar.update_daemon_settings", _update)
    monkeypatch.setattr(
        "asky.daemon.menubar.startup.get_status",
        lambda: menubar.startup.StartupStatus(
            supported=current_state["startup_supported"],
            enabled=current_state["startup_enabled"],
            active=current_state["startup_enabled"],
            platform_name="darwin",
            details="",
        ),
    )

    menubar.run_menubar_app()
    app = _FakeApp.last_instance
    assert app is not None
    assert app.action_daemon.title == "Start Daemon"
    assert app.action_voice.title == "Enable Voice"
    assert app.action_startup.title == "Enable Run at Login"

    app._service_thread = SimpleNamespace(is_alive=lambda: True)
    app._refresh_status()
    assert app.action_daemon.title == "Stop Daemon"

    current_state["voice_enabled"] = True
    app._refresh_status()
    assert app.action_voice.title == "Disable Voice"

    current_state["startup_enabled"] = True
    app._refresh_status()
    assert app.action_startup.title == "Disable Run at Login"


def test_start_daemon_with_missing_config_uses_cli_error_path(monkeypatch, tmp_path):
    monkeypatch.setattr("asky.daemon.menubar.platform.system", lambda: "Darwin")
    fake_rumps = _fake_rumps_module()
    monkeypatch.setitem(sys.modules, "rumps", fake_rumps)
    original_acquire = menubar.acquire_menubar_singleton_lock
    lock_path = tmp_path / "menubar.lock"
    monkeypatch.setattr(
        "asky.daemon.menubar.acquire_menubar_singleton_lock",
        lambda: original_acquire(lock_path),
    )
    current_state = {
        "enabled": False,
        "jid": "",
        "password": "",
        "allowed_jids": [],
        "voice_enabled": False,
    }

    def _settings():
        return _build_settings(
            enabled=current_state["enabled"],
            jid=current_state["jid"],
            password=current_state["password"],
            allowed_jids=current_state["allowed_jids"],
            voice_enabled=current_state["voice_enabled"],
        )

    def _update(**kwargs):
        if "enabled" in kwargs:
            current_state["enabled"] = kwargs["enabled"]
        if "voice_enabled" in kwargs:
            current_state["voice_enabled"] = kwargs["voice_enabled"]
        return _settings()

    monkeypatch.setattr("asky.daemon.menubar.get_daemon_settings", _settings)
    monkeypatch.setattr("asky.daemon.menubar.update_daemon_settings", _update)
    monkeypatch.setattr(
        "asky.daemon.menubar.startup.get_status",
        lambda: menubar.startup.StartupStatus(
            supported=True,
            enabled=False,
            active=False,
            platform_name="darwin",
            details="",
        ),
    )
    menubar.run_menubar_app()
    app = _FakeApp.last_instance
    assert app is not None
    app._on_daemon_action(None)
    assert fake_rumps.alerts
    assert "--edit-daemon" in fake_rumps.alerts[-1]
