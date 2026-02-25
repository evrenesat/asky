"""macOS menubar application launcher for daemon control."""

from __future__ import annotations

import errno
import logging
import os
import platform
from pathlib import Path
from typing import Optional, TextIO

from asky.daemon.errors import DaemonUserError

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

MENUBAR_LOCK_PATH = Path.home() / ".config" / "asky" / "locks" / "menubar.lock"
MENUBAR_ALREADY_RUNNING_MESSAGE = "asky menubar daemon is already running."
LOCK_CONTENTION_ERRNOS = (errno.EACCES, errno.EAGAIN)
logger = logging.getLogger(__name__)


class MenubarSingletonLock:
    """File-lock guard that keeps only one menubar process active."""

    def __init__(self, lock_path: Path = MENUBAR_LOCK_PATH):
        self._lock_path = Path(lock_path).expanduser()
        self._handle: Optional[TextIO] = None

    def acquire(self) -> None:
        if fcntl is None:  # pragma: no cover
            raise RuntimeError(
                "fcntl is unavailable; menubar singleton lock cannot be enforced."
            )
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self._lock_path.open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            if exc.errno in LOCK_CONTENTION_ERRNOS:
                raise DaemonUserError(
                    MENUBAR_ALREADY_RUNNING_MESSAGE,
                    hint="Use the existing menu icon.",
                ) from exc
            raise
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        self._handle = handle
        logger.debug(
            "menubar singleton lock acquired path=%s pid=%s",
            self._lock_path,
            os.getpid(),
        )

    def release(self) -> None:
        if self._handle is None:
            return
        if fcntl is not None:
            try:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                logger.debug("menubar singleton lock unlock failed", exc_info=True)
        self._handle.close()
        self._handle = None
        logger.debug("menubar singleton lock released path=%s", self._lock_path)


def acquire_menubar_singleton_lock(
    lock_path: Path = MENUBAR_LOCK_PATH,
) -> MenubarSingletonLock:
    """Acquire menubar singleton lock and return holder object."""
    lock = MenubarSingletonLock(lock_path)
    lock.acquire()
    return lock


def is_menubar_instance_running(lock_path: Path = MENUBAR_LOCK_PATH) -> bool:
    """Return whether a menubar process currently holds the singleton lock."""
    if fcntl is None:  # pragma: no cover
        return False
    probe = MenubarSingletonLock(lock_path)
    try:
        probe.acquire()
    except DaemonUserError:
        logger.debug("menubar singleton probe: existing instance is running")
        return True
    except Exception:
        logger.exception("menubar singleton probe failed")
        return False
    probe.release()
    logger.debug("menubar singleton probe: no existing instance")
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
