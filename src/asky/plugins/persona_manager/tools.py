"""Tool registration for persona manager plugin."""

from __future__ import annotations

from typing import Any, Callable, Dict

TOOL_IMPORT_PERSONA = "persona_import_package"
TOOL_LOAD_PERSONA = "persona_load"
TOOL_UNLOAD_PERSONA = "persona_unload"
TOOL_CURRENT_PERSONA = "persona_current"
TOOL_LIST_PERSONAS = "persona_list"


def register_persona_manager_tools(
    *,
    registry: Any,
    import_handler: Callable[[Dict[str, Any]], Dict[str, Any]],
    load_handler: Callable[[Dict[str, Any]], Dict[str, Any]],
    unload_handler: Callable[[Dict[str, Any]], Dict[str, Any]],
    current_handler: Callable[[Dict[str, Any]], Dict[str, Any]],
    list_handler: Callable[[Dict[str, Any]], Dict[str, Any]],
) -> None:
    """Register persona-manager tool surface."""
    registry.register(
        TOOL_IMPORT_PERSONA,
        {
            "name": TOOL_IMPORT_PERSONA,
            "description": "Import persona package ZIP and rebuild embeddings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "archive_path": {"type": "string"},
                },
                "required": ["archive_path"],
            },
        },
        import_handler,
    )

    registry.register(
        TOOL_LOAD_PERSONA,
        {
            "name": TOOL_LOAD_PERSONA,
            "description": "Load persona into the active session.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                },
                "required": ["name"],
            },
        },
        load_handler,
    )

    registry.register(
        TOOL_UNLOAD_PERSONA,
        {
            "name": TOOL_UNLOAD_PERSONA,
            "description": "Unload persona from the active session.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
        unload_handler,
    )

    registry.register(
        TOOL_CURRENT_PERSONA,
        {
            "name": TOOL_CURRENT_PERSONA,
            "description": "Show currently loaded persona for this session.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
        current_handler,
    )

    registry.register(
        TOOL_LIST_PERSONAS,
        {
            "name": TOOL_LIST_PERSONAS,
            "description": "List available imported personas.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
        list_handler,
    )
