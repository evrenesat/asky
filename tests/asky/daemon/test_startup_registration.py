from pathlib import Path

from asky.daemon import startup
from asky.daemon import startup_linux, startup_macos, startup_windows


def test_build_command_includes_macos_child_flag(monkeypatch):
    monkeypatch.setattr("asky.daemon.startup.platform.system", lambda: "Darwin")
    command = startup.build_command(macos_menubar_child=True)
    assert command[-1] == "--xmpp-menubar-child"


def test_build_command_omits_macos_child_flag_on_linux(monkeypatch):
    monkeypatch.setattr("asky.daemon.startup.platform.system", lambda: "Linux")
    command = startup.build_command(macos_menubar_child=True)
    assert "--xmpp-menubar-child" not in command


def test_get_status_unsupported_platform(monkeypatch):
    monkeypatch.setattr("asky.daemon.startup.platform.system", lambda: "FreeBSD")
    state = startup.get_status()
    assert state.supported is False
    assert state.enabled is False


def test_macos_plist_structure():
    payload = startup_macos.build_plist(["python", "-m", "asky"])
    assert payload["Label"] == "com.evren.asky.menubar"
    assert payload["RunAtLoad"] is True
    assert payload["ProgramArguments"] == ["python", "-m", "asky"]


def test_linux_unit_text_contains_execstart():
    text = startup_linux._unit_text(["python", "-m", "asky", "--xmpp-daemon"])
    assert "ExecStart=" in text
    assert "--xmpp-daemon" in text


def test_windows_script_text_contains_start():
    text = startup_windows._script_text(["python", "-m", "asky", "--xmpp-daemon"])
    assert text.startswith("@echo off")
    assert "start \"\"" in text


def test_windows_status_uses_startup_script_path(monkeypatch, tmp_path):
    fake_path = tmp_path / "asky.cmd"
    monkeypatch.setattr("asky.daemon.startup_windows.startup_script_path", lambda: fake_path)
    status = startup_windows.status()
    assert status.enabled is False
    fake_path.write_text("echo on")
    status = startup_windows.status()
    assert status.enabled is True


def test_linux_write_unit_creates_file(monkeypatch, tmp_path):
    fake_path = tmp_path / "asky.service"
    monkeypatch.setattr("asky.daemon.startup_linux.SYSTEMD_USER_SERVICE_PATH", fake_path)
    path = startup_linux.write_unit(["python", "-m", "asky"])
    assert path == fake_path
    assert fake_path.exists()


def test_macos_write_plist_creates_file(monkeypatch, tmp_path):
    fake_path = tmp_path / "com.evren.asky.menubar.plist"
    monkeypatch.setattr("asky.daemon.startup_macos.LAUNCH_AGENT_PATH", fake_path)
    path = startup_macos.write_plist(["python", "-m", "asky"])
    assert path == fake_path
    assert fake_path.exists()
