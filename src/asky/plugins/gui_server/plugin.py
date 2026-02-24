"""GUI server plugin entrypoint."""

from __future__ import annotations

from typing import Optional

from asky.plugins.base import AskyPlugin, PluginContext
from asky.plugins.gui_server.pages.plugin_registry import get_plugin_page_registry
from asky.plugins.gui_server.server import DEFAULT_GUI_HOST, DEFAULT_GUI_PORT, NiceGUIServer
from asky.plugins.hook_types import (
    DAEMON_SERVER_REGISTER,
    DaemonServerRegisterContext,
    DaemonServerSpec,
)

DAEMON_SERVER_PRIORITY = 100
GUI_SERVER_NAME = "nicegui_server"


class GUIServerPlugin(AskyPlugin):
    """Registers a NiceGUI sidecar server in daemon mode."""

    def __init__(self) -> None:
        self._context: Optional[PluginContext] = None
        self._server: Optional[NiceGUIServer] = None

    @property
    def declared_capabilities(self) -> tuple[str, ...]:
        return ("daemon_server", "gui")

    def activate(self, context: PluginContext) -> None:
        self._context = context
        context.hook_registry.register(
            DAEMON_SERVER_REGISTER,
            self._on_daemon_server_register,
            plugin_name=context.plugin_name,
            priority=DAEMON_SERVER_PRIORITY,
        )

    def deactivate(self) -> None:
        if self._server is not None:
            self._server.stop()
        self._server = None
        self._context = None

    def _on_daemon_server_register(self, payload: DaemonServerRegisterContext) -> None:
        context = self._context
        if context is None:
            return

        host = str(context.config.get("host", DEFAULT_GUI_HOST) or DEFAULT_GUI_HOST)
        port = int(context.config.get("port", DEFAULT_GUI_PORT) or DEFAULT_GUI_PORT)
        if self._server is None:
            self._server = NiceGUIServer(
                config_dir=context.config_dir,
                page_registry=get_plugin_page_registry(),
                host=host,
                port=port,
            )

        for existing_spec in payload.servers:
            if existing_spec.name == GUI_SERVER_NAME:
                return

        payload.servers.append(
            DaemonServerSpec(
                name=GUI_SERVER_NAME,
                start=self._server.start,
                stop=self._server.stop,
                health_check=self._server.health_check,
            )
        )
