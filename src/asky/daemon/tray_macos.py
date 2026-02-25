"""macOS system tray implementation using rumps."""

from __future__ import annotations

import logging
from pathlib import Path

from asky.daemon.errors import DaemonUserError
from asky.daemon.tray_controller import TrayController
from asky.daemon.tray_protocol import TrayApp, TrayPluginEntry, TrayStatus

logger = logging.getLogger(__name__)

ICON_FILE_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "icons" / "asky_icon_mono.ico"
)
ICON_FALLBACK_FILE_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "icons" / "asky_icon_small.png"
)


class MacosTrayApp(TrayApp):
    """macOS menubar tray using the rumps library."""

    def run(self) -> None:
        """Start the rumps event loop. Blocks until quit."""
        import rumps  # type: ignore

        icon_path = ICON_FILE_PATH if ICON_FILE_PATH.exists() else None
        if icon_path is None and ICON_FALLBACK_FILE_PATH.exists():
            icon_path = ICON_FALLBACK_FILE_PATH
        if icon_path is None:
            logger.warning(
                "menubar icon missing paths=%s,%s; falling back to default title-only icon",
                ICON_FILE_PATH,
                ICON_FALLBACK_FILE_PATH,
            )

        from asky.plugins.runtime import get_or_create_plugin_runtime

        runtime = get_or_create_plugin_runtime()
        startup_warnings = runtime.get_startup_warnings() if runtime is not None else []
        hook_registry = runtime.hooks if runtime is not None else None

        class AskyMenubarApp(rumps.App):
            def __init__(self_inner):
                logger.debug("initializing menubar app icon=%s", icon_path)
                super().__init__(
                    "asky",
                    icon=str(icon_path) if icon_path is not None else None,
                    quit_button=None,
                )
                self_inner._controller = TrayController(
                    on_state_change=self_inner._refresh_status,
                    on_error=rumps.alert,
                    hook_registry=hook_registry,
                    startup_warnings=startup_warnings,
                )

                self_inner._plugin_status_menu_items: list[
                    tuple[TrayPluginEntry, object]
                ] = []
                for entry in self_inner._controller._plugin_status_entries:
                    label = entry.get_label() or ""
                    item = rumps.MenuItem(label)
                    self_inner._plugin_status_menu_items.append((entry, item))

                self_inner._plugin_action_menu_items: list[
                    tuple[TrayPluginEntry, object]
                ] = []
                for entry in self_inner._controller._plugin_action_entries:
                    label = entry.get_label() or ""
                    item = rumps.MenuItem(
                        label, callback=self_inner._make_action_handler(entry)
                    )
                    self_inner._plugin_action_menu_items.append((entry, item))

                self_inner.status_startup = rumps.MenuItem("Run at login: off")
                self_inner.action_startup = rumps.MenuItem(
                    "Enable Run at Login",
                    callback=self_inner._on_startup_action,
                )
                self_inner.action_quit = rumps.MenuItem(
                    "Quit", callback=self_inner._on_quit_action
                )

                menu_items: list = []
                for _entry, item in self_inner._plugin_status_menu_items:
                    menu_items.append(item)
                menu_items.append(None)
                for _entry, item in self_inner._plugin_action_menu_items:
                    menu_items.append(item)
                menu_items.append(self_inner.action_startup)
                menu_items.append(self_inner.action_quit)
                self_inner.menu = menu_items

                self_inner._refresh_status()
                try:
                    self_inner._controller.autostart_if_ready()
                except DaemonUserError as exc:
                    logger.warning("menubar autostart blocked: %s", exc.user_message)
                    rumps.alert(exc.user_message)
                except Exception:
                    logger.exception("menubar autostart failed")
                    rumps.alert("Autostart failed. Check logs for details.")

            def _make_action_handler(self_inner, entry: TrayPluginEntry):
                def handler(_sender):
                    entry.on_action()
                    self_inner._refresh_status()

                return handler

            def _refresh_status(self_inner) -> None:
                state: TrayStatus = self_inner._controller.get_state()
                for entry, item in self_inner._plugin_status_menu_items:
                    label = entry.get_label()
                    if label is not None:
                        item.title = label
                for entry, item in self_inner._plugin_action_menu_items:
                    label = entry.get_label()
                    if label is not None:
                        item.title = label
                self_inner.status_startup.title = state.status_startup_label
                self_inner.action_startup.title = state.action_startup_label
                logger.debug(
                    "status refresh startup_enabled=%s error=%s",
                    state.startup_enabled,
                    state.error_message,
                )
                if state.warnings:
                    for w in state.warnings:
                        rumps.alert(w)
                    self_inner._controller._startup_warnings.clear()

            def _on_startup_action(self_inner, _sender) -> None:
                self_inner._controller.toggle_startup()

            def _on_quit_action(self_inner, _sender) -> None:
                logger.info("menubar quit action clicked")
                self_inner._controller.stop_service()
                rumps.quit_application()

        logger.info("running macOS menubar app event loop")
        app = AskyMenubarApp()
        app.run()

    def update_status(self, status: TrayStatus) -> None:
        """Status updates are handled internally via _refresh_status in run()."""
        pass
