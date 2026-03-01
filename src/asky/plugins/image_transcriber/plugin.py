"""Image transcriber plugin."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from asky.plugins import (
    AskyPlugin,
    LocalSourceHandlerRegisterContext,
    LocalSourceHandlerSpec,
    PluginCapabilityRegisterContext,
    PluginContext,
    ToolRegistryBuildContext,
    TRAY_MENU_REGISTER,
    TrayMenuRegisterContext,
)
from asky.research.adapters import LocalSourcePayload

from .service import ImageTranscriberService

logger = logging.getLogger(__name__)


class ImageTranscriberPlugin(AskyPlugin):
    """Plugin providing image transcription (captioning) capabilities and tools."""

    def __init__(self, context: Optional[PluginContext] = None):
        self.service: Optional[ImageTranscriberService] = None
        self.tools_enabled = True
        self.ingestion_enabled = True
        if context:
            self.activate(context)

    @property
    def declared_capabilities(self) -> tuple[str, ...]:
        return ("capability", "local_source_handler", "tool_registry")

    def activate(self, context: PluginContext) -> None:
        """Activate the plugin."""
        cfg = context.config.get("image_transcriber", {})
        self.service = ImageTranscriberService(
            model_alias=cfg.get("model_alias", ""),
            prompt_text=cfg.get("prompt_text", "Explain this image briefly."),
            max_size_mb=cfg.get("max_size_mb", 20),
            allowed_mime_types=cfg.get("allowed_mime_types", []),
            preferred_workers=cfg.get("workers", 1),
        )
        self.tools_enabled = bool(cfg.get("tools_enabled", True))
        self.ingestion_enabled = bool(cfg.get("ingestion_enabled", True))
        
        context.hook_registry.register(
            TRAY_MENU_REGISTER,
            self.on_tray_menu_register,
            plugin_name=context.plugin_name,
        )
        from asky.plugins.hook_types import (
            PLUGIN_CAPABILITY_REGISTER,
            LOCAL_SOURCE_HANDLER_REGISTER,
            TOOL_REGISTRY_BUILD,
        )
        context.hook_registry.register(
            PLUGIN_CAPABILITY_REGISTER,
            self.on_plugin_capability_register,
            plugin_name=context.plugin_name,
        )
        context.hook_registry.register(
            LOCAL_SOURCE_HANDLER_REGISTER,
            self.on_local_source_handler_register,
            plugin_name=context.plugin_name,
        )
        context.hook_registry.register(
            TOOL_REGISTRY_BUILD,
            self.on_tool_registry_build,
            plugin_name=context.plugin_name,
        )

    def deactivate(self) -> None:
        """Deactivate the plugin."""
        self.service = None

    def on_plugin_capability_register(self, context: PluginCapabilityRegisterContext) -> None:
        """Expose the transcriber service to other plugins."""
        context.capabilities["image_transcriber"] = self.service

    def on_local_source_handler_register(
        self, context: LocalSourceHandlerRegisterContext
    ) -> None:
        """Register image file handlers for corpus ingestion."""
        if not self.ingestion_enabled:
            return

        extensions = [".jpg", ".jpeg", ".png", ".webp", ".gif"]
        context.handlers.append(
            LocalSourceHandlerSpec(
                extensions=extensions,
                read=self._read_image_file,
                mime="image/jpeg",
            )
        )

    def on_tray_menu_register(self, context: TrayMenuRegisterContext) -> None:
        """Contribute image items to the tray menu."""
        from asky.daemon.tray_protocol import TrayPluginEntry

        context.status_entries.append(TrayPluginEntry(get_label=lambda: "Image: active"))

    def on_tool_registry_build(self, context: ToolRegistryBuildContext) -> None:
        """Register the transcribe_image_url tool."""
        if not self.tools_enabled:
            return

        if "transcribe_image_url" in context.disabled_tools:
            return

        context.registry.register(
            name="transcribe_image_url",
            func=self.transcribe_image_url_tool,
            description=(
                "Describe or transcribe an image from a public HTTPS URL. "
                "Supports formats like PNG, JPEG, WEBP, GIF."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The public HTTPS URL of the image file.",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Optional specific question or prompt about the image.",
                    },
                },
                "required": ["url"],
            },
        )

    def transcribe_image_url_tool(
        self,
        url: str,
        prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """LLM-callable tool for image transcription."""
        if not url.lower().startswith("https://"):
            return {
                "error": "Security Policy: Only public HTTPS URLs are supported for model-initiated transcription."
            }

        with tempfile.TemporaryDirectory() as tmp:
            target_path = Path(tmp) / "downloaded_image"
            try:
                text = self.service.transcribe_url(url, target_path, prompt=prompt)
                return {
                    "status": "success",
                    "description": text,
                    "url": url,
                }
            except Exception as exc:
                logger.exception("transcribe_image_url tool failed")
                return {"error": str(exc)}

    def _read_image_file(self, path: str) -> LocalSourcePayload:
        """Handler for local image file ingestion."""
        file_path = Path(path)
        try:
            # For ingestion, we use the default prompt
            text = self.service.transcribe_file(
                file_path,
                mime_type=self.service._resolve_mime("", "", file_path)
            )
            return LocalSourcePayload(
                content=text,
                title=file_path.name,
                resolved_target=f"local://{file_path.resolve().as_posix()}",
            )
        except Exception as exc:
            return LocalSourcePayload(
                content="",
                title=file_path.name,
                error=str(exc),
            )
