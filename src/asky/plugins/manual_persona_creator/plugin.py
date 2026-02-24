"""Manual persona creator plugin runtime entry."""

from __future__ import annotations

from typing import Optional

from asky.plugins.base import AskyPlugin, PluginContext
from asky.plugins.hook_types import TOOL_REGISTRY_BUILD, ToolRegistryBuildContext
from asky.plugins.manual_persona_creator.tools import register_manual_persona_tools

TOOL_REGISTRATION_PRIORITY = 200


class ManualPersonaCreatorPlugin(AskyPlugin):
    """Registers manual persona creation and export tools."""

    def __init__(self) -> None:
        self._context: Optional[PluginContext] = None

    @property
    def declared_capabilities(self) -> tuple[str, ...]:
        return ("tool_registry", "preload", "prompt")

    def activate(self, context: PluginContext) -> None:
        self._context = context
        context.hook_registry.register(
            TOOL_REGISTRY_BUILD,
            self._on_tool_registry_build,
            plugin_name=context.plugin_name,
            priority=TOOL_REGISTRATION_PRIORITY,
        )

    def deactivate(self) -> None:
        self._context = None

    def _on_tool_registry_build(self, payload: ToolRegistryBuildContext) -> None:
        context = self._context
        if context is None:
            return
        register_manual_persona_tools(
            registry=payload.registry,
            data_dir=context.data_dir,
            plugin_config=dict(context.config),
        )
