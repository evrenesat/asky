"""GUI server plugin entrypoint."""

from __future__ import annotations

from typing import Optional

from asky.daemon.job_queue import JobQueue
from asky.plugins.base import AskyPlugin, PluginContext
from asky.plugins.gui_server.pages.plugin_registry import get_plugin_page_registry
from asky.plugins.gui_server.server import DEFAULT_GUI_HOST, DEFAULT_GUI_PORT, NiceGUIServer
from asky.plugins.hook_types import (
    DAEMON_SERVER_REGISTER,
    GUI_EXTENSION_REGISTER,
    TRAY_MENU_REGISTER,
    DaemonServerRegisterContext,
    DaemonServerSpec,
    GUIExtensionRegisterContext,
    TrayMenuRegisterContext,
)

DAEMON_SERVER_PRIORITY = 100
GUI_SERVER_NAME = "nicegui_server"


class GUIServerPlugin(AskyPlugin):
    """Registers a NiceGUI sidecar server in daemon mode."""

    def __init__(self) -> None:
        self._context: Optional[PluginContext] = None
        self._server: Optional[NiceGUIServer] = None
        self._queue: Optional[JobQueue] = None

    @property
    def declared_capabilities(self) -> tuple[str, ...]:
        return ("daemon_server", "gui", "job_queue")

    def activate(self, context: PluginContext) -> None:
        self._context = context
        self._queue = JobQueue(context.data_dir / "jobs.db")
        context.hook_registry.register(
            DAEMON_SERVER_REGISTER,
            self._on_daemon_server_register,
            plugin_name=context.plugin_name,
            priority=DAEMON_SERVER_PRIORITY,
        )
        context.hook_registry.register(
            TRAY_MENU_REGISTER,
            self._on_tray_menu_register,
            plugin_name=context.plugin_name,
        )

    def deactivate(self) -> None:
        if self._queue is not None:
            self._queue.stop()
        if self._server is not None:
            self._server.stop()
        self._queue = None
        self._server = None
        self._context = None

    def _on_daemon_server_register(self, payload: DaemonServerRegisterContext) -> None:
        context = self._context
        if context is None or self._queue is None:
            return

        # Start the queue worker
        self._queue.start()

        # Invoke GUI extension hooks before server starts
        registry = get_plugin_page_registry()
        ext_context = GUIExtensionRegisterContext(
            register_page=registry.register_page,
            register_job_handler=self._queue.register_handler,
            queue=self._queue,
        )
        context.hook_registry.invoke(GUI_EXTENSION_REGISTER, ext_context)

        host = str(context.config.get("host", DEFAULT_GUI_HOST) or DEFAULT_GUI_HOST)
        port = int(context.config.get("port", DEFAULT_GUI_PORT) or DEFAULT_GUI_PORT)
        password = context.config.get("password")

        if self._server is None:
            self._server = NiceGUIServer(
                config_dir=context.config_dir,
                data_dir=context.data_dir,
                page_registry=registry,
                host=host,
                port=port,
                password=password,
                job_queue=self._queue,
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

    def _on_tray_menu_register(self, ctx: TrayMenuRegisterContext) -> None:
        import webbrowser

        from asky.daemon.tray_protocol import TrayPluginEntry

        context = self._context
        if context is None:
            return

        host = str(context.config.get("host", DEFAULT_GUI_HOST) or DEFAULT_GUI_HOST)
        port = int(context.config.get("port", DEFAULT_GUI_PORT) or DEFAULT_GUI_PORT)

        ctx.action_entries.append(
            TrayPluginEntry(
                get_label=lambda: "Stop Web GUI"
                if (self._server is not None and self._server.health_check().get("running"))
                else "Start Web GUI",
                on_action=lambda: self._toggle_server(ctx),
            )
        )
        ctx.action_entries.append(
            TrayPluginEntry(
                get_label=lambda: "Open Web Console",
                on_action=lambda: webbrowser.open(f"http://{host}:{port}/"),
            )
        )

    def _toggle_server(self, ctx: TrayMenuRegisterContext) -> None:
        context = self._context
        if context is None:
            return
        if self._server is not None and self._server.health_check().get("running"):
            self._server.stop()
        else:
            if self._server is None:
                host = str(
                    context.config.get("host", DEFAULT_GUI_HOST) or DEFAULT_GUI_HOST
                )
                port = int(
                    context.config.get("port", DEFAULT_GUI_PORT) or DEFAULT_GUI_PORT
                )
                password = context.config.get("password")
                self._server = NiceGUIServer(
                    config_dir=context.config_dir,
                    data_dir=context.data_dir,
                    page_registry=get_plugin_page_registry(),
                    host=host,
                    port=port,
                    password=password,
                    job_queue=self._queue,
                )
            try:
                self._server.start()
            except RuntimeError as exc:
                ctx.on_error(str(exc))
