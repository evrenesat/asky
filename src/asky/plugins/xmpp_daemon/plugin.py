"""XMPPDaemonPlugin: registers the XMPP transport for daemon mode."""

from __future__ import annotations

import logging
from typing import Optional

from asky.config import XMPP_ENABLED
from asky.daemon.errors import DaemonUserError
from asky.plugins.base import AskyPlugin, PluginContext
from asky.plugins.hook_types import (
    DAEMON_TRANSPORT_REGISTER,
    DaemonTransportRegisterContext,
    DaemonTransportSpec,
)

logger = logging.getLogger(__name__)
XMPP_TRANSPORT_NAME = "xmpp"


class XMPPDaemonPlugin(AskyPlugin):
    """Built-in plugin that provides the XMPP daemon transport."""

    def __init__(self) -> None:
        self._context: Optional[PluginContext] = None

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
