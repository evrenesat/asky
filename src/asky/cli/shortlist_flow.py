"""Pre-LLM shortlist orchestration helpers for chat flow."""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional

from rich.console import Console

ShortlistExecutor = Callable[..., Dict[str, Any]]
ShortlistFormatter = Callable[[Dict[str, Any]], str]
ShortlistStatsBuilder = Callable[[Dict[str, Any], float], Dict[str, Any]]
ShortlistVerbosePrinter = Callable[[Console, Dict[str, Any]], None]


def run_pre_llm_shortlist(
    *,
    query_text: str,
    research_mode: bool,
    shortlist_enabled: bool,
    shortlist_reason: str,
    live_banner: bool,
    verbose: bool,
    renderer: Any,
    shortlist_executor: ShortlistExecutor,
    shortlist_formatter: ShortlistFormatter,
    shortlist_stats_builder: ShortlistStatsBuilder,
    shortlist_verbose_printer: ShortlistVerbosePrinter,
) -> tuple[Optional[str], Dict[str, Any], Dict[str, Any], float]:
    """Run pre-LLM shortlist stage and return context plus execution metadata."""
    if live_banner:
        renderer.start_live()
        if shortlist_enabled:
            renderer.update_banner(
                0, status_message="Shortlist: starting pre-LLM retrieval"
            )
        else:
            renderer.update_banner(
                0, status_message=f"Shortlist disabled ({shortlist_reason})"
            )

    def shortlist_status_reporter(message: str) -> None:
        if live_banner and message:
            renderer.update_banner(0, status_message=message)

    shortlist_context: Optional[str] = None
    shortlist_payload: Dict[str, Any] = {
        "enabled": False,
        "candidates": [],
        "warnings": [],
        "stats": {},
        "trace": {
            "processed_candidates": [],
            "selected_candidates": [],
        },
    }
    shortlist_elapsed = 0.0

    if shortlist_enabled:
        try:
            shortlist_start = time.perf_counter()
            shortlist_payload = shortlist_executor(
                user_prompt=query_text,
                research_mode=research_mode,
                status_callback=shortlist_status_reporter if live_banner else None,
            )
            shortlist_elapsed = (time.perf_counter() - shortlist_start) * 1000
        except Exception:
            renderer.stop_live()
            raise

    shortlist_banner_stats = shortlist_stats_builder(shortlist_payload, shortlist_elapsed)
    renderer.set_shortlist_stats(shortlist_banner_stats)

    if shortlist_payload.get("enabled"):
        shortlist_context = shortlist_formatter(shortlist_payload)

    if live_banner:
        warnings_count = len(shortlist_payload.get("warnings", []) or [])
        if shortlist_enabled:
            status_msg = (
                f"Shortlist ready: {shortlist_banner_stats['selected']} selected "
                f"in {shortlist_elapsed:.0f}ms"
            )
            if warnings_count > 0:
                status_msg += f" ({warnings_count} warning(s))"
        else:
            status_msg = f"Shortlist disabled ({shortlist_reason})"
        renderer.update_banner(0, status_message=status_msg)

    if verbose:
        verbose_console = (
            renderer.live.console if live_banner and renderer.live else renderer.console
        )
        shortlist_verbose_printer(verbose_console, shortlist_payload)

    if live_banner:
        renderer.update_banner(0, status_message=None)

    return shortlist_context, shortlist_payload, shortlist_banner_stats, shortlist_elapsed
