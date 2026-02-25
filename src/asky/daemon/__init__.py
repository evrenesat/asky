"""Daemon package for remote transports."""

from __future__ import annotations

__all__ = ["DaemonService", "run_daemon_foreground"]


def __getattr__(name: str):
    if name in {"DaemonService", "run_daemon_foreground"}:
        from asky.daemon.service import DaemonService, run_daemon_foreground

        mapping = {
            "DaemonService": DaemonService,
            "run_daemon_foreground": run_daemon_foreground,
        }
        return mapping[name]
    raise AttributeError(f"module 'asky.daemon' has no attribute {name!r}")
