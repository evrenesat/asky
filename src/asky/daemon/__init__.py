"""Daemon package for remote transports."""

from asky.daemon.service import XMPPDaemonService, run_xmpp_daemon_foreground

__all__ = ["XMPPDaemonService", "run_xmpp_daemon_foreground"]
