"""Base plugin contracts."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from asky.plugins.hooks import HookRegistry


class CapabilityCategory:
    """String constants for CLI argument group categories."""

    OUTPUT_DELIVERY = "output_delivery"
    SESSION_CONTROL = "session_control"
    BROWSER_SETUP = "browser_setup"
    BACKGROUND_SERVICE = "background_service"


CATEGORY_LABELS: dict[str, tuple[str, str]] = {
    CapabilityCategory.OUTPUT_DELIVERY: (
        "Output Delivery",
        "Actions applied to the final answer after a query completes"
        " (e.g., send by email, push to an endpoint, open in browser).",
    ),
    CapabilityCategory.SESSION_CONTROL: (
        "Session & Query",
        "Control how sessions and queries behave."
        " Settings that persist across turns in the current session.",
    ),
    CapabilityCategory.BROWSER_SETUP: (
        "Browser Setup",
        "Configure and authenticate the retrieval browser"
        " for sites that require login or anti-bot handling.",
    ),
    CapabilityCategory.BACKGROUND_SERVICE: (
        "Background Services",
        "Start and manage background daemon processes.",
    ),
}


@dataclass(frozen=True)
class CLIContribution:
    """Describes one argparse argument contributed by a plugin."""

    category: str
    flags: tuple[str, ...]
    kwargs: dict[str, Any]


@dataclass(frozen=True)
class CLIHintContext:
    """Context passed to plugins when collecting static inline hints."""

    parsed_args: Any  # argparse.Namespace
    phase: str  # "pre_dispatch"


@dataclass(frozen=True)
class CLIHint:
    """Describes an inline operational hint to be shown to the user."""

    id: str
    message: str
    priority: int = 100
    frequency: str = "per_invocation"  # "per_invocation" or "per_session"
    channel: str = "cli_stdout"


@dataclass(frozen=True)
class PluginContext:
    """Activation context passed to plugin instances."""

    plugin_name: str
    config_dir: Path
    data_dir: Path
    config: Mapping[str, Any]
    hook_registry: "HookRegistry"
    logger: logging.Logger


@dataclass
class PluginStatus:
    """Runtime status for one plugin."""

    name: str
    enabled: bool
    module: str = ""
    plugin_class: str = ""
    state: str = "pending"
    message: str = ""
    active: bool = False
    dependencies: tuple[str, ...] = field(default_factory=tuple)


class AskyPlugin(ABC):
    """Abstract plugin interface."""

    @abstractmethod
    def activate(self, context: PluginContext) -> None:
        """Activate plugin runtime behavior."""

    def deactivate(self) -> None:
        """Deactivate plugin runtime behavior."""
        return None

    @classmethod
    def get_cli_contributions(cls) -> list[CLIContribution]:
        """Return CLI flags this plugin wants to expose.

        Called before activation to collect argparse arguments. Plugins override
        this to contribute flags to named argparse groups in the CLI.
        """
        return []

    @classmethod
    def get_cli_hint_contributions(cls, context: CLIHintContext) -> list[CLIHint]:
        """Return static inline hints this plugin wants to expose.
        
        Called before dispatch to provide situational guidance based on parsed flags.
        """
        return []

    @property
    def declared_capabilities(self) -> tuple[str, ...]:
        """Optional capability declarations used for diagnostics only."""
        return ()

    @property
    def name(self) -> Optional[str]:
        """Optional explicit plugin name override."""
        return None
