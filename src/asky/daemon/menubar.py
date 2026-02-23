"""macOS menubar application for daemon control."""

from __future__ import annotations

import errno
import logging
import os
import platform
import threading
from pathlib import Path
from typing import Optional, TextIO

from asky.cli.daemon_config import (
    get_daemon_settings,
    update_daemon_settings,
)
from asky.daemon import startup
from asky.daemon.errors import DaemonUserError
from asky.daemon.service import XMPPDaemonService

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

ICON_FILE_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "icons" / "asky_icon_mono.ico"
)
ICON_FALLBACK_FILE_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "icons" / "asky_icon_small.png"
)
MENUBAR_LOCK_PATH = Path.home() / ".config" / "asky" / "locks" / "menubar.lock"
MENUBAR_ALREADY_RUNNING_MESSAGE = "asky menubar daemon is already running."
MISSING_XMPP_CONFIG_MESSAGE = "XMPP configuration is incomplete."
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
        import rumps  # type: ignore
    except ImportError as exc:
        logger.exception("menubar bootstrap failed: missing rumps")
        raise RuntimeError(
            "rumps is required for menubar mode. Install asky-cli[mac]."
        ) from exc

    singleton_lock = acquire_menubar_singleton_lock()

    icon_path = ICON_FILE_PATH if ICON_FILE_PATH.exists() else None
    if icon_path is None and ICON_FALLBACK_FILE_PATH.exists():
        icon_path = ICON_FALLBACK_FILE_PATH
    if icon_path is None:
        logger.warning(
            "menubar icon missing paths=%s,%s; falling back to default title-only icon",
            ICON_FILE_PATH,
            ICON_FALLBACK_FILE_PATH,
        )

    class AskyMenubarApp(rumps.App):
        def __init__(self):
            logger.debug("initializing menubar app icon=%s", icon_path)
            super().__init__(
                "asky",
                icon=str(icon_path) if icon_path is not None else None,
                quit_button=None,
            )
            self._service: Optional[XMPPDaemonService] = None
            self._service_thread: Optional[threading.Thread] = None
            self._last_error = ""
            self.status_daemon = rumps.MenuItem("Daemon: stopped")
            self.status_jid = rumps.MenuItem("JID: (unset)")
            self.status_voice = rumps.MenuItem("Voice: off")
            self.status_startup = rumps.MenuItem("Run at login: off")
            self.action_daemon = rumps.MenuItem(
                "Start Daemon", callback=self._on_daemon_action
            )
            self.action_voice = rumps.MenuItem(
                "Enable Voice", callback=self._on_voice_action
            )
            self.action_startup = rumps.MenuItem(
                "Enable Run at Login",
                callback=self._on_startup_action,
            )
            self.action_quit = rumps.MenuItem("Quit", callback=self._on_quit_action)
            self.menu = [
                self.status_daemon,
                self.status_jid,
                self.status_voice,
                self.status_startup,
                None,
                self.action_daemon,
                self.action_voice,
                self.action_startup,
                self.action_quit,
            ]
            self._refresh_status()
            try:
                self._autostart_if_ready()
            except DaemonUserError as exc:
                logger.warning("menubar autostart blocked: %s", exc.user_message)
                self._set_error(exc.user_message, alert_user=True)
            except Exception:
                logger.exception("menubar autostart failed")
                self._set_error(
                    "Autostart failed. Check logs for details.", alert_user=True
                )

        def _set_error(self, message: str, *, alert_user: bool) -> None:
            self._last_error = str(message or "").strip()
            if alert_user and self._last_error:
                rumps.alert(self._last_error)
            self._refresh_status()

        def _autostart_if_ready(self) -> None:
            settings = get_daemon_settings()
            logger.debug(
                "autostart check enabled=%s minimum_ready=%s",
                settings.enabled,
                settings.has_minimum_requirements(),
            )
            if settings.has_minimum_requirements() and settings.enabled:
                self._start_daemon()

        def _refresh_menu_actions(
            self,
            *,
            daemon_running: bool,
            voice_enabled: bool,
            startup_supported: bool,
            startup_enabled: bool,
        ) -> None:
            self.action_daemon.title = (
                "Stop Daemon" if daemon_running else "Start Daemon"
            )
            self.action_voice.title = (
                "Disable Voice" if voice_enabled else "Enable Voice"
            )
            if startup_supported:
                self.action_startup.title = (
                    "Disable Run at Login" if startup_enabled else "Enable Run at Login"
                )
            else:
                self.action_startup.title = "Run at Login Unsupported"

        def _refresh_status(self) -> None:
            settings = get_daemon_settings()
            startup_state = startup.get_status()
            daemon_running = (
                self._service_thread is not None and self._service_thread.is_alive()
            )
            startup_enabled = startup_state.supported and startup_state.enabled
            self.status_daemon.title = (
                f"Daemon: {'running' if daemon_running else 'stopped'}"
            )
            jid_text = settings.jid if settings.jid else "(unset)"
            self.status_jid.title = f"JID: {jid_text}"
            self.status_voice.title = (
                f"Voice: {'on' if settings.voice_enabled else 'off'}"
            )
            self.status_startup.title = (
                f"Run at login: {'on' if startup_enabled else 'off'}"
            )
            if self._last_error:
                self.status_daemon.title = f"Daemon: error ({self._last_error})"
            self._refresh_menu_actions(
                daemon_running=daemon_running,
                voice_enabled=settings.voice_enabled,
                startup_supported=startup_state.supported,
                startup_enabled=startup_enabled,
            )
            logger.debug(
                "status refresh daemon_running=%s jid=%s voice=%s startup_enabled=%s last_error=%s",
                daemon_running,
                settings.jid,
                settings.voice_enabled,
                startup_enabled,
                self._last_error,
            )

        def _start_daemon(self) -> None:
            logger.info("menubar start daemon requested")
            if self._service_thread is not None and self._service_thread.is_alive():
                logger.debug("start daemon ignored: already running")
                self._refresh_status()
                return
            settings = get_daemon_settings()
            logger.debug(
                "start daemon precheck enabled=%s minimum_ready=%s password_env=%s",
                settings.enabled,
                settings.has_minimum_requirements(),
                settings.password_env,
            )
            if not settings.has_minimum_requirements():
                logger.warning("start daemon aborted: missing configuration")
                self._set_error(
                    f"{MISSING_XMPP_CONFIG_MESSAGE} Run `asky --edit-daemon` to configure JID, password, and allowed users.",
                    alert_user=True,
                )
                return
            update_daemon_settings(enabled=True)
            self._last_error = ""
            try:
                self._service = XMPPDaemonService()
            except DaemonUserError as exc:
                logger.warning(
                    "failed to construct XMPPDaemonService: %s", exc.user_message
                )
                self._service = None
                self._service_thread = None
                self._set_error(exc.user_message, alert_user=True)
                return
            except Exception:
                logger.exception("failed to construct XMPPDaemonService")
                self._service = None
                self._service_thread = None
                self._set_error(
                    "Failed to construct daemon service. Check logs for details.",
                    alert_user=True,
                )
                return

            def _run_service() -> None:
                try:
                    assert self._service is not None
                    logger.info("daemon service thread entering foreground loop")
                    self._service.run_foreground()
                    logger.info("daemon service thread exited foreground loop")
                except DaemonUserError as exc:
                    logger.warning(
                        "daemon service thread user error: %s", exc.user_message
                    )
                    self._set_error(exc.user_message, alert_user=True)
                except Exception:
                    logger.exception("daemon service thread failed")
                    self._set_error(
                        "Daemon crashed. Check logs for details.", alert_user=True
                    )
                finally:
                    self._service = None
                    self._service_thread = None
                    self._refresh_status()

            self._service_thread = threading.Thread(
                target=_run_service,
                name="asky-menubar-daemon",
                daemon=True,
            )
            self._service_thread.start()
            logger.debug(
                "daemon service thread started name=%s", self._service_thread.name
            )
            self._refresh_status()

        def _stop_daemon(self) -> None:
            logger.info("menubar stop daemon requested")
            if self._service is not None:
                self._service.stop()
            else:
                logger.debug("stop daemon: no active service instance")
            self._service = None
            self._service_thread = None
            self._refresh_status()

        def _on_daemon_action(self, _sender) -> None:
            daemon_running = (
                self._service_thread is not None and self._service_thread.is_alive()
            )
            if daemon_running:
                self._stop_daemon()
            else:
                self._start_daemon()

        def _on_voice_action(self, _sender) -> None:
            logger.info("menubar voice action clicked")
            settings = get_daemon_settings()
            update_daemon_settings(voice_enabled=not settings.voice_enabled)
            self._refresh_status()

        def _on_startup_action(self, _sender) -> None:
            logger.info("menubar run-at-login action clicked")
            current = startup.get_status()
            if not current.supported:
                logger.warning(
                    "run-at-login toggle unsupported platform=%s", current.platform_name
                )
                rumps.alert("Run at login is unsupported on this platform.")
                self._refresh_status()
                return
            if current.enabled:
                state = startup.disable_startup()
                logger.debug(
                    "run-at-login disable result enabled=%s active=%s details=%s",
                    state.enabled,
                    state.active,
                    state.details,
                )
                if state.enabled:
                    self._set_error(
                        f"Could not disable startup: {state.details}", alert_user=True
                    )
                    return
            else:
                state = startup.enable_startup()
                logger.debug(
                    "run-at-login enable result enabled=%s active=%s details=%s",
                    state.enabled,
                    state.active,
                    state.details,
                )
                if not state.enabled:
                    self._set_error(
                        f"Could not enable startup: {state.details}", alert_user=True
                    )
                    return
            self._last_error = ""
            self._refresh_status()

        def _on_quit_action(self, _sender) -> None:
            logger.info("menubar quit action clicked")
            self._stop_daemon()
            rumps.quit_application()

    logger.info("running menubar app event loop")
    try:
        app = AskyMenubarApp()
        app.run()
    finally:
        singleton_lock.release()
