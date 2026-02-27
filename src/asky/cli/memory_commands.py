"""CLI handlers for memory management commands."""

from __future__ import annotations

import logging

from rich.console import Console
from rich.table import Table

from asky.config import (
    DB_PATH,
    RESEARCH_CHROMA_PERSIST_DIRECTORY,
    USER_MEMORY_CHROMA_COLLECTION,
)
from asky.memory.store import (
    delete_all_memories_from_db,
    delete_memory_from_db,
    get_all_memories,
    get_memory_by_id,
)
from asky.memory.vector_ops import (
    clear_all_memory_embeddings,
    delete_memory_from_chroma,
)

console = Console()
logger = logging.getLogger(__name__)

_MAX_MEMORY_DISPLAY_CHARS = 80


def handle_list_memories() -> None:
    """Print a table of all saved user memories."""
    memories = get_all_memories(DB_PATH)
    if not memories:
        console.print("No memories saved.")
        return

    table = Table(title="User Memories", show_header=True, header_style="bold cyan")
    table.add_column("ID", justify="right", style="dim", width=5)
    table.add_column("Memory", style="white")
    table.add_column("Tags", style="magenta")
    table.add_column("Created At", style="green")

    for m in memories:
        text = m["memory_text"]
        if len(text) > _MAX_MEMORY_DISPLAY_CHARS:
            text = text[:_MAX_MEMORY_DISPLAY_CHARS] + "..."
        tags_str = ", ".join(m["tags"]) if m["tags"] else ""
        table.add_row(str(m["id"]), text, tags_str, m["created_at"][:19])

    console.print(table)


def handle_delete_memory(memory_id: int) -> None:
    """Delete a single memory by ID."""
    existing = get_memory_by_id(DB_PATH, memory_id)
    if existing is None:
        console.print(f"Memory ID {memory_id} not found.")
        return

    delete_memory_from_db(DB_PATH, memory_id)
    delete_memory_from_chroma(
        RESEARCH_CHROMA_PERSIST_DIRECTORY,
        memory_id,
        USER_MEMORY_CHROMA_COLLECTION,
    )
    console.print(f"Deleted memory {memory_id}.")


def handle_clear_memories() -> None:
    """Prompt for confirmation, then delete all memories."""
    try:
        answer = input("Are you sure you want to delete ALL memories? (y/N) ").strip()
    except (EOFError, KeyboardInterrupt):
        console.print("\nAborted.")
        return

    if answer.lower() != "y":
        console.print("Aborted.")
        return

    count = delete_all_memories_from_db(DB_PATH)
    clear_all_memory_embeddings(RESEARCH_CHROMA_PERSIST_DIRECTORY, USER_MEMORY_CHROMA_COLLECTION)
    console.print(f"Deleted {count} memories.")


def clear_memories_non_interactive() -> int:
    """Delete all memories without interactive confirmation and return deleted count."""
    count = delete_all_memories_from_db(DB_PATH)
    clear_all_memory_embeddings(
        RESEARCH_CHROMA_PERSIST_DIRECTORY,
        USER_MEMORY_CHROMA_COLLECTION,
    )
    logger.info("Deleted %s memories via non-interactive cleanup.", count)
    return int(count)
