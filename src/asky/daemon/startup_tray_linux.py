"""Linux tray-login startup registration via .desktop files."""

from __future__ import annotations

import logging
import shlex
from dataclasses import dataclass
from pathlib import Path

AUTOSTART_DIR = Path.home() / ".config" / "autostart"
DESKTOP_FILE_NAME = "asky-tray.desktop"
DESKTOP_FILE_PATH = AUTOSTART_DIR / DESKTOP_FILE_NAME
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LinuxTrayStartupStatus:
    """State for Linux tray startup registration."""

    enabled: bool
    details: str = ""


def _desktop_file_text(program_args: list[str]) -> str:
    exec_line = " ".join(shlex.quote(part) for part in program_args)
    return "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            "Name=Asky Tray",
            "Comment=Asky AI CLI Assistant Tray Icon",
            f"Exec={exec_line}",
            "Terminal=false",
            "Categories=Utility;",
            "X-GNOME-Autostart-enabled=true",
            "",
        ]
    )


def status() -> LinuxTrayStartupStatus:
    """Inspect configured startup state."""
    exists = DESKTOP_FILE_PATH.exists()
    return LinuxTrayStartupStatus(
        enabled=exists,
        details=f"path={DESKTOP_FILE_PATH}",
    )


def enable(program_args: list[str]) -> LinuxTrayStartupStatus:
    """Write autostart desktop file."""
    logger.info("enabling linux tray startup registration")
    AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
    DESKTOP_FILE_PATH.write_text(_desktop_file_text(program_args))
    logger.debug("wrote autostart desktop file path=%s args=%s", DESKTOP_FILE_PATH, program_args)
    return status()


def disable() -> LinuxTrayStartupStatus:
    """Remove autostart desktop file."""
    logger.info("disabling linux tray startup registration")
    if DESKTOP_FILE_PATH.exists():
        DESKTOP_FILE_PATH.unlink()
        logger.debug("removed autostart desktop file path=%s", DESKTOP_FILE_PATH)
    return status()
