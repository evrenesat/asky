"""Memory recall pipeline — retrieves relevant memories for injection into system prompt."""

from __future__ import annotations

import logging
from typing import Optional

from asky.config import (
    DB_PATH,
    RESEARCH_CHROMA_PERSIST_DIRECTORY,
    USER_MEMORY_CHROMA_COLLECTION,
)
from asky.memory.store import has_any_memories
from asky.memory.vector_ops import search_memories

logger = logging.getLogger(__name__)

MEMORY_SECTION_HEADER = "## User Memory\nThe following are previously saved facts about this user:"


def recall_memories_for_query(
    query_text: str,
    top_k: int,
    min_similarity: float,
    db_path=None,
    chroma_dir=None,
) -> Optional[str]:
    """Search user memories relevant to query_text and return a formatted markdown block.

    Returns None if no memories exist or none match the query.
    """
    effective_db_path = db_path or DB_PATH
    effective_chroma_dir = chroma_dir or RESEARCH_CHROMA_PERSIST_DIRECTORY

    if not has_any_memories(effective_db_path):
        return None

    # Use YAKE keyphrases to expand the search query
    from asky.research.query_expansion import expand_query_deterministic

    sub_queries = expand_query_deterministic(query_text)
    combined_query = " ".join(sub_queries) if len(sub_queries) > 1 else query_text

    results = search_memories(
        db_path=effective_db_path,
        chroma_dir=effective_chroma_dir,
        query=combined_query,
        top_k=top_k,
        min_similarity=min_similarity,
        collection_name=USER_MEMORY_CHROMA_COLLECTION,
    )

    if not results:
        return None

    lines = [MEMORY_SECTION_HEADER]
    for memory_dict, _similarity in results:
        lines.append(f"- {memory_dict['memory_text']}")

    return "\n".join(lines)
