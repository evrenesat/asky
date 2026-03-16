"""System tray selection and execution entry point."""

from __future__ import annotations

import logging
import platform
import os
from typing import Optional, Type

from asky.daemon.tray_protocol import TrayApp

logger = logging.getLogger(__name__)


def is_tray_supported() -> bool:
    """Return whether any tray backend is supported on the current platform."""
    sys_name = platform.system().lower()
    
    if sys_name == "darwin":
        from asky.daemon.menubar import has_rumps
        return has_rumps()
        
    if sys_name in ("linux", "windows"):
        if sys_name == "linux":
            if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
                logger.debug("linux tray rejected: no desktop session (DISPLAY/WAYLAND_DISPLAY missing)")
                return False
        
        try:
            import pystray
            # Note: HAS_MENU check requires a backend to be selected, 
            # which usually happens when creating an Icon, but pystray 
            # can sometimes report it early.
            return getattr(pystray.Icon, "HAS_MENU", True)
        except ImportError:
            logger.debug("%s tray rejected: pystray missing", sys_name)
            return False
            
    return False


def get_tray_app_class() -> Type[TrayApp]:
    """Return the platform-appropriate TrayApp implementation."""
    sys_name = platform.system().lower()
    
    if sys_name == "darwin":
        from asky.daemon.tray_macos import MacosTrayApp
        return MacosTrayApp
        
    if sys_name in ("linux", "windows"):
        from asky.daemon.tray_pystray import PystrayTrayApp
        return PystrayTrayApp
        
    raise RuntimeError(f"No tray implementation for platform: {sys_name}")


def run_tray_app() -> None:
    """Acquire lock and run the platform-appropriate tray application."""
    from asky.daemon.runtime_owner import RuntimeOwnerLock, RuntimeMode
    
    lock = RuntimeOwnerLock()
    if not lock.acquire(RuntimeMode.TRAY):
        from asky.daemon.menubar import MENUBAR_ALREADY_RUNNING_MESSAGE
        logger.warning("tray launch rejected: already running")
        print(f"Error: {MENUBAR_ALREADY_RUNNING_MESSAGE}")
        raise SystemExit(1)
        
    try:
        app_cls = get_tray_app_class()
        app = app_cls()
        app.run()
    finally:
        lock.release()
