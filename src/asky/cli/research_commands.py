"""CLI helpers for manual research-corpus inspection without LLM calls."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.table import Table

from asky.cli.local_ingestion_flow import preload_local_research_sources
from asky.research.cache import ResearchCache
from asky.research.tools import execute_get_relevant_content

DEFAULT_MANUAL_QUERY_MAX_SOURCES = 20
DEFAULT_MANUAL_QUERY_MAX_CHUNKS = 3


def _print_manual_query_results(
    *,
    console: Console,
    query: str,
    source_ids: List[str],
    results: Dict[str, Any],
) -> None:
    """Render manual corpus query results."""
    table = Table(
        title="Manual Corpus Query Results",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Source", style="magenta")
    table.add_column("Title", style="white")
    table.add_column("Top Evidence", style="green")

    rows_added = 0
    for source_id in source_ids:
        payload = results.get(source_id)
        if not isinstance(payload, dict):
            continue

        error = str(payload.get("error", "") or "").strip()
        if error:
            table.add_row(source_id, "-", f"[red]{error}[/red]")
            rows_added += 1
            continue

        title = str(payload.get("title", "") or "")
        chunks = payload.get("chunks")
        if isinstance(chunks, list) and chunks:
            snippet = str(chunks[0].get("text", "") or "").strip()
            snippet = snippet.replace("\n", " ")
            if len(snippet) > 320:
                snippet = f"{snippet[:320]}..."
            score = chunks[0].get("relevance")
            if isinstance(score, (int, float)):
                snippet = f"(relevance={float(score):.3f}) {snippet}"
            table.add_row(source_id, title or "-", snippet or "(empty chunk)")
            rows_added += 1
            continue

        preview = str(payload.get("content_preview", "") or "").strip()
        if preview:
            preview = preview.replace("\n", " ")
            if len(preview) > 320:
                preview = f"{preview[:320]}..."
            table.add_row(source_id, title or "-", preview)
            rows_added += 1
            continue

    console.print(
        f"Manual corpus query: [bold]{query}[/bold]\n"
        f"Sources queried: {len(source_ids)}"
    )

    if rows_added == 0:
        console.print(
            "[yellow]No relevant chunks returned. Try a narrower or differently phrased query.[/yellow]"
        )
        return

    console.print(table)


def run_manual_corpus_query_command(
    *,
    query: str,
    explicit_targets: Optional[List[str]] = None,
    max_sources: int = DEFAULT_MANUAL_QUERY_MAX_SOURCES,
    max_chunks: int = DEFAULT_MANUAL_QUERY_MAX_CHUNKS,
    console: Optional[Console] = None,
) -> int:
    """Run deterministic corpus retrieval directly from cache (no model call)."""
    active_console = console or Console()
    safe_max_sources = max(1, int(max_sources))
    safe_max_chunks = max(1, int(max_chunks))

    ingested_payload: Optional[Dict[str, Any]] = None
    source_ids: List[str] = []
    if explicit_targets:
        ingested_payload = preload_local_research_sources(
            user_prompt="",
            explicit_targets=list(explicit_targets),
        )
        ingested = ingested_payload.get("ingested") or []
        source_ids = [
            str(item.get("source_handle", "") or "").strip()
            for item in ingested
            if str(item.get("source_handle", "") or "").strip()
        ]

        warnings = ingested_payload.get("warnings") or []
        for warning in warnings[:8]:
            active_console.print(f"[yellow]Warning:[/] {warning}")

    if not source_ids:
        cache = ResearchCache()
        cached_sources = cache.list_cached_sources(limit=safe_max_sources)
        source_ids = [f"corpus://cache/{entry['id']}" for entry in cached_sources]

    source_ids = source_ids[:safe_max_sources]
    if not source_ids:
        active_console.print(
            "[bold red]Error:[/] No cached corpus sources available. "
            "Ingest a corpus first with `-r <pointer>`."
        )
        return 1

    results = execute_get_relevant_content(
        {
            "query": query,
            "corpus_urls": source_ids,
            "max_chunks": safe_max_chunks,
        }
    )
    if not isinstance(results, dict):
        active_console.print("[bold red]Error:[/] Corpus query returned invalid output.")
        return 1

    _print_manual_query_results(
        console=active_console,
        query=query,
        source_ids=source_ids,
        results=results,
    )
    return 0
