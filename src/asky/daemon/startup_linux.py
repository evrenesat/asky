"""Linux startup registration via systemd user services."""

from __future__ import annotations

import logging
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

SYSTEMD_USER_SERVICE_NAME = "asky-xmpp-daemon.service"
SYSTEMD_USER_SERVICE_PATH = (
    Path.home() / ".config" / "systemd" / "user" / SYSTEMD_USER_SERVICE_NAME
)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LinuxStartupStatus:
    """State for Linux startup registration."""

    enabled: bool
    active: bool
    details: str = ""


def _run_systemctl(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    logger.debug("systemctl --user args=%s check=%s", args, check)
    return subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _unit_text(program_args: list[str]) -> str:
    exec_start = " ".join(shlex.quote(part) for part in program_args)
    return "\n".join(
        [
            "[Unit]",
            "Description=asky XMPP daemon",
            "",
            "[Service]",
            "Type=simple",
            f"ExecStart={exec_start}",
            "Restart=on-failure",
            "RestartSec=5",
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        ]
    )


def write_unit(program_args: list[str]) -> Path:
    """Write user systemd unit file."""
    SYSTEMD_USER_SERVICE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SYSTEMD_USER_SERVICE_PATH.write_text(_unit_text(program_args))
    logger.debug("wrote systemd user unit path=%s args=%s", SYSTEMD_USER_SERVICE_PATH, program_args)
    return SYSTEMD_USER_SERVICE_PATH


def remove_unit() -> None:
    """Remove unit file when present."""
    if SYSTEMD_USER_SERVICE_PATH.exists():
        SYSTEMD_USER_SERVICE_PATH.unlink()
        logger.debug("removed systemd user unit path=%s", SYSTEMD_USER_SERVICE_PATH)


def status() -> LinuxStartupStatus:
    """Inspect configured + active startup state."""
    exists = SYSTEMD_USER_SERVICE_PATH.exists()
    try:
        enabled_result = _run_systemctl("is-enabled", SYSTEMD_USER_SERVICE_NAME)
        active_result = _run_systemctl("is-active", SYSTEMD_USER_SERVICE_NAME)
    except FileNotFoundError as exc:
        return LinuxStartupStatus(enabled=False, active=False, details=str(exc))

    enabled = exists and enabled_result.returncode == 0
    active = active_result.returncode == 0
    details = ""
    if enabled_result.returncode != 0:
        details = (enabled_result.stderr or enabled_result.stdout or "").strip()
    return LinuxStartupStatus(enabled=enabled, active=active, details=details)


def enable(program_args: list[str]) -> LinuxStartupStatus:
    """Install and enable user service."""
    logger.info("enabling linux startup registration")
    write_unit(program_args)
    try:
        _run_systemctl("daemon-reload", check=True)
        _run_systemctl("enable", "--now", SYSTEMD_USER_SERVICE_NAME, check=True)
    except FileNotFoundError as exc:
        return LinuxStartupStatus(enabled=False, active=False, details=str(exc))
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or str(exc)).strip()
        logger.warning("linux startup enable failed: %s", details)
        return LinuxStartupStatus(enabled=True, active=False, details=details)
    logger.info("linux startup registration enabled")
    return status()


def disable() -> LinuxStartupStatus:
    """Disable and uninstall user service."""
    logger.info("disabling linux startup registration")
    details = ""
    try:
        _run_systemctl("disable", "--now", SYSTEMD_USER_SERVICE_NAME)
        _run_systemctl("daemon-reload")
    except FileNotFoundError as exc:
        details = str(exc)
    remove_unit()
    current = status()
    logger.info(
        "linux startup registration disabled enabled=%s active=%s details=%s",
        current.enabled,
        current.active,
        current.details,
    )
    if details and not current.details:
        return LinuxStartupStatus(
            enabled=current.enabled,
            active=current.active,
            details=details,
        )
    return current
