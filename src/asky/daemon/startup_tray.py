"""Cross-platform tray-login startup registration helpers."""

from __future__ import annotations

import logging
import platform
import sys
from dataclasses import dataclass

from asky.daemon import startup_tray_linux, startup_tray_macos, startup_tray_windows

PLATFORM_DARWIN = "darwin"
PLATFORM_LINUX = "linux"
PLATFORM_WINDOWS = "windows"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrayStartupStatus:
    """Normalized tray startup status across supported platforms."""

    supported: bool
    enabled: bool
    active: bool
    platform_name: str
    details: str = ""


def _normalized_platform() -> str:
    return platform.system().strip().lower()


def build_tray_command() -> list[str]:
    """Build command used by tray-login startup registration."""
    # Tray auto-start always uses the tray-child flag
    return [sys.executable, "-m", "asky", "--daemon", "--tray-child"]


def get_status() -> TrayStartupStatus:
    """Get tray startup registration status for current OS."""
    normalized = _normalized_platform()
    logger.debug("tray startup get_status platform=%s", normalized)
    
    if normalized == PLATFORM_DARWIN:
        state = startup_tray_macos.status()
        return TrayStartupStatus(
            supported=True,
            enabled=state.enabled,
            active=state.loaded,
            platform_name=normalized,
            details=state.details,
        )
    if normalized == PLATFORM_LINUX:
        state = startup_tray_linux.status()
        return TrayStartupStatus(
            supported=True,
            enabled=state.enabled,
            active=state.enabled,
            platform_name=normalized,
            details=state.details,
        )
    if normalized == PLATFORM_WINDOWS:
        state = startup_tray_windows.status()
        return TrayStartupStatus(
            supported=True,
            enabled=state.enabled,
            active=state.enabled,
            platform_name=normalized,
            details=state.details,
        )
        
    return TrayStartupStatus(
        supported=False,
        enabled=False,
        active=False,
        platform_name=normalized,
        details="Unsupported platform for tray startup registration.",
    )


def enable_startup() -> TrayStartupStatus:
    """Enable tray startup registration for current OS."""
    normalized = _normalized_platform()
    command = build_tray_command()
    logger.info("tray startup enable requested platform=%s", normalized)
    
    # Best-effort disable headless startup to avoid conflicts
    try:
        from asky.daemon import startup
        startup.disable_startup()
    except Exception:
        logger.debug("failed to disable headless startup while enabling tray startup", exc_info=True)

    if normalized == PLATFORM_DARWIN:
        state = startup_tray_macos.enable(command)
        return TrayStartupStatus(
            supported=True,
            enabled=state.enabled,
            active=state.loaded,
            platform_name=normalized,
            details=state.details,
        )
    if normalized == PLATFORM_LINUX:
        state = startup_tray_linux.enable(command)
        return TrayStartupStatus(
            supported=True,
            enabled=state.enabled,
            active=state.enabled,
            platform_name=normalized,
            details=state.details,
        )
    if normalized == PLATFORM_WINDOWS:
        state = startup_tray_windows.enable(command)
        return TrayStartupStatus(
            supported=True,
            enabled=state.enabled,
            active=state.enabled,
            platform_name=normalized,
            details=state.details,
        )
    return get_status()


def disable_startup() -> TrayStartupStatus:
    """Disable tray startup registration for current OS."""
    normalized = _normalized_platform()
    logger.info("tray startup disable requested platform=%s", normalized)
    
    if normalized == PLATFORM_DARWIN:
        state = startup_tray_macos.disable()
        return TrayStartupStatus(
            supported=True,
            enabled=state.enabled,
            active=state.loaded,
            platform_name=normalized,
            details=state.details,
        )
    if normalized == PLATFORM_LINUX:
        state = startup_tray_linux.disable()
        return TrayStartupStatus(
            supported=True,
            enabled=state.enabled,
            active=state.enabled,
            platform_name=normalized,
            details=state.details,
        )
    if normalized == PLATFORM_WINDOWS:
        state = startup_tray_windows.disable()
        return TrayStartupStatus(
            supported=True,
            enabled=state.enabled,
            active=state.enabled,
            platform_name=normalized,
            details=state.details,
        )
    return get_status()
