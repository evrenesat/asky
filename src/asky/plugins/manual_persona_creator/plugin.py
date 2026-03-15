"""Manual persona creator plugin runtime entry."""

from __future__ import annotations

from typing import Optional

from asky.plugins.base import AskyPlugin, PluginContext
from asky.plugins.hook_types import (
    GUI_EXTENSION_REGISTER,
    TOOL_REGISTRY_BUILD,
    GUIExtensionRegisterContext,
    GUIPageSpec,
    ToolRegistryBuildContext,
)

TOOL_REGISTRATION_PRIORITY = 200


class ManualPersonaCreatorPlugin(AskyPlugin):
    """Registers manual persona creation and export tools."""

    def __init__(self) -> None:
        self._context: Optional[PluginContext] = None

    @property
    def declared_capabilities(self) -> tuple[str, ...]:
        return ("tool_registry", "preload", "prompt", "gui_extension")

    def activate(self, context: PluginContext) -> None:
        self._context = context
        context.hook_registry.register(
            TOOL_REGISTRY_BUILD,
            self._on_tool_registry_build,
            plugin_name=context.plugin_name,
            priority=TOOL_REGISTRATION_PRIORITY,
        )
        context.hook_registry.register(
            GUI_EXTENSION_REGISTER,
            self._on_gui_extension_register,
            plugin_name=context.plugin_name,
        )

    def deactivate(self) -> None:
        self._context = None

    def _on_gui_extension_register(self, payload: GUIExtensionRegisterContext) -> None:
        context = self._context
        if context is None:
            return

        from asky.plugins.gui_server.pages.personas import register_persona_pages
        from asky.plugins.gui_server.pages.web_review import register_web_review_pages

        register_persona_pages(payload.register_page, context.data_dir, payload.queue)
        register_web_review_pages(payload.register_page, context.data_dir)

        # Register job handlers
        from asky.plugins.manual_persona_creator.book_service import run_ingestion_job
        from asky.plugins.manual_persona_creator.source_service import run_source_job

        payload.register_job_handler(
            "authored_book_ingest",
            lambda job_id, **kw: run_ingestion_job(
                data_dir=context.data_dir,
                persona_name=kw.get("persona_name"),
                job_id=job_id,
            ),
        )
        payload.register_job_handler(
            "source_ingest",
            lambda job_id, **kw: run_source_job(
                data_dir=context.data_dir,
                persona_name=kw.get("persona_name"),
                job_id=job_id,
            ),
        )

    def _on_tool_registry_build(self, payload: ToolRegistryBuildContext) -> None:
        """
        Skip tool registration - persona tools are now CLI-only.
        
        Persona creation and management operations are now handled exclusively
        through CLI commands (e.g., 'asky persona create', 'asky persona load')
        to provide deterministic, user-driven control. The LLM no longer has
        access to persona management tools.
        """
        # Intentionally empty - no tools registered
        return
