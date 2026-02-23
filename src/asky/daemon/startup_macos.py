"""macOS startup registration via LaunchAgents."""

from __future__ import annotations

import logging
import os
import plistlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

LAUNCH_AGENT_LABEL = "com.evren.asky.menubar"
LAUNCH_AGENT_PATH = (
    Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"
)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MacStartupStatus:
    """State for macOS LaunchAgent registration."""

    enabled: bool
    loaded: bool
    details: str = ""


def _launchctl_domain() -> str:
    return f"gui/{os.getuid()}"


def _run_launchctl(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    logger.debug("launchctl command args=%s check=%s", args, check)
    return subprocess.run(
        ["launchctl", *args],
        capture_output=True,
        text=True,
        check=check,
    )


def build_plist(program_args: list[str]) -> dict:
    """Build LaunchAgent plist payload."""
    return {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": list(program_args),
        "RunAtLoad": True,
        "KeepAlive": False,
        "StandardOutPath": str(Path.home() / ".config" / "asky" / "logs" / "menubar.out.log"),
        "StandardErrorPath": str(Path.home() / ".config" / "asky" / "logs" / "menubar.err.log"),
    }


def write_plist(program_args: list[str]) -> Path:
    """Write LaunchAgent plist to disk."""
    LAUNCH_AGENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    plist_payload = build_plist(program_args)
    with LAUNCH_AGENT_PATH.open("wb") as handle:
        plistlib.dump(plist_payload, handle)
    logger.debug("wrote launchagent plist path=%s args=%s", LAUNCH_AGENT_PATH, program_args)
    return LAUNCH_AGENT_PATH


def remove_plist() -> None:
    """Delete LaunchAgent plist when present."""
    if LAUNCH_AGENT_PATH.exists():
        LAUNCH_AGENT_PATH.unlink()
        logger.debug("removed launchagent plist path=%s", LAUNCH_AGENT_PATH)


def is_loaded() -> bool:
    """Return whether launchd currently has this label loaded."""
    try:
        result = _run_launchctl("list")
    except FileNotFoundError:
        return False
    if result.returncode != 0:
        return False
    return LAUNCH_AGENT_LABEL in (result.stdout or "")


def status() -> MacStartupStatus:
    """Inspect configured + loaded startup state."""
    exists = LAUNCH_AGENT_PATH.exists()
    loaded = is_loaded()
    return MacStartupStatus(
        enabled=exists,
        loaded=loaded,
        details=f"path={LAUNCH_AGENT_PATH}",
    )


def enable(program_args: list[str]) -> MacStartupStatus:
    """Write plist and bootstrap it into launchd."""
    logger.info("enabling macos startup registration")
    write_plist(program_args)
    domain = _launchctl_domain()
    try:
        _run_launchctl("bootout", domain, str(LAUNCH_AGENT_PATH))
    except FileNotFoundError as exc:
        return MacStartupStatus(enabled=False, loaded=False, details=str(exc))
    try:
        _run_launchctl("bootstrap", domain, str(LAUNCH_AGENT_PATH), check=True)
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or str(exc)).strip()
        logger.warning("launchctl bootstrap failed: %s", details)
        return MacStartupStatus(enabled=True, loaded=False, details=details)
    logger.info("macos startup registration enabled")
    return status()


def disable() -> MacStartupStatus:
    """Unload and remove LaunchAgent registration."""
    logger.info("disabling macos startup registration")
    domain = _launchctl_domain()
    try:
        _run_launchctl("bootout", domain, str(LAUNCH_AGENT_PATH))
    except FileNotFoundError as exc:
        remove_plist()
        return MacStartupStatus(enabled=False, loaded=False, details=str(exc))
    remove_plist()
    logger.info("macos startup registration disabled")
    return status()
