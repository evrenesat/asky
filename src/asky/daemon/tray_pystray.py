"""Linux and Windows system tray implementation using pystray."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from asky.daemon.errors import DaemonUserError
from asky.daemon.tray_controller import TrayController
from asky.daemon.tray_protocol import TrayApp, TrayStatus

logger = logging.getLogger(__name__)

ICON_FILE_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "icons" / "asky_icon_mono.ico"
)


class PystrayTrayApp(TrayApp):
    """Linux/Windows tray using the pystray library."""

    def __init__(self):
        self._icon: Optional["pystray.Icon"] = None
        self._controller: Optional[TrayController] = None

    def run(self) -> None:
        """Start the pystray event loop. Blocks until quit."""
        try:
            import pystray
            from PIL import Image
        except ImportError as exc:
            logger.exception("pystray or PIL import failed")
            raise RuntimeError(
                "pystray and Pillow are required for tray mode. Install asky-cli[tray]."
            ) from exc

        if not pystray.Icon.HAS_MENU:
            raise RuntimeError("Selected pystray backend does not support menus.")

        icon_img = Image.open(ICON_FILE_PATH) if ICON_FILE_PATH.exists() else Image.new('RGB', (64, 64), color='red')

        from asky.plugins.runtime import get_or_create_plugin_runtime
        runtime = get_or_create_plugin_runtime()
        startup_warnings = runtime.get_startup_warnings() if runtime is not None else []
        hook_registry = runtime.hooks if runtime is not None else None

        self._controller = TrayController(
            on_state_change=self._refresh_menu,
            on_error=self._show_error,
            hook_registry=hook_registry,
            startup_warnings=startup_warnings,
        )

        self._icon = pystray.Icon("asky", icon_img, "asky")
        self._refresh_menu()
        
        try:
            self._controller.autostart_if_ready()
        except Exception:
            logger.exception("pystray autostart failed")

        logger.info("running pystray event loop")
        self._icon.run()

    def _show_error(self, message: str) -> None:
        logger.error("Tray error: %s", message)
        if self._icon:
            try:
                self._icon.notify(message, title="Asky Error")
            except Exception:
                logger.debug("pystray notify failed", exc_info=True)

    def _refresh_menu(self) -> None:
        if not self._icon or not self._controller:
            return

        import pystray
        state: TrayStatus = self._controller.get_state()
        
        menu_items = []
        
        # Plugin status entries (disabled menu items)
        for entry in state.plugin_status_entries:
            label = entry.get_label()
            if label:
                menu_items.append(pystray.MenuItem(label, action=None, enabled=False))
        
        if state.plugin_status_entries:
            menu_items.append(pystray.Menu.SEPARATOR)

        # Plugin action entries
        for entry in state.plugin_action_entries:
            label = entry.get_label()
            if label:
                menu_items.append(pystray.MenuItem(label, action=self._make_action_handler(entry)))

        if state.plugin_action_entries:
            menu_items.append(pystray.Menu.SEPARATOR)

        # Core entries
        menu_items.append(pystray.MenuItem(state.action_startup_label, action=self._on_startup_action))
        menu_items.append(pystray.MenuItem("Quit", action=self._on_quit_action))

        self._icon.menu = pystray.Menu(*menu_items)
        
        if state.warnings:
            for w in state.warnings:
                self._show_error(w)
            self._controller._startup_warnings.clear()

    def _make_action_handler(self, entry):
        def handler(icon, item):
            if entry.on_action:
                entry.on_action()
            self._refresh_menu()
        return handler

    def _on_startup_action(self, icon, item):
        if self._controller:
            self._controller.toggle_startup()

    def _on_quit_action(self, icon, item):
        logger.info("pystray quit action clicked")
        if self._controller:
            self._controller.stop_service()
        if self._icon:
            self._icon.stop()

    def update_status(self, status: TrayStatus) -> None:
        self._refresh_menu()
