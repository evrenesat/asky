"""Research mode module with lazy exports."""

from __future__ import annotations

from importlib import import_module
from typing import Dict, Tuple

_EXPORTS: Dict[str, Tuple[str, str]] = {
    "ResearchCache": ("asky.research.cache", "ResearchCache"),
    "EmbeddingClient": ("asky.research.embeddings", "EmbeddingClient"),
    "VectorStore": ("asky.research.vector_store", "VectorStore"),
    "execute_extract_links": ("asky.research.tools", "execute_extract_links"),
    "execute_get_link_summaries": ("asky.research.tools", "execute_get_link_summaries"),
    "execute_get_relevant_content": (
        "asky.research.tools",
        "execute_get_relevant_content",
    ),
    "execute_get_full_content": ("asky.research.tools", "execute_get_full_content"),
    "execute_save_finding": ("asky.research.tools", "execute_save_finding"),
    "execute_query_research_memory": (
        "asky.research.tools",
        "execute_query_research_memory",
    ),
    "RESEARCH_TOOL_SCHEMAS": ("asky.research.tools", "RESEARCH_TOOL_SCHEMAS"),
}


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module 'asky.research' has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name)
    return getattr(module, attr_name)


__all__ = sorted(_EXPORTS.keys())
