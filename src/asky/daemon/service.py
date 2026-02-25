"""Foreground daemon service bootstrap — transport-agnostic lifecycle manager."""

from __future__ import annotations

import logging
import threading
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
    transport). Transport is optional: if none is registered the daemon runs sidecar
    servers only and blocks until stop() is called. More than one transport raises
    DaemonUserError immediately.
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
        self._stop_event = threading.Event()

        self._register_plugin_servers()
        self._register_transport()

        logger.debug(
            "DaemonService initialized transport=%s sidecar_count=%d",
            self._transport.name if self._transport else "none",
            len(self._plugin_servers),
        )

    def run_foreground(self) -> None:
        """Start sidecar servers, run foreground loop, then clean up.

        If a transport is registered it drives the blocking loop. With no transport
        the daemon runs sidecar servers only and blocks until stop() is called.
        """
        self._running = True
        self._stop_event.clear()
        self._start_plugin_servers()
        try:
            if self._transport is not None:
                logger.info("daemon foreground loop starting transport=%s", self._transport.name)
                self._transport.run()
            else:
                logger.info("daemon foreground loop: no transport, running sidecar servers only")
                self._stop_event.wait()
        finally:
            self._stop_plugin_servers()
            if self.plugin_runtime is not None:
                self.plugin_runtime.shutdown()
            self._running = False
            logger.info("daemon foreground loop exited")

    def stop(self) -> None:
        """Request shutdown: stops transport if present, otherwise signals the wait event."""
        if not self._running:
            logger.debug("daemon stop requested while not running")
            return
        if self._transport is not None:
            logger.info("daemon stop requested transport=%s", self._transport.name)
            self._transport.stop()
        else:
            logger.info("daemon stop requested (sidecar-only mode)")
            self._stop_event.set()

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
            logger.warning("No plugin runtime available; daemon will run without a transport.")
            return
        context = DaemonTransportRegisterContext(double_verbose=self._double_verbose)
        runtime.hooks.invoke(DAEMON_TRANSPORT_REGISTER, context)

        if len(context.transports) > 1:
            names = ", ".join(t.name for t in context.transports)
            raise DaemonUserError(
                f"Multiple daemon transports registered ({names}); exactly one is required.",
            )
        if context.transports:
            self._transport = context.transports[0]
        else:
            logger.info("No daemon transport registered; running sidecar servers only.")

    def get_plugin_server(self, name: str) -> Optional[DaemonServerSpec]:
        """Return the sidecar spec registered under *name*, or None."""
        for spec in self._plugin_servers:
            if spec.name == name:
                return spec
        return None

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
