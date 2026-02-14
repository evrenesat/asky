"""Core logic and orchestration for asky (lazy exports)."""

from __future__ import annotations

from importlib import import_module
from typing import Dict, Tuple

_EXPORTS: Dict[str, Tuple[str, str]] = {
    "get_llm_msg": ("asky.core.api_client", "get_llm_msg"),
    "count_tokens": ("asky.core.api_client", "count_tokens"),
    "UsageTracker": ("asky.core.api_client", "UsageTracker"),
    "ConversationEngine": ("asky.core.engine", "ConversationEngine"),
    "create_tool_registry": ("asky.core.engine", "create_tool_registry"),
    "create_default_tool_registry": ("asky.core.engine", "create_tool_registry"),
    "create_research_tool_registry": (
        "asky.core.engine",
        "create_research_tool_registry",
    ),
    "generate_summaries": ("asky.core.engine", "generate_summaries"),
    "ToolRegistry": ("asky.core.registry", "ToolRegistry"),
    "SessionManager": ("asky.core.session_manager", "SessionManager"),
    "get_shell_session_id": ("asky.core.session_manager", "get_shell_session_id"),
    "set_shell_session_id": ("asky.core.session_manager", "set_shell_session_id"),
    "clear_shell_session": ("asky.core.session_manager", "clear_shell_session"),
    "construct_system_prompt": ("asky.core.prompts", "construct_system_prompt"),
    "construct_research_system_prompt": (
        "asky.core.prompts",
        "construct_research_system_prompt",
    ),
    "append_research_guidance": ("asky.core.prompts", "append_research_guidance"),
    "extract_calls": ("asky.core.prompts", "extract_calls"),
    "is_markdown": ("asky.core.prompts", "is_markdown"),
    "parse_textual_tool_call": ("asky.core.prompts", "parse_textual_tool_call"),
    "AskyError": ("asky.core.exceptions", "AskyError"),
    "ContextOverflowError": ("asky.core.exceptions", "ContextOverflowError"),
}


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module 'asky.core' has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name)
    return getattr(module, attr_name)


__all__ = sorted(_EXPORTS.keys())
