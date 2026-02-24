"""NiceGUI sidecar server for daemon plugin runtime."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from asky.plugins.gui_server.pages.general_settings import mount_general_settings_page
from asky.plugins.gui_server.pages.plugin_registry import (
    PluginPageRegistry,
    mount_plugin_registry_page,
)

logger = logging.getLogger(__name__)

DEFAULT_GUI_HOST = "127.0.0.1"
DEFAULT_GUI_PORT = 8766
SERVER_STOP_JOIN_TIMEOUT_SECONDS = 2.0

Runner = Callable[[str, int, Path, PluginPageRegistry], None]
Shutdown = Callable[[], None]


class NiceGUIServer:
    """Manage NiceGUI lifecycle in a background thread."""

    def __init__(
        self,
        *,
        config_dir: Path,
        page_registry: PluginPageRegistry,
        host: str = DEFAULT_GUI_HOST,
        port: int = DEFAULT_GUI_PORT,
        runner: Optional[Runner] = None,
        shutdown: Optional[Shutdown] = None,
    ) -> None:
        self.config_dir = config_dir
        self.page_registry = page_registry
        self.host = str(host or DEFAULT_GUI_HOST)
        self.port = int(port)
        self._runner = runner or _default_runner
        self._shutdown = shutdown or _default_shutdown
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._last_error: Optional[str] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start GUI server in background thread."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._running = True
            self._last_error = None
            self._thread = threading.Thread(
                target=self._run_thread,
                name="asky-gui-server",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """Stop GUI server if running."""
        with self._lock:
            thread = self._thread
        if thread is None:
            return

        try:
            self._shutdown()
        except Exception:
            logger.exception("GUI shutdown hook failed")

        thread.join(timeout=SERVER_STOP_JOIN_TIMEOUT_SECONDS)
        with self._lock:
            self._running = False

    def health_check(self) -> dict[str, Any]:
        """Return basic runtime health payload."""
        thread = self._thread
        return {
            "running": bool(thread and thread.is_alive() and self._running),
            "host": self.host,
            "port": self.port,
            "error": self._last_error,
        }

    def _run_thread(self) -> None:
        try:
            self._runner(self.host, self.port, self.config_dir, self.page_registry)
        except Exception as exc:
            self._last_error = str(exc)
            self._running = False
            logger.exception("GUI server failed to start")
        finally:
            self._running = False


def _default_runner(
    host: str,
    port: int,
    config_dir: Path,
    page_registry: PluginPageRegistry,
) -> None:
    from nicegui import ui

    mount_general_settings_page(ui, config_dir=config_dir)
    mount_plugin_registry_page(ui, page_registry)
    page_registry.mount_pages(ui)
    ui.run(
        host=host,
        port=port,
        show=False,
        reload=False,
        title="Asky GUI",
    )


def _default_shutdown() -> None:
    try:
        from nicegui import app

        app.shutdown()
    except Exception:
        logger.debug("NiceGUI app shutdown unavailable", exc_info=True)
