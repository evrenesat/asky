"""Base plugin contracts."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from asky.plugins.hooks import HookRegistry


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

    @property
    def declared_capabilities(self) -> tuple[str, ...]:
        """Optional capability declarations used for diagnostics only."""
        return ()

    @property
    def name(self) -> Optional[str]:
        """Optional explicit plugin name override."""
        return None
