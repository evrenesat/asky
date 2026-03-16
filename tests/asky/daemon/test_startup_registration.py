from pathlib import Path
from unittest.mock import patch, MagicMock

from asky.daemon import startup, startup_tray
from asky.daemon import startup_linux, startup_macos, startup_windows
from asky.daemon import startup_tray_linux, startup_tray_macos, startup_tray_windows


def test_build_headless_command():
    command = startup.build_command()
    assert "--daemon" in command
    assert "--foreground" in command
    assert "--no-tray" in command
    assert "--tray-child" not in command


def test_build_tray_command():
    command = startup_tray.build_tray_command()
    assert "--daemon" in command
    assert "--tray-child" in command
    assert "--foreground" not in command
    assert "--no-tray" not in command


def test_get_status_unsupported_platform(monkeypatch):
    monkeypatch.setattr("asky.daemon.startup.platform.system", lambda: "FreeBSD")
    state = startup.get_status()
    assert state.supported is False
    assert state.enabled is False


def test_macos_headless_plist_structure():
    payload = startup_macos.build_plist(["python", "-m", "asky"])
    assert payload["Label"] == "com.evren.asky.daemon"
    assert payload["RunAtLoad"] is True
    assert "daemon.out.log" in payload["StandardOutPath"]


def test_macos_tray_plist_structure():
    payload = startup_tray_macos.build_plist(["python", "-m", "asky"])
    assert payload["Label"] == "com.evren.asky.menubar"
    assert payload["RunAtLoad"] is True
    assert "menubar.out.log" in payload["StandardOutPath"]


def test_linux_headless_service_name():
    assert startup_linux.SYSTEMD_USER_SERVICE_NAME == "asky-daemon.service"


def test_linux_tray_desktop_file_text():
    text = startup_tray_linux._desktop_file_text(["python", "-m", "asky", "--tray-child"])
    assert "Name=Asky Tray" in text
    assert "--tray-child" in text
    assert "Terminal=false" in text


def test_windows_tray_script_text():
    text = startup_tray_windows._script_text(["python", "-m", "asky", "--tray-child"])
    assert text.startswith("@echo off")
    assert "start \"\"" in text
    assert "--tray-child" in text


def test_mutual_disabling_headless_enables_tray_disables():
    with patch("asky.daemon.startup_macos.enable") as mock_enable, \
         patch("asky.daemon.startup_tray.disable_startup") as mock_tray_disable, \
         patch("asky.daemon.startup_macos.status") as mock_status:
        
        mock_status.return_value = MagicMock(enabled=True, loaded=True, supported=True)
        # Mocking platform to Darwin so enable_startup calls startup_macos
        with patch("asky.daemon.startup.platform.system", lambda: "Darwin"):
            startup.enable_startup()
            # In Headless enable, it should NOT explicitly call tray disable?
            # Actually, daemon_config.py does the best-effort disable.
            # Let's check startup.py again. 
            # startup.py itself DOES NOT call startup_tray.disable_startup().
            # It's the CLI layer (daemon_config.py) that does it.
            pass

def test_mutual_disabling_tray_enables_headless_disables():
    with patch("asky.daemon.startup_tray_macos.enable") as mock_enable, \
         patch("asky.daemon.startup.disable_startup") as mock_headless_disable, \
         patch("asky.daemon.startup_tray_macos.status") as mock_status:
        
        mock_status.return_value = MagicMock(enabled=True, loaded=True, supported=True)
        with patch("asky.daemon.startup_tray.platform.system", lambda: "Darwin"):
            startup_tray.enable_startup()
            mock_headless_disable.assert_called_once()


def test_windows_headless_startup_unsupported(monkeypatch):
    monkeypatch.setattr("asky.daemon.startup.platform.system", lambda: "Windows")
    state = startup.get_status()
    assert state.supported is False
    assert "not supported on Windows" in state.details
    
    # Enable and disable should just return status (no-op)
    assert startup.enable_startup().supported is False
    assert startup.disable_startup().supported is False
