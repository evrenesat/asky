"""Platform-agnostic system tray protocol for daemon control UI."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, List, Optional


@dataclass
class TrayPluginEntry:
    """One menu item contributed by a plugin.

    ``get_label`` is called each time the menu refreshes.  Returning ``None``
    hides the item.  ``on_action`` is ``None`` for non-clickable status rows
    and a callable for clickable action rows.  ``autostart_fn``, when set, is
    invoked once by ``TrayController.autostart_if_ready()`` at tray init.
    """

    get_label: Callable[[], Optional[str]]
    on_action: Optional[Callable[[], None]] = None
    autostart_fn: Optional[Callable[[], None]] = None
    separator_after: bool = False


@dataclass
class TrayStatus:
    """View-model snapshot produced by TrayController for tray UI rendering.

    Plugin-specific state lives in ``plugin_status_entries`` and
    ``plugin_action_entries`` contributed via the ``TRAY_MENU_REGISTER`` hook.
    """

    startup_enabled: bool = False
    startup_supported: bool = False
    error_message: str = ""
    warnings: List[str] = field(default_factory=list)
    plugin_status_entries: List[TrayPluginEntry] = field(default_factory=list)
    plugin_action_entries: List[TrayPluginEntry] = field(default_factory=list)
    status_startup_label: str = "Run at login: off"
    action_startup_label: str = "Enable Run at Login"


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
