"""Platform-agnostic tray business logic for daemon service control."""

from __future__ import annotations

import logging
import threading
from typing import Callable, List, Optional

from asky.daemon import startup
from asky.daemon.errors import DaemonUserError
from asky.daemon.service import DaemonService
from asky.daemon.tray_protocol import TrayPluginEntry, TrayStatus

logger = logging.getLogger(__name__)


class TrayController:
    """Holds platform-agnostic daemon service/startup business logic.

    Platform-specific tray implementations (e.g. MacosTrayApp) create one
    instance and delegate all non-UI logic to it.  The two callbacks let the
    controller trigger a UI refresh or surface an error without importing any
    platform-specific library.

    Plugin-contributed menu entries are collected at construction time by
    firing the ``TRAY_MENU_REGISTER`` hook via ``hook_registry`` (if
    provided).  When no registry is given the menu degrades gracefully to
    core-only items.
    """

    def __init__(
        self,
        on_state_change: Callable[[], None],
        on_error: Callable[[str], None],
        hook_registry=None,
        startup_warnings: Optional[List[str]] = None,
    ) -> None:
        self._on_state_change = on_state_change
        self._on_error = on_error
        self._service: Optional[DaemonService] = None
        self._service_thread: Optional[threading.Thread] = None
        self._last_error = ""
        self._startup_warnings: List[str] = list(startup_warnings or [])

        self._plugin_status_entries: List[TrayPluginEntry] = []
        self._plugin_action_entries: List[TrayPluginEntry] = []

        if hook_registry is not None:
            self._collect_plugin_entries(hook_registry)

    def _collect_plugin_entries(self, hook_registry) -> None:
        from asky.plugins.hook_types import TRAY_MENU_REGISTER, TrayMenuRegisterContext

        ctx = TrayMenuRegisterContext(
            status_entries=self._plugin_status_entries,
            action_entries=self._plugin_action_entries,
            start_service=self.start_service,
            stop_service=self.stop_service,
            is_service_running=self.is_service_running,
            on_error=self._on_error,
        )
        hook_registry.invoke(TRAY_MENU_REGISTER, ctx)

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def is_service_running(self) -> bool:
        return self._service_thread is not None and self._service_thread.is_alive()

    def get_state(self) -> TrayStatus:
        startup_state = startup.get_status()
        startup_enabled = startup_state.supported and startup_state.enabled

        if not startup_state.supported:
            action_startup_label = "Run at Login Unsupported"
        elif startup_enabled:
            action_startup_label = "Disable Run at Login"
        else:
            action_startup_label = "Enable Run at Login"

        return TrayStatus(
            startup_enabled=startup_enabled,
            startup_supported=startup_state.supported,
            error_message=self._last_error,
            warnings=list(self._startup_warnings),
            plugin_status_entries=list(self._plugin_status_entries),
            plugin_action_entries=list(self._plugin_action_entries),
            status_startup_label=f"Run at login: {'on' if startup_enabled else 'off'}",
            action_startup_label=action_startup_label,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def autostart_if_ready(self) -> None:
        for entry in self._plugin_status_entries + self._plugin_action_entries:
            if entry.autostart_fn is not None:
                entry.autostart_fn()
                break

    def start_service(self) -> None:
        logger.info("tray controller start service requested")
        if self.is_service_running():
            logger.debug("start service ignored: already running")
            self._on_state_change()
            return
        self._last_error = ""
        try:
            self._service = DaemonService()
        except DaemonUserError as exc:
            logger.warning("failed to construct DaemonService: %s", exc.user_message)
            self._service = None
            self._service_thread = None
            self._last_error = exc.user_message
            self._on_error(exc.user_message)
            self._on_state_change()
            return
        except Exception:
            logger.exception("failed to construct DaemonService")
            msg = "Failed to construct daemon service. Check logs for details."
            self._service = None
            self._service_thread = None
            self._last_error = msg
            self._on_error(msg)
            self._on_state_change()
            return

        def _run_service() -> None:
            try:
                assert self._service is not None
                logger.info("daemon service thread entering foreground loop")
                self._service.run_foreground()
                logger.info("daemon service thread exited foreground loop")
            except DaemonUserError as exc:
                logger.warning("daemon service thread user error: %s", exc.user_message)
                self._last_error = exc.user_message
                self._on_error(exc.user_message)
            except Exception:
                logger.exception("daemon service thread failed")
                msg = "Daemon crashed. Check logs for details."
                self._last_error = msg
                self._on_error(msg)
            finally:
                self._service = None
                self._service_thread = None
                self._on_state_change()

        self._service_thread = threading.Thread(
            target=_run_service,
            name="asky-daemon-service",
            daemon=True,
        )
        self._service_thread.start()
        logger.debug("daemon service thread started name=%s", self._service_thread.name)
        self._on_state_change()

    def stop_service(self) -> None:
        logger.info("tray controller stop service requested")
        if self._service is not None:
            self._service.stop()
        else:
            logger.debug("stop service: no active service instance")
        self._service = None
        self._service_thread = None
        self._on_state_change()

    def toggle_service(self) -> None:
        if self.is_service_running():
            self.stop_service()
        else:
            self.start_service()

    # ------------------------------------------------------------------
    # Startup toggle
    # ------------------------------------------------------------------

    def toggle_startup(self) -> None:
        logger.info("tray controller run-at-login toggle")
        current = startup.get_status()
        if not current.supported:
            logger.warning(
                "run-at-login toggle unsupported platform=%s", current.platform_name
            )
            self._on_error("Run at login is unsupported on this platform.")
            self._on_state_change()
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
                msg = f"Could not disable startup: {state.details}"
                self._last_error = msg
                self._on_error(msg)
                self._on_state_change()
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
                msg = f"Could not enable startup: {state.details}"
                self._last_error = msg
                self._on_error(msg)
                self._on_state_change()
                return
        self._last_error = ""
        self._on_state_change()
