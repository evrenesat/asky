"""CLI commands for deterministic local-corpus section listing and summarization."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from rich.console import Console
from rich.table import Table

from asky.cli.local_ingestion_flow import preload_local_research_sources
from asky.research.cache import ResearchCache
from asky.research.sections import (
    MIN_SUMMARIZE_SECTION_CHARS,
    build_section_index,
    get_listable_sections,
    match_section_strict,
    slice_section_content,
)
from asky.summarization import _summarize_content

DEFAULT_SECTION_DETAIL = "balanced"
DEFAULT_SECTION_LIST_SOURCE_LIMIT = 20
DEFAULT_SECTION_SUGGESTION_LIMIT = 8

SECTION_DETAIL_OPTIONS = {"compact", "balanced", "max"}
SECTION_HANDLE_PATTERN = re.compile(r"^corpus://cache/(\d+)$", re.IGNORECASE)

SECTION_SUMMARY_PROMPTS: Dict[str, str] = {
    "compact": (
        "Summarize this section concisely with clear thematic bullets. "
        "Cover the thesis, major claims, and strongest examples."
    ),
    "balanced": (
        "Produce a comprehensive section summary. Include argument flow, "
        "sub-themes, examples, causal claims, constraints, and implications. "
        "Prefer concrete detail over high-level generic phrasing."
    ),
    "max": (
        "Produce an exhaustive section summary with strong structural coverage. "
        "Capture the narrative progression, key terminology, factual examples, "
        "contrasts, caveats, and practical implications in detail."
    ),
}

SECTION_SUMMARY_MAX_OUTPUT_CHARS: Dict[str, int] = {
    "compact": 2800,
    "balanced": 7200,
    "max": 12000,
}
CORPUS_HANDLE_PREFIX = "corpus://cache/"


def _parse_cache_id_from_handle(source_handle: str) -> Optional[int]:
    token = str(source_handle or "").strip()
    match = SECTION_HANDLE_PATTERN.match(token)
    if not match:
        return None
    return int(match.group(1))


def _format_section_ref(cache_id: int, section_id: str) -> str:
    return f"{CORPUS_HANDLE_PREFIX}{int(cache_id)}#section={section_id}"


def _coerce_source_handle(source: str) -> Optional[str]:
    raw = str(source or "").strip()
    if not raw:
        return None

    cache_id = _parse_cache_id_from_handle(raw)
    if cache_id is not None:
        return f"corpus://cache/{cache_id}"

    if raw.isdigit():
        return f"corpus://cache/{int(raw)}"

    return None


def _source_entry_from_cache_id(cache: ResearchCache, cache_id: int) -> Optional[Dict[str, Any]]:
    cached = cache.get_cached_by_id(cache_id)
    if not cached:
        return None
    return {
        "id": cache_id,
        "handle": f"corpus://cache/{cache_id}",
        "title": str(cached.get("title", "") or ""),
        "url": str(cached.get("url", "") or ""),
    }


def _collect_source_entries(
    *,
    cache: ResearchCache,
    explicit_targets: Optional[List[str]],
    console: Console,
) -> List[Dict[str, Any]]:
    source_entries: List[Dict[str, Any]] = []

    if explicit_targets:
        ingest_payload = preload_local_research_sources(
            user_prompt="",
            explicit_targets=list(explicit_targets),
        )
        warnings = list(ingest_payload.get("warnings") or [])
        for warning in warnings[:DEFAULT_SECTION_SUGGESTION_LIMIT]:
            console.print(f"[yellow]Warning:[/] {warning}")

        for item in ingest_payload.get("ingested") or []:
            handle = str(item.get("source_handle", "") or "").strip()
            cache_id = _parse_cache_id_from_handle(handle)
            if cache_id is None:
                continue
            entry = _source_entry_from_cache_id(cache, cache_id)
            if entry is not None:
                source_entries.append(entry)

    if not source_entries:
        for item in cache.list_cached_sources(limit=DEFAULT_SECTION_LIST_SOURCE_LIMIT):
            cache_id = int(item.get("id"))
            source_entries.append(
                {
                    "id": cache_id,
                    "handle": f"corpus://cache/{cache_id}",
                    "title": str(item.get("title", "") or ""),
                    "url": str(item.get("url", "") or ""),
                }
            )

    deduped: List[Dict[str, Any]] = []
    seen = set()
    for entry in source_entries:
        source_id = int(entry["id"])
        if source_id in seen:
            continue
        seen.add(source_id)
        deduped.append(entry)
    return deduped


def _render_source_choices(console: Console, sources: List[Dict[str, Any]]) -> None:
    table = Table(title="Available Local Corpus Sources", show_header=True)
    table.add_column("Handle", style="magenta")
    table.add_column("Title", style="white")
    table.add_column("URL", style="green")

    for source in sources[:DEFAULT_SECTION_LIST_SOURCE_LIMIT]:
        table.add_row(
            str(source.get("handle", "")),
            str(source.get("title", "") or "-"),
            str(source.get("url", "") or "-"),
        )

    console.print(table)


def _resolve_source(
    *,
    source_selector: Optional[str],
    source_entries: List[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if not source_entries:
        return None, "No local corpus sources are cached. Ingest one with -r <pointer> first."

    if not source_selector:
        if len(source_entries) == 1:
            return source_entries[0], None
        return None, "Multiple local corpus sources found. Specify one with --section-source."

    selector = str(source_selector).strip()
    if not selector:
        return None, "Invalid --section-source value."

    coerced = _coerce_source_handle(selector)
    if coerced:
        cache_id = _parse_cache_id_from_handle(coerced)
        for entry in source_entries:
            if int(entry["id"]) == cache_id:
                return entry, None
        return None, f"Section source not found in cache: {coerced}"

    lowered = selector.lower()
    matches = [
        entry
        for entry in source_entries
        if lowered in str(entry.get("title", "")).lower()
        or lowered in str(entry.get("url", "")).lower()
    ]

    if len(matches) == 1:
        return matches[0], None
    if not matches:
        return None, f"No local source matched --section-source '{selector}'."
    return None, (
        f"--section-source '{selector}' matched multiple cached sources. "
        "Use a corpus handle (corpus://cache/<id>) for an exact source."
    )


def _render_sections(console: Console, source: Dict[str, Any], section_index: Dict[str, Any]) -> None:
    include_toc = bool(source.get("include_toc"))
    sections = get_listable_sections(section_index, include_toc=include_toc)
    cache_id = int(source.get("id"))
    table = Table(title="Local Corpus Sections", show_header=True)
    table.add_column("ID", style="magenta")
    table.add_column("Title", style="white")
    table.add_column("Chars", style="green", justify="right")
    table.add_column("Section Ref", style="cyan")
    if include_toc:
        table.add_column("TOC", style="yellow")

    for section in sections:
        section_id = str(section.get("id", ""))
        row: List[str] = [
            section_id,
            str(section.get("title", "")),
            str(int(section.get("char_count", 0) or 0)),
            _format_section_ref(cache_id, section_id),
        ]
        if include_toc:
            row.append("yes" if bool(section.get("is_toc")) else "no")
        table.add_row(
            *row,
        )

    console.print(
        "\n".join(
            [
                f"Section source: [bold]{source.get('handle')}[/bold]",
                f"Title: {source.get('title') or '-'}",
                f"Sections returned: {len(sections)}",
                f"All detected headings: {len(list(section_index.get('sections') or []))}",
            ]
        )
    )
    console.print(table)


def _normalize_detail(detail: Optional[str]) -> str:
    if not detail:
        return DEFAULT_SECTION_DETAIL
    normalized = str(detail).strip().lower()
    if normalized in SECTION_DETAIL_OPTIONS:
        return normalized
    return DEFAULT_SECTION_DETAIL


def _render_match_suggestions(
    *,
    console: Console,
    section_query: str,
    match_payload: Dict[str, Any],
    cache_id: Optional[int] = None,
) -> None:
    suggestions = list(match_payload.get("suggestions") or [])
    confidence = float(match_payload.get("confidence", 0.0) or 0.0)
    reason = str(match_payload.get("reason", "") or "unknown")
    console.print(
        f"[bold red]Error:[/] No strict section match for '{section_query}'. "
        f"(reason={reason}, top_confidence={confidence:.3f})"
    )

    if not suggestions:
        return

    table = Table(title="Closest Section Matches", show_header=True)
    table.add_column("ID", style="magenta")
    table.add_column("Title", style="white")
    table.add_column("Confidence", style="green", justify="right")
    if cache_id is not None:
        table.add_column("Section Ref", style="cyan")

    for item in suggestions:
        row: List[str] = [
            str(item.get("id", "")),
            str(item.get("title", "")),
            f"{float(item.get('confidence', 0.0) or 0.0):.3f}",
        ]
        if cache_id is not None:
            row.append(_format_section_ref(cache_id, str(item.get("id", "") or "")))
        table.add_row(*row)

    console.print(table)


def _build_summary_prompt(detail: str, section_title: str) -> str:
    base = SECTION_SUMMARY_PROMPTS[detail]
    return (
        f"{base}\n"
        f"Focus only on the section titled: {section_title}\n"
        "Do not summarize unrelated sections."
    )


def run_summarize_section_command(
    *,
    section_query: Optional[str],
    section_source: Optional[str],
    section_id: Optional[str] = None,
    section_include_toc: bool = False,
    section_detail: str = DEFAULT_SECTION_DETAIL,
    section_max_chunks: Optional[int] = None,
    explicit_targets: Optional[List[str]] = None,
    console: Optional[Console] = None,
) -> int:
    """List sections or summarize one section from local corpus without the main model."""
    active_console = console or Console()
    cache = ResearchCache()

    source_entries = _collect_source_entries(
        cache=cache,
        explicit_targets=explicit_targets,
        console=active_console,
    )
    source, source_error = _resolve_source(
        source_selector=section_source,
        source_entries=source_entries,
    )
    if source_error:
        active_console.print(f"[bold red]Error:[/] {source_error}")
        if source_entries:
            _render_source_choices(active_console, source_entries)
        return 1
    if source is None:
        active_console.print("[bold red]Error:[/] Could not resolve section source.")
        return 1

    cached = cache.get_cached_by_id(int(source["id"]))
    if not cached:
        active_console.print(
            f"[bold red]Error:[/] Source {source['handle']} is not available in cache anymore."
        )
        return 1

    content = str(cached.get("content", "") or "")
    if not content.strip():
        active_console.print(
            f"[bold red]Error:[/] Source {source['handle']} has no cached content."
        )
        return 1

    section_index = build_section_index(content)
    sections = get_listable_sections(section_index, include_toc=bool(section_include_toc))
    if not sections:
        active_console.print("[bold red]Error:[/] No sections were detected in this source.")
        return 1

    source["include_toc"] = bool(section_include_toc)
    normalized_query = str(section_query or "").strip()
    normalized_section_id = str(section_id or "").strip()
    if not normalized_query and not normalized_section_id:
        _render_sections(active_console, source, section_index)
        return 0

    requested_section_id = normalized_section_id
    match_payload: Dict[str, Any] = {"confidence": 1.0}
    if not requested_section_id:
        match_payload = match_section_strict(normalized_query, section_index)
        if not match_payload.get("matched"):
            _render_match_suggestions(
                console=active_console,
                section_query=normalized_query,
                match_payload=match_payload,
                cache_id=int(source["id"]),
            )
            return 1
        section = dict(match_payload["section"])
        requested_section_id = str(section.get("id", "") or "")

    slice_payload = slice_section_content(
        content,
        section_index,
        requested_section_id,
        max_chunks=section_max_chunks,
    )
    if slice_payload.get("error"):
        active_console.print(f"[bold red]Error:[/] {slice_payload.get('error')}")
        active_console.print("Use --summarize-section with no value to list valid section IDs.")
        return 1

    resolved_section = dict(slice_payload.get("section") or {})
    resolved_section_id = str(
        slice_payload.get("resolved_section_id", requested_section_id)
        or requested_section_id
    )
    requested_section_id = str(
        slice_payload.get("requested_section_id", requested_section_id)
        or requested_section_id
    )
    section_text = str(slice_payload.get("content", "") or "").strip()
    if not section_text:
        active_console.print("[bold red]Error:[/] Matched section has no extractable content.")
        return 1
    if len(section_text) < MIN_SUMMARIZE_SECTION_CHARS:
        active_console.print(
            "[bold red]Error:[/] Resolved section is too small to summarize "
            f"reliably ({len(section_text)} chars, minimum {MIN_SUMMARIZE_SECTION_CHARS})."
        )
        active_console.print("List sections and choose a canonical body section ID.")
        return 1

    detail = _normalize_detail(section_detail)
    summary = _summarize_content(
        content=section_text,
        prompt_template=_build_summary_prompt(detail, str(resolved_section.get("title", ""))),
        max_output_chars=SECTION_SUMMARY_MAX_OUTPUT_CHARS[detail],
    )

    metadata_lines = [
        f"Section source: {source.get('handle')}",
        f"Matched section: {resolved_section.get('title')} ({resolved_section_id})",
        f"Requested section ID: {requested_section_id}",
        f"Auto-promoted to canonical: {'yes' if bool(slice_payload.get('auto_promoted')) else 'no'}",
        f"Section ref: {_format_section_ref(int(source['id']), resolved_section_id)}",
        f"Match confidence: {float(match_payload.get('confidence', 0.0) or 0.0):.3f}",
        f"Detail profile: {detail}",
        f"Section chars used for summary: {len(section_text):,}",
    ]
    if bool(slice_payload.get("truncated")):
        available_chunks = int(slice_payload.get("available_chunks", 0) or 0)
        metadata_lines.append(
            f"Input truncated by --section-max-chunks (available chunks: {available_chunks})."
        )

    active_console.print("\n".join(metadata_lines))
    active_console.print("\n[bold cyan]Section Summary[/bold cyan]\n")
    active_console.print(summary)
    return 0
