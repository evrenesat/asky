"""Windows startup registration via Startup folder scripts."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path

STARTUP_SCRIPT_NAME = "asky-xmpp-daemon.cmd"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WindowsStartupStatus:
    """State for Windows startup registration."""

    enabled: bool
    details: str = ""


def startup_dir() -> Path:
    """Return per-user startup folder path."""
    appdata = Path.home() / "AppData" / "Roaming"
    return appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def startup_script_path() -> Path:
    """Return startup script file path."""
    return startup_dir() / STARTUP_SCRIPT_NAME


def _script_text(program_args: list[str]) -> str:
    quoted = " ".join(f'"{part}"' for part in program_args)
    return "\n".join(
        [
            "@echo off",
            "setlocal",
            f"start \"\" {quoted}",
            "endlocal",
            "",
        ]
    )


def write_startup_script(program_args: list[str]) -> Path:
    """Write startup .cmd launcher."""
    path = startup_script_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_script_text(program_args))
    logger.debug("wrote windows startup script path=%s args=%s", path, program_args)
    return path


def remove_startup_script() -> None:
    """Remove startup .cmd launcher when present."""
    path = startup_script_path()
    if path.exists():
        path.unlink()
        logger.debug("removed windows startup script path=%s", path)


def status() -> WindowsStartupStatus:
    """Inspect startup registration state."""
    path = startup_script_path()
    return WindowsStartupStatus(enabled=path.exists(), details=f"path={path}")


def enable(program_args: list[str]) -> WindowsStartupStatus:
    """Enable startup by writing .cmd script."""
    logger.info("enabling windows startup registration")
    write_startup_script(program_args)
    return status()


def disable() -> WindowsStartupStatus:
    """Disable startup by removing .cmd script."""
    logger.info("disabling windows startup registration")
    remove_startup_script()
    return status()
