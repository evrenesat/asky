"""Voice transcriber plugin."""

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

from .service import VoiceTranscriberService

logger = logging.getLogger(__name__)


class VoiceTranscriberPlugin(AskyPlugin):
    """Plugin providing voice transcription capabilities and tools."""

    def __init__(self, context: Optional[PluginContext] = None):
        self.service: Optional[VoiceTranscriberService] = None
        self.tools_enabled = True
        self.ingestion_enabled = True
        if context:
            self.activate(context)

    @property
    def declared_capabilities(self) -> tuple[str, ...]:
        return ("capability", "local_source_handler", "tool_registry")

    def activate(self, context: PluginContext) -> None:
        """Activate the plugin."""
        cfg = context.config.get("voice_transcriber", {})
        self.service = VoiceTranscriberService(
            model=cfg.get("model", "mlx-community/whisper-turbo-mlx"),
            language=cfg.get("language", ""),
            max_size_mb=cfg.get("max_size_mb", 500),
            allowed_mime_types=cfg.get("allowed_mime_types", []),
            hf_token=cfg.get("hf_token", ""),
            hf_token_env=cfg.get("hf_token_env", "HF_TOKEN"),
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
        context.capabilities["voice_transcriber"] = self.service

    def on_local_source_handler_register(
        self, context: LocalSourceHandlerRegisterContext
    ) -> None:
        """Register audio file handlers for corpus ingestion."""
        if not self.ingestion_enabled:
            return

        extensions = [".m4a", ".mp3", ".wav", ".webm", ".ogg", ".flac", ".opus"]
        context.handlers.append(
            LocalSourceHandlerSpec(
                extensions=extensions,
                read=self._read_audio_file,
                mime="audio/mpeg",  # Generic audio mime for ingestion
            )
        )

    def on_tray_menu_register(self, context: TrayMenuRegisterContext) -> None:
        """Contribute voice items to the tray menu."""
        from asky.daemon.tray_protocol import TrayPluginEntry

        context.status_entries.append(TrayPluginEntry(get_label=lambda: "Voice: active"))

    def on_tool_registry_build(self, context: ToolRegistryBuildContext) -> None:
        """Register the transcribe_audio_url tool."""
        if not self.tools_enabled:
            return

        if "transcribe_audio_url" in context.disabled_tools:
            return

        context.registry.register(
            "transcribe_audio_url",
            {
                "name": "transcribe_audio_url",
                "description": (
                    "Transcribe an audio file from a public HTTPS URL to text. "
                    "Supports common formats like MP3, M4A, WAV, WebM, OGG."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The public HTTPS URL of the audio file.",
                        },
                        "prompt": {
                            "type": "string",
                            "description": "Optional initial prompt to guide transcription (e.g. spelling of names).",
                        },
                        "language": {
                            "type": "string",
                            "description": "Optional ISO 639-1 language code (e.g. 'en', 'fr').",
                        },
                    },
                    "required": ["url"],
                },
            },
            lambda args: self.transcribe_audio_url_tool(
                url=str(args.get("url", "")),
                prompt=args.get("prompt"),
                language=args.get("language"),
            ),
        )

    def transcribe_audio_url_tool(
        self,
        url: str,
        prompt: Optional[str] = None,
        language: Optional[str] = None,
    ) -> Dict[str, Any]:
        """LLM-callable tool for audio transcription."""
        if not url.lower().startswith("https://"):
            return {
                "error": "Security Policy: Only public HTTPS URLs are supported for model-initiated transcription."
            }

        with tempfile.TemporaryDirectory() as tmp:
            target_path = Path(tmp) / "downloaded_audio"
            try:
                text = self.service.strategy.transcribe(
                    self.service.download_audio(url, target_path),
                    model=self.service.model,
                    language=language or self.service.language,
                    hf_token=self.service.hf_token,
                    hf_token_env=self.service.hf_token_env,
                )
                return {
                    "status": "success",
                    "transcript": text,
                    "url": url,
                }
            except Exception as exc:
                logger.exception("transcribe_audio_url tool failed")
                return {"error": str(exc)}

    def _read_audio_file(self, path: str) -> LocalSourcePayload:
        """Handler for local audio file ingestion."""
        file_path = Path(path)
        try:
            text = self.service.strategy.transcribe(
                file_path,
                model=self.service.model,
                language=self.service.language,
                hf_token=self.service.hf_token,
                hf_token_env=self.service.hf_token_env,
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
