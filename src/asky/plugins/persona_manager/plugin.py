"""Persona manager plugin runtime entry."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, Optional

from asky.plugins.base import AskyPlugin, PluginContext
from asky.plugins.hook_types import (
    PRE_PRELOAD,
    SESSION_RESOLVED,
    SYSTEM_PROMPT_EXTEND,
    TOOL_REGISTRY_BUILD,
    TURN_COMPLETED,
    PrePreloadContext,
    SessionResolvedContext,
    ToolRegistryBuildContext,
)
from asky.plugins.manual_persona_creator.storage import (
    get_persona_paths,
    list_persona_names,
    read_prompt,
    validate_persona_name,
)
from asky.plugins.persona_manager.importer import import_persona_archive
from asky.plugins.persona_manager.knowledge import retrieve_relevant_chunks
from asky.plugins.persona_manager.session_binding import (
    get_session_binding,
    set_session_binding,
)

SESSION_HOOK_PRIORITY = 100
TOOL_HOOK_PRIORITY = 210
PROMPT_HOOK_PRIORITY = 110
PRELOAD_HOOK_PRIORITY = 115
TURN_HOOK_PRIORITY = 400
DEFAULT_PERSONA_CONTEXT_TOP_K = 3


class PersonaManagerPlugin(AskyPlugin):
    """Imports persona packages and applies them per session."""

    def __init__(self) -> None:
        self._context: Optional[PluginContext] = None
        self._thread_local = threading.local()
        self._active_by_session: Dict[str, str] = {}

    @property
    def declared_capabilities(self) -> tuple[str, ...]:
        return ("tool_registry", "prompt", "preload", "session")

    def activate(self, context: PluginContext) -> None:
        self._context = context
        context.hook_registry.register(
            TOOL_REGISTRY_BUILD,
            self._on_tool_registry_build,
            plugin_name=context.plugin_name,
            priority=TOOL_HOOK_PRIORITY,
        )
        context.hook_registry.register(
            SESSION_RESOLVED,
            self._on_session_resolved,
            plugin_name=context.plugin_name,
            priority=SESSION_HOOK_PRIORITY,
        )
        context.hook_registry.register(
            PRE_PRELOAD,
            self._on_pre_preload,
            plugin_name=context.plugin_name,
            priority=PRELOAD_HOOK_PRIORITY,
        )
        context.hook_registry.register(
            SYSTEM_PROMPT_EXTEND,
            self._on_system_prompt_extend,
            plugin_name=context.plugin_name,
            priority=PROMPT_HOOK_PRIORITY,
        )
        context.hook_registry.register(
            TURN_COMPLETED,
            self._on_turn_completed,
            plugin_name=context.plugin_name,
            priority=TURN_HOOK_PRIORITY,
        )

    def deactivate(self) -> None:
        self._context = None
        self._active_by_session.clear()
        if hasattr(self._thread_local, "session_id"):
            delattr(self._thread_local, "session_id")

    def _on_tool_registry_build(self, payload: ToolRegistryBuildContext) -> None:
        """
        Skip tool registration - persona tools are now CLI-only.
        
        Persona management operations (load, unload, import, etc.) are now handled
        exclusively through CLI commands (e.g., 'asky persona load', 'asky persona unload')
        and @mention syntax for deterministic, user-driven control. The LLM no longer
        has access to persona management tools.
        """
        # Intentionally empty - no tools registered
        return

    def _on_session_resolved(self, payload: SessionResolvedContext) -> None:
        context = self._context
        if context is None:
            return

        session_id = self._resolve_session_id(
            session_manager=payload.session_manager,
            session_resolution=payload.session_resolution,
        )
        if session_id is None:
            if hasattr(self._thread_local, "session_id"):
                delattr(self._thread_local, "session_id")
            return

        self._thread_local.session_id = session_id
        bound_persona = get_session_binding(context.data_dir, session_id)
        if bound_persona and self._persona_exists(bound_persona):
            self._active_by_session[session_id] = bound_persona
        else:
            self._active_by_session.pop(session_id, None)

    def _on_pre_preload(self, payload: PrePreloadContext) -> None:
        context = self._context
        if context is None:
            return
        if bool(getattr(payload.request, "lean", False)):
            return

        session_id = getattr(self._thread_local, "session_id", None)
        if not session_id:
            return
        persona_name = self._active_by_session.get(str(session_id))
        if not persona_name:
            return

        query_text = str(payload.query_text or "").strip()
        if not query_text:
            return

        persona_dir = self._persona_dir(persona_name)
        top_k = int(context.config.get("knowledge_top_k", DEFAULT_PERSONA_CONTEXT_TOP_K))
        chunks = retrieve_relevant_chunks(
            persona_dir=persona_dir,
            query_text=query_text,
            top_k=top_k,
        )
        if not chunks:
            return

        snippet_lines = ["Persona knowledge context:"]
        for item in chunks:
            source = str(item.get("source", "") or "")
            score = float(item.get("score", 0.0) or 0.0)
            text = str(item.get("text", "") or "").strip()
            if not text:
                continue
            if source:
                snippet_lines.append(f"- {source} (score={score:.3f}): {text}")
            else:
                snippet_lines.append(f"- score={score:.3f}: {text}")

        persona_context = "\n".join(snippet_lines)
        existing_context = str(payload.additional_source_context or "").strip()
        if existing_context:
            payload.additional_source_context = (
                f"{existing_context}\n\n{persona_context}"
            )
        else:
            payload.additional_source_context = persona_context

    def _on_system_prompt_extend(self, system_prompt: str) -> str:
        session_id = getattr(self._thread_local, "session_id", None)
        if not session_id:
            return system_prompt

        persona_name = self._active_by_session.get(str(session_id))
        if not persona_name:
            return system_prompt

        persona_prompt = self._read_persona_prompt(persona_name)
        if not persona_prompt:
            return system_prompt

        return (
            f"{system_prompt}\n\n"
            f"Loaded Persona ({persona_name}):\n"
            f"{persona_prompt}"
        )

    def _on_turn_completed(self, _payload: Any) -> None:
        if hasattr(self._thread_local, "session_id"):
            delattr(self._thread_local, "session_id")

    def _tool_import_persona(self, args: Dict[str, Any]) -> Dict[str, Any]:
        context = self._context
        if context is None:
            return {"error": "persona manager is not active"}

        archive_path = str(args.get("archive_path", "") or "").strip()
        if not archive_path:
            return {"error": "archive_path is required"}
        try:
            return import_persona_archive(
                data_dir=context.data_dir,
                archive_path=archive_path,
            )
        except Exception as exc:
            return {"error": f"persona import failed: {exc}"}

    def _tool_load_persona(self, args: Dict[str, Any]) -> Dict[str, Any]:
        context = self._context
        if context is None:
            return {"error": "persona manager is not active"}

        try:
            persona_name = validate_persona_name(str(args.get("name", "") or ""))
        except ValueError as exc:
            return {"error": str(exc)}

        if not self._persona_exists(persona_name):
            return {"error": f"persona '{persona_name}' is not imported"}

        session_id = getattr(self._thread_local, "session_id", None)
        if not session_id:
            return {"error": "no active session; load persona within a session"}

        self._active_by_session[str(session_id)] = persona_name
        set_session_binding(
            context.data_dir,
            session_id=str(session_id),
            persona_name=persona_name,
        )
        return {"ok": True, "session_id": str(session_id), "persona": persona_name}

    def _tool_unload_persona(self, _args: Dict[str, Any]) -> Dict[str, Any]:
        context = self._context
        if context is None:
            return {"error": "persona manager is not active"}

        session_id = getattr(self._thread_local, "session_id", None)
        if not session_id:
            return {"error": "no active session"}

        removed = self._active_by_session.pop(str(session_id), None)
        set_session_binding(
            context.data_dir,
            session_id=str(session_id),
            persona_name=None,
        )
        return {
            "ok": True,
            "session_id": str(session_id),
            "removed_persona": removed,
        }

    def _tool_current_persona(self, _args: Dict[str, Any]) -> Dict[str, Any]:
        session_id = getattr(self._thread_local, "session_id", None)
        if not session_id:
            return {"session_id": None, "persona": None}

        return {
            "session_id": str(session_id),
            "persona": self._active_by_session.get(str(session_id)),
        }

    def _tool_list_personas(self, _args: Dict[str, Any]) -> Dict[str, Any]:
        context = self._context
        if context is None:
            return {"personas": []}
        return {"personas": list_persona_names(self._personas_root())}

    def _resolve_session_id(self, *, session_manager: Any, session_resolution: Any) -> Optional[str]:
        current_session = getattr(session_manager, "current_session", None)
        if current_session is not None:
            current_id = getattr(current_session, "id", None)
            if current_id is not None:
                return str(current_id)

        resolved_id = getattr(session_resolution, "session_id", None)
        if resolved_id is None:
            return None
        return str(resolved_id)

    def _personas_root(self) -> Path:
        context = self._context
        if context is None:
            return Path(".")
        return context.data_dir / "personas"

    def _persona_exists(self, persona_name: str) -> bool:
        context = self._context
        if context is None:
            return False
        try:
            paths = get_persona_paths(context.data_dir, persona_name)
        except Exception:
            return False
        return paths.metadata_path.exists() and paths.prompt_path.exists()

    def _persona_dir(self, persona_name: str) -> Path:
        context = self._context
        if context is None:
            return Path(".")
        return get_persona_paths(context.data_dir, persona_name).root_dir

    def _read_persona_prompt(self, persona_name: str) -> str:
        context = self._context
        if context is None:
            return ""
        try:
            prompt_path = get_persona_paths(context.data_dir, persona_name).prompt_path
            if not prompt_path.exists():
                return ""
            return read_prompt(prompt_path).strip()
        except Exception:
            return ""
