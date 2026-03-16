"""Daemon launch resolution and background spawn helpers."""

import logging
import platform
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DAEMON_BACKGROUND_LOG_FILE = "~/.config/asky/logs/daemon-background.log"

class LaunchMode(Enum):
    """Execution mode for the daemon."""
    FOREGROUND = auto()
    BACKGROUND_HEADLESS = auto()
    BACKGROUND_TRAY = auto()


@dataclass
class DaemonLaunchNotice:
    log_path: Path
    pid: Optional[int]
    mode: LaunchMode
    gui_url: Optional[str] = None
    gui_warning: Optional[str] = None


def build_launch_notice(mode: LaunchMode, pid: Optional[int], log_path: Path) -> DaemonLaunchNotice:
    from asky.plugins.runtime import get_or_create_plugin_runtime
    import os
    
    gui_url = None
    gui_warning = None
    
    runtime = get_or_create_plugin_runtime()
    if runtime and runtime.manager.is_active("gui_server"):
        context = runtime.manager._contexts.get("gui_server")
        if context:
            config = context.config
            password = config.get("password") or os.environ.get("ASKY_GUI_PASSWORD")
            if password:
                host = config.get("host", "127.0.0.1")
                port = config.get("port", 8766)
                gui_url = f"http://{host}:{port}/"
            else:
                gui_warning = "GUI password is not configured and ASKY_GUI_PASSWORD is not set. GUI server will not start in an insecure state."

    return DaemonLaunchNotice(
        log_path=log_path,
        pid=pid,
        mode=mode,
        gui_url=gui_url,
        gui_warning=gui_warning,
    )


def print_launch_notice(notice: DaemonLaunchNotice) -> None:
    print(f"Asky Daemon launched in {notice.mode.name} mode.")
    if notice.pid is not None:
        print(f"PID: {notice.pid}")
    print(f"Logs: {notice.log_path}")
    if notice.gui_url:
        print(f"Web Admin: {notice.gui_url}")
    if notice.gui_warning:
        print(f"Warning: {notice.gui_warning}")


def resolve_launch_mode(
    is_foreground: bool,
    is_no_tray: bool,
    is_legacy_double_verbose: bool,
) -> LaunchMode:
    """Resolve the daemon launch mode based on explicit flags and platform support."""
    if is_foreground or is_legacy_double_verbose:
        return LaunchMode.FOREGROUND

    is_macos = platform.system().lower() == "darwin"
    
    if is_macos and not is_no_tray:
        try:
            from asky.daemon.menubar import has_rumps
            if has_rumps():
                return LaunchMode.BACKGROUND_TRAY
        except ImportError:
            pass
            
    return LaunchMode.BACKGROUND_HEADLESS


def spawn_background_child(
    mode: LaunchMode,
    verbose: bool = False,
    double_verbose: bool = False,
) -> None:
    """Spawn the daemon as a detached background child process."""
    if mode == LaunchMode.FOREGROUND:
        raise ValueError("Cannot spawn a foreground process via background spawn helper")

    command = [sys.executable, "-m", "asky", "--xmpp-daemon"]

    if mode == LaunchMode.BACKGROUND_TRAY:
        command.append("--xmpp-menubar-child")
    else:
        command.append("--foreground")

    if double_verbose:
        command.append("-vv")
    elif verbose:
        command.append("-v")

    kwargs = {
        "start_new_session": True,
        "stdin": subprocess.DEVNULL,
    }

    if platform.system().lower() == "windows":
        # 0x00000008 = DETACHED_PROCESS
        # 0x08000000 = CREATE_NO_WINDOW
        kwargs["creationflags"] = 0x00000008 | 0x08000000

    log_path = Path(DAEMON_BACKGROUND_LOG_FILE).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("a")
    
    kwargs["stdout"] = log_file
    kwargs["stderr"] = log_file

    logger.debug("spawning background child command=%s mode=%s", command, mode)
    proc = subprocess.Popen(command, **kwargs)
    
    notice = build_launch_notice(mode=mode, pid=proc.pid, log_path=log_path.parent)
    print_launch_notice(notice)
    
    logger.info("background child spawned successfully. check logs at %s", log_path)

