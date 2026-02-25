"""Launch context for the daemon process.

Tracks how the process was started so components can adapt behaviour
(e.g. skip interactive prompts in non-interactive contexts).
"""

from __future__ import annotations

from enum import Enum


class LaunchContext(Enum):
    INTERACTIVE_CLI = "interactive_cli"
    DAEMON_FOREGROUND = "daemon_foreground"
    MACOS_APP = "macos_app"


_current: LaunchContext = LaunchContext.INTERACTIVE_CLI


def set_launch_context(ctx: LaunchContext) -> None:
    global _current
    _current = ctx


def get_launch_context() -> LaunchContext:
    return _current


def is_interactive() -> bool:
    return _current == LaunchContext.INTERACTIVE_CLI
