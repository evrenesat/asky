import json
import os
import platform
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from asky.daemon import tray, runtime_owner
from asky.daemon.runtime_owner import RuntimeMode, RuntimeOwnerLock, RuntimeOwnerMetadata
from asky.daemon.tray import is_tray_supported, run_tray_app


@pytest.fixture
def mock_lock_path(tmp_path):
    return tmp_path / "daemon.lock"


def test_runtime_owner_lock_acquire_release(mock_lock_path):
    lock = RuntimeOwnerLock(lock_path=mock_lock_path)
    assert lock.acquire(RuntimeMode.HEADLESS) is True
    assert mock_lock_path.exists()
    
    metadata = lock.get_owner()
    assert metadata.pid == os.getpid()
    assert metadata.mode == "headless"
    
    lock.release()
    assert not mock_lock_path.exists()


def test_runtime_owner_lock_collision(mock_lock_path):
    # Simulate another process holding the lock
    metadata = RuntimeOwnerMetadata(pid=999999, mode="headless", start_time=123.0)
    mock_lock_path.parent.mkdir(parents=True, exist_ok=True)
    mock_lock_path.write_text(json.dumps(metadata.__dict__))
    
    lock = RuntimeOwnerLock(lock_path=mock_lock_path)
    with patch("os.kill", return_value=None):  # Process 999999 is "alive"
        assert lock.acquire(RuntimeMode.HEADLESS) is False


def test_tray_takeover_from_headless(mock_lock_path):
    # Simulate headless process holding the lock
    metadata = RuntimeOwnerMetadata(pid=12345, mode="headless", start_time=123.0)
    mock_lock_path.parent.mkdir(parents=True, exist_ok=True)
    mock_lock_path.write_text(json.dumps(metadata.__dict__))
    
    lock = RuntimeOwnerLock(lock_path=mock_lock_path)
    
    with patch("os.kill") as mock_kill, \
         patch("asky.daemon.startup.disable_startup") as mock_startup_disable:
        # Mocking _is_process_alive to return True then False
        with patch.object(RuntimeOwnerLock, "_is_process_alive", side_effect=[True, True, False]):
            assert lock.acquire(RuntimeMode.TRAY) is True
            # Should have called kill with SIGTERM (15)
            mock_kill.assert_any_call(12345, 15)
            # Should have disabled headless startup
            mock_startup_disable.assert_called_once()


def test_tray_collision(mock_lock_path):
    # Simulate another tray process holding the lock
    metadata = RuntimeOwnerMetadata(pid=12345, mode="tray", start_time=123.0)
    mock_lock_path.parent.mkdir(parents=True, exist_ok=True)
    mock_lock_path.write_text(json.dumps(metadata.__dict__))
    
    lock = RuntimeOwnerLock(lock_path=mock_lock_path)
    
    with patch.object(RuntimeOwnerLock, "_is_process_alive", return_value=True):
        # Tray should NOT take over from another tray
        assert lock.acquire(RuntimeMode.TRAY) is False


def test_is_tray_supported_linux_no_display(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setenv("DISPLAY", "")
    monkeypatch.setenv("WAYLAND_DISPLAY", "")
    assert is_tray_supported() is False


def test_is_tray_supported_linux_with_display(monkeypatch):
    monkeypatch.setattr("asky.daemon.tray.platform.system", lambda: "linux")
    monkeypatch.setenv("DISPLAY", ":0")
    
    mock_pystray = MagicMock()
    mock_pystray.Icon.HAS_MENU = True
    monkeypatch.setitem(sys.modules, "pystray", mock_pystray)
    
    assert is_tray_supported() is True


@patch("asky.daemon.tray.is_tray_supported", return_value=True)
@patch("asky.daemon.tray.get_tray_app_class")
@patch("asky.daemon.runtime_owner.RuntimeOwnerLock.acquire", return_value=True)
def test_run_tray_app(mock_acquire, mock_get_class, mock_supported):
    mock_app_instance = MagicMock()
    mock_get_class.return_value = lambda: mock_app_instance
    
    run_tray_app()
    
    assert mock_app_instance.run.called


def test_is_conflict(mock_lock_path):
    lock = RuntimeOwnerLock(lock_path=mock_lock_path)
    
    # No owner -> no conflict
    assert lock.is_conflict(RuntimeMode.TRAY) is False
    assert lock.is_conflict(RuntimeMode.HEADLESS) is False
    
    # Headless owner
    metadata = RuntimeOwnerMetadata(pid=12345, mode="headless", start_time=123.0)
    mock_lock_path.parent.mkdir(parents=True, exist_ok=True)
    mock_lock_path.write_text(json.dumps(metadata.__dict__))
    
    with patch.object(RuntimeOwnerLock, "_is_process_alive", return_value=True):
        # Tray can takeover headless -> no conflict
        assert lock.is_conflict(RuntimeMode.TRAY) is False
        # Headless cannot takeover headless -> conflict
        assert lock.is_conflict(RuntimeMode.HEADLESS) is True
        
    # Tray owner
    metadata = RuntimeOwnerMetadata(pid=12345, mode="tray", start_time=123.0)
    mock_lock_path.write_text(json.dumps(metadata.__dict__))
    
    with patch.object(RuntimeOwnerLock, "_is_process_alive", return_value=True):
        # Tray cannot takeover tray -> conflict
        assert lock.is_conflict(RuntimeMode.TRAY) is True
        # Headless cannot takeover tray -> conflict
        assert lock.is_conflict(RuntimeMode.HEADLESS) is True
