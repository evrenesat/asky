"""XMPPDaemonPlugin: registers the XMPP transport for daemon mode."""

from __future__ import annotations

import logging
from typing import Optional

from asky.config import XMPP_ENABLED
from asky.daemon.errors import DaemonUserError
from asky.plugins.base import AskyPlugin, CapabilityCategory, CLIContribution, PluginContext
from asky.plugins.hook_types import (
    DAEMON_TRANSPORT_REGISTER,
    TRAY_MENU_REGISTER,
    DaemonTransportRegisterContext,
    DaemonTransportSpec,
    TrayMenuRegisterContext,
)

logger = logging.getLogger(__name__)
XMPP_TRANSPORT_NAME = "xmpp"


class XMPPDaemonPlugin(AskyPlugin):
    """Built-in plugin that provides the XMPP daemon transport."""

    def __init__(self) -> None:
        self._context: Optional[PluginContext] = None

    @classmethod
    def get_cli_contributions(cls) -> list[CLIContribution]:
        return [
            CLIContribution(
                category=CapabilityCategory.BACKGROUND_SERVICE,
                flags=("--daemon",),
                kwargs=dict(
                    action="store_true",
                    help="Run the XMPP daemon in the foreground.",
                ),
            ),
        ]

    @property
    def declared_capabilities(self) -> tuple[str, ...]:
        return ("daemon_transport",)

    def activate(self, context: PluginContext) -> None:
        self._context = context
        context.hook_registry.register(
            DAEMON_TRANSPORT_REGISTER,
            self._on_daemon_transport_register,
            plugin_name=context.plugin_name,
        )
        context.hook_registry.register(
            TRAY_MENU_REGISTER,
            self._on_tray_menu_register,
            plugin_name=context.plugin_name,
        )

    def deactivate(self) -> None:
        self._context = None

    def _on_daemon_transport_register(
        self, payload: DaemonTransportRegisterContext
    ) -> None:
        if not XMPP_ENABLED:
            raise DaemonUserError(
                "XMPP daemon is disabled in xmpp.toml (xmpp.enabled=false).",
                hint="Run asky --edit-daemon to enable it.",
            )

        from asky.cli.daemon_config import get_daemon_settings

        settings = get_daemon_settings()
        if not settings.has_minimum_requirements():
            raise DaemonUserError(
                "XMPP configuration is incomplete. "
                "Run `asky --edit-daemon` to configure JID, password, and allowed users."
            )

        from asky.plugins.runtime import get_or_create_plugin_runtime
        from asky.plugins.xmpp_daemon.xmpp_service import XMPPService

        service = XMPPService(
            double_verbose=payload.double_verbose,
            plugin_runtime=get_or_create_plugin_runtime(),
        )
        payload.transports.append(
            DaemonTransportSpec(
                name=XMPP_TRANSPORT_NAME,
                run=service.run,
                stop=service.stop,
            )
        )
        logger.debug("XMPP transport registered double_verbose=%s", payload.double_verbose)

    def _on_tray_menu_register(self, ctx: TrayMenuRegisterContext) -> None:
        from asky.cli.daemon_config import get_daemon_settings, update_daemon_settings
        from asky.daemon.tray_protocol import TrayPluginEntry

        ctx.status_entries.append(
            TrayPluginEntry(
                get_label=lambda: f"XMPP: {'connected' if ctx.is_service_running() else 'stopped'}"
            )
        )
        ctx.status_entries.append(
            TrayPluginEntry(
                get_label=lambda: f"JID: {get_daemon_settings().jid or '(unset)'}"
            )
        )
        ctx.action_entries.append(
            TrayPluginEntry(
                get_label=lambda: "Stop XMPP"
                if ctx.is_service_running()
                else "Start XMPP",
                on_action=lambda: self._toggle_xmpp(ctx, update_daemon_settings),
                autostart_fn=lambda: self._autostart_if_ready(ctx, update_daemon_settings),
            )
        )

    def _toggle_xmpp(self, ctx: TrayMenuRegisterContext, update_daemon_settings) -> None:
        if ctx.is_service_running():
            ctx.stop_service()
        else:
            update_daemon_settings(enabled=True)
            ctx.start_service()

    def _autostart_if_ready(
        self, ctx: TrayMenuRegisterContext, update_daemon_settings
    ) -> None:
        from asky.cli.daemon_config import get_daemon_settings

        settings = get_daemon_settings()
        logger.debug(
            "xmpp autostart check enabled=%s minimum_ready=%s",
            settings.enabled,
            settings.has_minimum_requirements(),
        )
        if settings.has_minimum_requirements() and settings.enabled:
            ctx.start_service()
