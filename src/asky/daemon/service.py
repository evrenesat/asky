"""Foreground daemon service bootstrap — transport-agnostic lifecycle manager."""

from __future__ import annotations

import logging
from typing import Any, Optional

from asky.daemon.errors import DaemonUserError
from asky.logger import setup_xmpp_logging
from asky.plugins.hook_types import (
    DAEMON_SERVER_REGISTER,
    DAEMON_TRANSPORT_REGISTER,
    DaemonServerRegisterContext,
    DaemonServerSpec,
    DaemonTransportRegisterContext,
    DaemonTransportSpec,
)
from asky.plugins.runtime import get_or_create_plugin_runtime
from asky.storage import init_db

logger = logging.getLogger(__name__)


class DaemonService:
    """Lifecycle coordinator for pluggable daemon transports and sidecar servers.

    On construction the service fires DAEMON_SERVER_REGISTER (to collect sidecar
    servers from plugins) and DAEMON_TRANSPORT_REGISTER (to collect the primary
    transport). Exactly one transport must be registered; zero or more than one
    raises DaemonUserError immediately.
    """

    def __init__(
        self,
        double_verbose: bool = False,
        plugin_runtime: Optional[Any] = None,
    ):
        logger.debug("initializing DaemonService double_verbose=%s", double_verbose)
        init_db()
        self.plugin_runtime = plugin_runtime or get_or_create_plugin_runtime()
        self._double_verbose = double_verbose
        self._plugin_servers: list[DaemonServerSpec] = []
        self._transport: Optional[DaemonTransportSpec] = None
        self._running = False

        self._register_plugin_servers()
        self._register_transport()

        logger.debug(
            "DaemonService initialized transport=%s sidecar_count=%d",
            self._transport.name if self._transport else "none",
            len(self._plugin_servers),
        )

    def run_foreground(self) -> None:
        """Start sidecar servers, run transport foreground loop, then clean up."""
        if self._transport is None:
            raise DaemonUserError(
                "No daemon transport registered.",
                hint="Enable the xmpp_daemon plugin in plugins.toml.",
            )
        logger.info("daemon foreground loop starting transport=%s", self._transport.name)
        self._running = True
        self._start_plugin_servers()
        try:
            self._transport.run()
        finally:
            self._stop_plugin_servers()
            if self.plugin_runtime is not None:
                self.plugin_runtime.shutdown()
            self._running = False
            logger.info("daemon foreground loop exited")

    def stop(self) -> None:
        """Request transport shutdown."""
        if not self._running:
            logger.debug("daemon stop requested while not running")
            return
        if self._transport is None:
            return
        logger.info("daemon stop requested transport=%s", self._transport.name)
        self._transport.stop()

    def _register_plugin_servers(self) -> None:
        runtime = self.plugin_runtime
        if runtime is None:
            return
        context = DaemonServerRegisterContext(service=self)
        runtime.hooks.invoke(DAEMON_SERVER_REGISTER, context)
        for spec in context.servers:
            self._add_plugin_server(spec)

    def _add_plugin_server(self, spec: DaemonServerSpec) -> None:
        if not isinstance(spec, DaemonServerSpec):
            logger.warning(
                "Ignoring invalid plugin server spec type: %s",
                type(spec).__name__,
            )
            return
        self._plugin_servers.append(spec)

    def _register_transport(self) -> None:
        runtime = self.plugin_runtime
        if runtime is None:
            raise DaemonUserError(
                "No plugin runtime available; cannot register daemon transport.",
                hint="Enable the xmpp_daemon plugin in plugins.toml.",
            )
        context = DaemonTransportRegisterContext(double_verbose=self._double_verbose)
        runtime.hooks.invoke(DAEMON_TRANSPORT_REGISTER, context)

        if len(context.transports) == 0:
            raise DaemonUserError(
                "No daemon transport was registered by any plugin.",
                hint="Enable the xmpp_daemon plugin in plugins.toml.",
            )
        if len(context.transports) > 1:
            names = ", ".join(t.name for t in context.transports)
            raise DaemonUserError(
                f"Multiple daemon transports registered ({names}); exactly one is required.",
            )
        self._transport = context.transports[0]

    def _start_plugin_servers(self) -> None:
        for spec in self._plugin_servers:
            try:
                spec.start()
                logger.info("Started plugin server '%s'", spec.name)
            except Exception:
                logger.exception("Plugin server '%s' failed to start", spec.name)

    def _stop_plugin_servers(self) -> None:
        for spec in reversed(self._plugin_servers):
            stop_fn = spec.stop
            if stop_fn is None:
                continue
            try:
                stop_fn()
            except Exception:
                logger.exception("Plugin server '%s' failed to stop", spec.name)


def run_daemon_foreground(
    double_verbose: bool = False,
    plugin_runtime: Optional[Any] = None,
) -> None:
    """Entry point used by CLI flag and menubar child process."""
    setup_xmpp_logging()
    service = DaemonService(
        double_verbose=double_verbose,
        plugin_runtime=plugin_runtime,
    )
    service.run_foreground()
