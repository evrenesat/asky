"""LLM tool definition and executor for save_memory."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from asky.config import (
    DB_PATH,
    RESEARCH_CHROMA_PERSIST_DIRECTORY,
    USER_MEMORY_CHROMA_COLLECTION,
    USER_MEMORY_DEDUP_THRESHOLD,
)

logger = logging.getLogger(__name__)

MEMORY_TOOL_SCHEMA: Dict[str, Any] = {
    "name": "save_memory",
    "description": (
        "Save an important fact about the user or their preferences to long-term memory. "
        "Use when the user explicitly asks to remember something or shares a persistent preference."
    ),
    "system_prompt_guideline": (
        "When the user says 'remember this', 'keep in mind', 'don't forget', or shares a persistent "
        "preference or personal fact, call save_memory. Do not save ephemeral request-specific information."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "memory": {
                "type": "string",
                "description": "The fact, preference, or context to remember",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional tags for categorization (e.g. ['preference', 'personal'])",
            },
            # session_id is injected by the tool executor if available, not by the LLM
        },
        "required": ["memory"],
    },
}


def execute_save_memory(args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute the save_memory tool: dedup check, then insert or update."""
    from asky.memory.store import save_memory as db_save_memory
    from asky.memory.store import update_memory as db_update_memory
    from asky.memory.vector_ops import find_near_duplicate, store_memory_embedding

    memory_text = args.get("memory", "")
    tags: List[str] = args.get("tags") or []
    session_id: Optional[int] = args.get("session_id")  # Injected by ToolRegistry

    if not memory_text or not memory_text.strip():
        return {"status": "error", "error": "memory text must be non-empty"}

    memory_text = memory_text.strip()

    try:
        existing_id = find_near_duplicate(
            db_path=DB_PATH,
            chroma_dir=RESEARCH_CHROMA_PERSIST_DIRECTORY,
            text=memory_text,
            threshold=USER_MEMORY_DEDUP_THRESHOLD,
            collection_name=USER_MEMORY_CHROMA_COLLECTION,
            session_id=session_id,
        )

        if existing_id is not None:
            # We assume updates don't change session ownership
            db_update_memory(DB_PATH, existing_id, memory_text, tags)
            store_memory_embedding(
                db_path=DB_PATH,
                chroma_dir=RESEARCH_CHROMA_PERSIST_DIRECTORY,
                memory_id=existing_id,
                text=memory_text,
                collection_name=USER_MEMORY_CHROMA_COLLECTION,
                session_id=session_id,
            )
            return {
                "status": "updated",
                "memory_id": existing_id,
                "deduplicated": True,
            }

        memory_id = db_save_memory(DB_PATH, memory_text, tags, session_id=session_id)
        store_memory_embedding(
            db_path=DB_PATH,
            chroma_dir=RESEARCH_CHROMA_PERSIST_DIRECTORY,
            memory_id=memory_id,
            text=memory_text,
            collection_name=USER_MEMORY_CHROMA_COLLECTION,
            session_id=session_id,
        )
        return {"status": "saved", "memory_id": memory_id, "deduplicated": False}

    except Exception as exc:
        logger.error("save_memory execution failed: %s", exc)
        return {"status": "error", "error": str(exc)}
