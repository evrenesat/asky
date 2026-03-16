"""macOS menubar application launcher for daemon control."""

from __future__ import annotations

import logging
import platform
from pathlib import Path
from typing import Optional

from asky.daemon.errors import DaemonUserError
from asky.daemon.runtime_owner import RuntimeOwnerLock, RuntimeMode

MENUBAR_ALREADY_RUNNING_MESSAGE = "asky menubar daemon is already running."
logger = logging.getLogger(__name__)


def acquire_menubar_singleton_lock() -> RuntimeOwnerLock:
    """Acquire tray singleton lock and return holder object."""
    lock = RuntimeOwnerLock()
    if not lock.acquire(RuntimeMode.TRAY):
        raise DaemonUserError(
            MENUBAR_ALREADY_RUNNING_MESSAGE,
            hint="Use the existing menu icon.",
        )
    return lock


def is_menubar_instance_running() -> bool:
    """Return whether a tray process currently holds the singleton lock."""
    lock = RuntimeOwnerLock()
    owner = lock.get_owner()
    if owner and lock._is_process_alive(owner.pid):
        return True
    return False


def has_rumps() -> bool:
    """Return whether rumps is importable."""
    try:
        import rumps  # type: ignore  # noqa: F401
    except ImportError:
        logger.debug("rumps import failed")
        return False
    logger.debug("rumps import is available")
    return True


def run_menubar_app() -> None:
    """Start menubar app when running on macOS and rumps is available."""
    logger.info("starting menubar app bootstrap")
    if platform.system().lower() != "darwin":
        logger.error("menubar bootstrap rejected: non-macos platform")
        raise RuntimeError("Menubar daemon mode is supported only on macOS.")
    try:
        import rumps  # type: ignore  # noqa: F401
    except ImportError as exc:
        logger.exception("menubar bootstrap failed: missing rumps")
        raise RuntimeError(
            "rumps is required for menubar mode. Install asky-cli[mac]."
        ) from exc

    singleton_lock = acquire_menubar_singleton_lock()

    from asky.daemon.tray_macos import MacosTrayApp

    logger.info("running menubar app event loop")
    tray = MacosTrayApp()
    try:
        tray.run()
    finally:
        singleton_lock.release()
