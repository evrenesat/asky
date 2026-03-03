"""Core inline-help engine and built-in providers."""

from __future__ import annotations

import logging
from typing import Any, List, Set

from rich.console import Console
from rich.text import Text

from asky.plugins.base import CLIHint, CLIHintContext

logger = logging.getLogger(__name__)

MAX_INLINE_HINTS_PER_EMISSION = 2
QUERY_DEFAULT_INLINE_HELP_SEEN_KEY = "__inline_help_seen"


def _dedupe_and_sort_hints(hints: List[CLIHint], seen_ids: Set[str]) -> List[CLIHint]:
    """Deduplicate, filter by seen, sort by priority, and cap."""
    unique_hints = {}
    for hint in hints:
        if hint.id in seen_ids and hint.frequency == "per_session":
            continue
        if hint.id in unique_hints:
            if hint.priority > unique_hints[hint.id].priority:
                unique_hints[hint.id] = hint
        else:
            unique_hints[hint.id] = hint

    sorted_hints = sorted(
        unique_hints.values(),
        key=lambda h: (-h.priority, h.id)
    )
    return sorted_hints[:MAX_INLINE_HINTS_PER_EMISSION]


def _get_seen_hint_ids(session_id: int | None) -> Set[str]:
    """Retrieve seen hint IDs from session if available."""
    if not session_id:
        return set()
    from asky.storage.sqlite import SQLiteHistoryRepository
    from asky.storage import init_db
    try:
        init_db()
        repo = SQLiteHistoryRepository()
        session = repo.get_session_by_id(session_id)
        if session:
            defaults = dict(getattr(session, "query_defaults", None) or {})
            seen = defaults.get(QUERY_DEFAULT_INLINE_HELP_SEEN_KEY, [])
            if isinstance(seen, list):
                return set(seen)
    except Exception:
        logger.debug("Failed to get seen inline hints from session", exc_info=True)
    return set()


def _mark_hints_as_seen(session_id: int | None, hint_ids: List[str]) -> None:
    """Persist new seen hint IDs to session."""
    if not session_id or not hint_ids:
        return
    from asky.storage.sqlite import SQLiteHistoryRepository
    from asky.storage import init_db
    try:
        init_db()
        repo = SQLiteHistoryRepository()
        session = repo.get_session_by_id(session_id)
        if session:
            defaults = dict(getattr(session, "query_defaults", None) or {})
            seen = list(set(defaults.get(QUERY_DEFAULT_INLINE_HELP_SEEN_KEY, []) + hint_ids))
            defaults[QUERY_DEFAULT_INLINE_HELP_SEEN_KEY] = seen
            repo.update_session_query_defaults(session_id, defaults)
    except Exception:
        logger.debug("Failed to mark inline hints as seen", exc_info=True)


def mark_hints_seen_for_session(session_id: int | None, hints: List[CLIHint]) -> None:
    """Persist only per-session hints for the given session id."""
    if not session_id or not hints:
        return
    hint_ids = [hint.id for hint in hints if hint.frequency == "per_session"]
    _mark_hints_as_seen(session_id, hint_ids)


def _collect_builtin_pre_dispatch_hints(args: Any) -> List[CLIHint]:
    """Collect hints from built-in providers (e.g. research mode)."""
    hints = []
    
    # Provider: Research source-mode reminder
    # args.research, args.research_source_mode
    if getattr(args, "research", False):
        mode = getattr(args, "research_source_mode", None)
        if mode == "local_only":
            hints.append(
                CLIHint(
                    id="research_local_only",
                    message='Research mode is local-only. To include web searches, append \',web\' to your corpus pointer (e.g. -r ".,web").',
                    priority=50,
                    frequency="per_session",
                )
            )
        elif mode == "mixed":
            hints.append(
                CLIHint(
                    id="research_mixed",
                    message="Research mode is mixed (local+web). For deeper web context, use a pure web session (-r web).",
                    priority=50,
                    frequency="per_session",
                )
            )
        elif mode == "web_only":
            hints.append(
                CLIHint(
                    id="research_web_only",
                    message="Research mode is web-only. To ground answers in local files, pass a path (e.g. -r .).",
                    priority=50,
                    frequency="per_session",
                )
            )

    return hints


def collect_pre_dispatch_hints(args: Any, plugin_manager: Any = None) -> List[CLIHint]:
    """Collect static hints before dispatching the command."""
    hints = _collect_builtin_pre_dispatch_hints(args)
    
    if plugin_manager:
        context = CLIHintContext(parsed_args=args, phase="pre_dispatch")
        plugin_contributions = plugin_manager.collect_cli_hint_contributions(context)
        for _, hint in plugin_contributions:
            if isinstance(hint, CLIHint):
                hints.append(hint)
                
    return hints


def collect_post_turn_hints(turn_request: Any, turn_result: Any, cli_args: Any, plugin_runtime: Any = None) -> List[CLIHint]:
    """Collect runtime hints after a chat turn."""
    hints = []
    
    if plugin_runtime:
        from asky.plugins.hook_types import CLIInlineHintsContext, CLI_INLINE_HINTS_BUILD
        context = CLIInlineHintsContext(
            request=turn_request,
            result=turn_result,
            cli_args=cli_args,
            hints=[]
        )
        plugin_runtime.hooks.invoke(CLI_INLINE_HINTS_BUILD, context)
        for hint in context.hints:
            if isinstance(hint, CLIHint):
                hints.append(hint)
                
    return hints


def render_inline_hints(
    console: Console,
    hints: List[CLIHint],
    session_id: int | None = None,
) -> List[CLIHint]:
    """Render actionable one-line hints to the terminal."""
    if not hints:
        return []
        
    seen_ids = _get_seen_hint_ids(session_id) if session_id else set()
    
    # Filter for CLI output channel and dedupe
    cli_hints = [h for h in hints if h.channel == "cli_stdout"]
    
    final_hints = _dedupe_and_sort_hints(cli_hints, seen_ids)
    if not final_hints:
        return []
        
    for hint in final_hints:
        # Operational tone, single line
        text = Text()
        text.append("💡 Hint: ", style="bold cyan")
        text.append(hint.message, style="dim white")
        console.print(text)

    mark_hints_seen_for_session(session_id, final_hints)
    return final_hints
