"""Platform-agnostic system tray protocol for daemon control UI."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class TrayDaemonState(Enum):
    """Reported daemon lifecycle state shown in the tray UI."""

    STOPPED = "stopped"
    RUNNING = "running"
    ERROR = "error"


@dataclass
class TrayStatus:
    """Snapshot of daemon state for tray UI rendering."""

    daemon_state: TrayDaemonState = TrayDaemonState.STOPPED
    jid: str = ""
    voice_enabled: bool = False
    startup_enabled: bool = False
    startup_supported: bool = False
    error_message: str = ""


class TrayApp(ABC):
    """Protocol for a platform-specific system tray application.

    Implementations wrap a native tray library (rumps on macOS, pystray on
    Windows/Linux, etc.) and expose a uniform start/stop interface plus a
    method for pushing status updates from the daemon service thread.
    """

    @abstractmethod
    def run(self) -> None:
        """Enter the tray event loop. Blocks until the app quits."""

    @abstractmethod
    def update_status(self, status: TrayStatus) -> None:
        """Push a new status snapshot to the tray UI (thread-safe)."""
