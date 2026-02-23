"""Daemon package for remote transports."""

from __future__ import annotations

__all__ = ["XMPPDaemonService", "run_xmpp_daemon_foreground"]


def __getattr__(name: str):
    if name in {"XMPPDaemonService", "run_xmpp_daemon_foreground"}:
        from asky.daemon.service import (
            XMPPDaemonService,
            run_xmpp_daemon_foreground,
        )

        mapping = {
            "XMPPDaemonService": XMPPDaemonService,
            "run_xmpp_daemon_foreground": run_xmpp_daemon_foreground,
        }
        return mapping[name]
    raise AttributeError(f"module 'asky.daemon' has no attribute {name!r}")
