"""Cross-platform startup registration helpers for daemon mode."""

from __future__ import annotations

import logging
import platform
import sys
from dataclasses import dataclass

from asky.daemon import startup_linux, startup_macos, startup_windows

PLATFORM_DARWIN = "darwin"
PLATFORM_LINUX = "linux"
PLATFORM_WINDOWS = "windows"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StartupStatus:
    """Normalized startup status across supported platforms."""

    supported: bool
    enabled: bool
    active: bool
    platform_name: str
    details: str = ""


def _normalized_platform() -> str:
    return platform.system().strip().lower()


def build_command(*, macos_menubar_child: bool) -> list[str]:
    """Build command used by startup registration."""
    command = [sys.executable, "-m", "asky", "--xmpp-daemon"]
    if _normalized_platform() == PLATFORM_DARWIN and macos_menubar_child:
        command.append("--xmpp-menubar-child")
    logger.debug("startup build_command platform=%s command=%s", _normalized_platform(), command)
    return command


def get_status() -> StartupStatus:
    """Get startup registration status for current OS."""
    normalized = _normalized_platform()
    logger.debug("startup get_status platform=%s", normalized)
    if normalized == PLATFORM_DARWIN:
        state = startup_macos.status()
        return StartupStatus(
            supported=True,
            enabled=state.enabled,
            active=state.loaded,
            platform_name=normalized,
            details=state.details,
        )
    if normalized == PLATFORM_LINUX:
        state = startup_linux.status()
        return StartupStatus(
            supported=True,
            enabled=state.enabled,
            active=state.active,
            platform_name=normalized,
            details=state.details,
        )
    if normalized == PLATFORM_WINDOWS:
        state = startup_windows.status()
        return StartupStatus(
            supported=True,
            enabled=state.enabled,
            active=state.enabled,
            platform_name=normalized,
            details=state.details,
        )
    return StartupStatus(
        supported=False,
        enabled=False,
        active=False,
        platform_name=normalized,
        details="Unsupported platform for startup registration.",
    )


def enable_startup() -> StartupStatus:
    """Enable startup registration for current OS."""
    normalized = _normalized_platform()
    command = build_command(macos_menubar_child=True)
    logger.info("startup enable requested platform=%s", normalized)
    if normalized == PLATFORM_DARWIN:
        state = startup_macos.enable(command)
        return StartupStatus(
            supported=True,
            enabled=state.enabled,
            active=state.loaded,
            platform_name=normalized,
            details=state.details,
        )
    if normalized == PLATFORM_LINUX:
        state = startup_linux.enable(command)
        return StartupStatus(
            supported=True,
            enabled=state.enabled,
            active=state.active,
            platform_name=normalized,
            details=state.details,
        )
    if normalized == PLATFORM_WINDOWS:
        state = startup_windows.enable(command)
        return StartupStatus(
            supported=True,
            enabled=state.enabled,
            active=state.enabled,
            platform_name=normalized,
            details=state.details,
        )
    return get_status()


def disable_startup() -> StartupStatus:
    """Disable startup registration for current OS."""
    normalized = _normalized_platform()
    logger.info("startup disable requested platform=%s", normalized)
    if normalized == PLATFORM_DARWIN:
        state = startup_macos.disable()
        return StartupStatus(
            supported=True,
            enabled=state.enabled,
            active=state.loaded,
            platform_name=normalized,
            details=state.details,
        )
    if normalized == PLATFORM_LINUX:
        state = startup_linux.disable()
        return StartupStatus(
            supported=True,
            enabled=state.enabled,
            active=state.active,
            platform_name=normalized,
            details=state.details,
        )
    if normalized == PLATFORM_WINDOWS:
        state = startup_windows.disable()
        return StartupStatus(
            supported=True,
            enabled=state.enabled,
            active=state.enabled,
            platform_name=normalized,
            details=state.details,
        )
    return get_status()
