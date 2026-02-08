"""CLI package for asky with lazy exports."""

from __future__ import annotations

from importlib import import_module
from typing import Dict, Optional, Tuple

_EXPORTS: Dict[str, Tuple[str, Optional[str]]] = {
    "show_history": ("asky.cli.history", "show_history_command"),
    "print_answers": ("asky.cli.history", "print_answers_command"),
    "handle_delete_messages": ("asky.cli.history", "handle_delete_messages_command"),
    "handle_delete_sessions": (
        "asky.cli.sessions",
        "handle_delete_sessions_command",
    ),
    "list_prompts": ("asky.cli.prompts", "list_prompts_command"),
    "run_chat": ("asky.cli.chat", "run_chat"),
    "load_context": ("asky.cli.chat", "load_context"),
    "build_messages": ("asky.cli.chat", "build_messages"),
    "expand_query_text": ("asky.cli.utils", "expand_query_text"),
    "print_config": ("asky.cli.utils", "print_config"),
    "openrouter": ("asky.cli.openrouter", None),
}


def _restore_main_entrypoint() -> None:
    """Ensure package attribute `main` stays the callable entrypoint."""
    globals()["main"] = _main_entrypoint


def _main_entrypoint() -> None:
    """CLI entry point wrapper for console scripts."""
    from asky.cli.main import main as main_impl

    _restore_main_entrypoint()
    main_impl()


def parse_args():
    from asky.cli.main import parse_args as parse_args_impl

    _restore_main_entrypoint()
    return parse_args_impl()


def handle_print_answer_implicit(args):
    from asky.cli.main import (
        handle_print_answer_implicit as handle_print_answer_implicit_impl,
    )

    _restore_main_entrypoint()
    return handle_print_answer_implicit_impl(args)


main = _main_entrypoint


def __getattr__(name: str):
    if name == "main":
        return main
    if name == "parse_args":
        return parse_args
    if name == "handle_print_answer_implicit":
        return handle_print_answer_implicit
    if name not in _EXPORTS:
        raise AttributeError(f"module 'asky.cli' has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name)
    _restore_main_entrypoint()
    if attr_name is None:
        return module
    return getattr(module, attr_name)


__all__ = [
    "main",
    "parse_args",
    "handle_print_answer_implicit",
    *sorted(_EXPORTS.keys()),
]
