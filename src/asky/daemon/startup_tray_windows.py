"""Windows tray-login startup registration via Startup folder scripts."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

STARTUP_FOLDER = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
SCRIPT_FILE_NAME = "asky-tray.cmd"
SCRIPT_FILE_PATH = STARTUP_FOLDER / SCRIPT_FILE_NAME
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WindowsTrayStartupStatus:
    """State for Windows tray startup registration."""

    enabled: bool
    details: str = ""


def _script_text(program_args: list[str]) -> str:
    # Use start /min to launch minimized/backgrounded if possible
    # but for tray-child it usually doesn't show a window anyway
    exec_line = " ".join(f'"{part}"' if " " in part else part for part in program_args)
    return f'@echo off\nstart "" {exec_line}\n'


def status() -> WindowsTrayStartupStatus:
    """Inspect configured startup state."""
    exists = SCRIPT_FILE_PATH.exists()
    return WindowsTrayStartupStatus(
        enabled=exists,
        details=f"path={SCRIPT_FILE_PATH}",
    )


def enable(program_args: list[str]) -> WindowsTrayStartupStatus:
    """Write startup script."""
    logger.info("enabling windows tray startup registration")
    STARTUP_FOLDER.mkdir(parents=True, exist_ok=True)
    SCRIPT_FILE_PATH.write_text(_script_text(program_args))
    logger.debug("wrote startup script path=%s args=%s", SCRIPT_FILE_PATH, program_args)
    return status()


def disable() -> WindowsTrayStartupStatus:
    """Remove startup script."""
    logger.info("disabling windows tray startup registration")
    if SCRIPT_FILE_PATH.exists():
        SCRIPT_FILE_PATH.unlink()
        logger.debug("removed startup script path=%s", SCRIPT_FILE_PATH)
    return status()
