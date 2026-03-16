"""CLI handlers for persona management commands."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

import json
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from asky.config.loader import _get_config_dir
from asky.core import get_shell_session_id
from asky.plugins.kvstore import PluginKVStore
from asky.plugins.manual_persona_creator import book_service, source_service, web_service
from asky.plugins.manual_persona_creator.book_ingestion import BookIngestionJob
from asky.plugins.manual_persona_creator.web_types import WebPageStatus
from asky.plugins.manual_persona_creator.book_types import (
    BookMetadata,
    ExtractionTargets,
    IngestionIdentityStatus,
)
from asky.plugins.manual_persona_creator.exporter import export_persona_package
from asky.plugins.manual_persona_creator.storage import (
    create_persona,
    get_persona_paths,
    list_persona_names,
    persona_exists,
    read_chunks,
    read_metadata,
    read_prompt,
    write_chunks,
    touch_updated_at,
)

console = Console()


def handle_persona_docs(args: argparse.Namespace) -> None:
    """Show persona documentation topics."""
    from asky.plugins.manual_persona_creator import feature_docs
    from rich.markdown import Markdown

    topic_id = getattr(args, "topic", None)

    if not topic_id:
        # List topics
        topics = feature_docs.list_topics()
        if not topics:
            console.print("[yellow]No persona documentation topics found.[/yellow]")
            return

        table = Table(title="Persona Documentation", show_header=True, header_style="bold magenta")
        table.add_column("Topic ID", style="cyan")
        table.add_column("Title")
        table.add_column("Summary")

        for t in topics:
            table.add_row(t.id, t.title, t.summary)

        console.print(table)
        console.print("\nRun [cyan]asky persona docs <topic-id>[/cyan] to view full content.")
        return

    try:
        topic = feature_docs.load_topic(topic_id)
        console.print(Markdown(topic.body))
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")


def _get_data_dir() -> Path:
    """Get the plugin data directory."""
    return _get_config_dir() / "plugins"


def handle_persona_ingest_book(args: argparse.Namespace) -> None:
    """Ingest an authored book into a persona."""
    persona_name = str(args.name).strip()
    source_path = str(args.path).strip()
    data_dir = _get_data_dir()

    if not persona_exists(data_dir, persona_name):
        console.print(f"[red]Error: Persona '{persona_name}' does not exist.[/red]")
        return

    try:
        with console.status("[cyan]Analyzing book and looking up metadata...[/cyan]"):
            preflight = book_service.prepare_ingestion_preflight(
                persona_name=persona_name,
                source_path=source_path,
                data_dir=data_dir,
            )

        if preflight.resumable_job_id:
            console.print(f"\n[yellow]Found unfinished ingestion job:[/yellow] {preflight.resumable_job_id}")
            if Confirm.ask("Resume this job and show preflight?"):
                _handle_preflight_loop(
                    data_dir=data_dir,
                    persona_name=persona_name,
                    source_path=source_path,
                    source_fingerprint=preflight.source_fingerprint,
                    initial_metadata=preflight.resumable_manifest.metadata,
                    initial_targets=preflight.resumable_manifest.targets,
                    stats=preflight.stats,
                    mode="ingest",
                    job_id=preflight.resumable_job_id,
                )
                return

        # Regular preflight loop
        console.print("\n[bold cyan]Book Preflight[/bold cyan]")
        console.print(f"Source: {preflight.source_path}")
        console.print(f"Stats: {preflight.stats['word_count']:,} words, {preflight.stats['section_count']} sections")

        # Candidate selection
        metadata = None
        if preflight.candidates:
            console.print("\n[bold]Select Metadata Candidate:[/bold]")
            for i, cand in enumerate(preflight.candidates, 1):
                ambiguity = " [yellow](Ambiguous)[/yellow]" if cand.is_ambiguous else ""
                console.print(f"  {i}. {cand.metadata.title} ({cand.metadata.publication_year}) by {', '.join(cand.metadata.authors)}{ambiguity}")
            console.print(f"  {len(preflight.candidates) + 1}. [Manual Entry]")
            
            choice = Prompt.ask("Choice", choices=[str(i) for i in range(1, len(preflight.candidates) + 2)], default="1")
            idx = int(choice) - 1
            if idx < len(preflight.candidates):
                metadata = preflight.candidates[idx].metadata
        
        if not metadata:
            metadata = BookMetadata(title="", authors=[])

        _handle_preflight_loop(
            data_dir=data_dir,
            persona_name=persona_name,
            source_path=source_path,
            source_fingerprint=preflight.source_fingerprint,
            initial_metadata=metadata,
            initial_targets=preflight.proposed_targets,
            stats=preflight.stats,
            mode="ingest",
        )

    except Exception as e:
        console.print(f"[red]Error during preflight: {e}[/red]")


def handle_persona_reingest_book(args: argparse.Namespace) -> None:
    """Re-ingest an already completed book."""
    persona_name = str(args.name).strip()
    book_key = str(args.book_key).strip()
    source_path = str(args.path).strip()
    data_dir = _get_data_dir()

    if not persona_exists(data_dir, persona_name):
        console.print(f"[red]Error: Persona '{persona_name}' does not exist.[/red]")
        return

    try:
        # Load existing report/metadata
        report = book_service.get_authored_book_report(
            data_dir=data_dir,
            persona_name=persona_name,
            book_key=book_key
        )

        with console.status("[cyan]Analyzing book...[/cyan]"):
            preflight = book_service.prepare_ingestion_preflight(
                persona_name=persona_name,
                source_path=source_path,
                data_dir=data_dir,
            )

        console.print(f"\n[bold cyan]Re-ingestion Preflight: {book_key}[/bold cyan]")
        console.print(f"Source: {preflight.source_path}")
        console.print(f"Stats: {preflight.stats['word_count']:,} words, {preflight.stats['section_count']} sections")

        _handle_preflight_loop(
            data_dir=data_dir,
            persona_name=persona_name,
            source_path=source_path,
            source_fingerprint=preflight.source_fingerprint,
            initial_metadata=report.metadata,
            initial_targets=report.targets,
            stats=preflight.stats,
            mode="reingest",
            expected_book_key=book_key,
        )

    except FileNotFoundError:
        console.print(f"[red]Error: Book '{book_key}' not found for persona '{persona_name}'.[/red]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def _handle_preflight_loop(
    *,
    data_dir: Path,
    persona_name: str,
    source_path: str,
    source_fingerprint: str,
    initial_metadata: BookMetadata,
    initial_targets: ExtractionTargets,
    stats: Dict[str, Any],
    mode: str,
    expected_book_key: Optional[str] = None,
    job_id: Optional[str] = None,
):
    """Editable preflight interaction loop."""
    while True:
        console.print("\n[bold cyan]Edit Metadata & Targets[/bold cyan]")
        title = Prompt.ask("Title", default=initial_metadata.title)
        authors_raw = Prompt.ask("Authors (comma separated)", default=", ".join(initial_metadata.authors))
        authors = [a.strip() for a in authors_raw.split(",") if a.strip()]
        
        pub_year_str = Prompt.ask("Publication Year", default=str(initial_metadata.publication_year or ""))
        pub_year = int(pub_year_str) if pub_year_str.isdigit() else None
        
        isbn = Prompt.ask("ISBN", default=initial_metadata.isbn or "")
        
        topic_target = int(Prompt.ask("Topic target", default=str(initial_targets.topic_target)))
        viewpoint_target = int(Prompt.ask("Viewpoint target", default=str(initial_targets.viewpoint_target)))

        metadata = BookMetadata(
            title=title,
            authors=authors,
            publication_year=pub_year,
            isbn=isbn,
        )
        targets = ExtractionTargets(
            topic_target=topic_target,
            viewpoint_target=viewpoint_target,
        )

        # Check identity status before proceeding
        status = book_service.get_ingestion_identity_status(
            data_dir=data_dir,
            persona_name=persona_name,
            metadata=metadata,
            expected_book_key=expected_book_key,
            mode=mode,
        )

        if mode == "ingest" and status == IngestionIdentityStatus.DUPLICATE_COMPLETED:
            console.print(f"\n[red]Error: Book identity already exists.[/red]")
            console.print("Manual edits resolve to a completed book. Use 'reingest-book' to replace.")
            if not Confirm.ask("Edit metadata again?"):
                return
            initial_metadata = metadata
            continue

        if mode == "reingest" and status == IngestionIdentityStatus.REPLACEMENT_FORBIDDEN:
            console.print(f"\n[red]Error: Identity mismatch.[/red]")
            console.print(f"Manual edits resolve to a different book key than '{expected_book_key}'.")
            if not Confirm.ask("Edit metadata again?"):
                return
            initial_metadata = metadata
            continue

        if not Confirm.ask("\nProceed with ingestion?"):
            console.print("[yellow]Cancelled.[/yellow]")
            return

        # Finalize job creation
        if not job_id:
            job_id = book_service.create_ingestion_job(
                data_dir=data_dir,
                persona_name=persona_name,
                source_path=source_path,
                source_fingerprint=source_fingerprint,
                metadata=metadata,
                targets=targets,
                mode=mode,
                expected_book_key=expected_book_key,
            )
        else:
            book_service.update_ingestion_job_inputs(
                data_dir=data_dir,
                persona_name=persona_name,
                job_id=job_id,
                metadata=metadata,
                targets=targets,
                mode=mode,
            )
        
        _run_ingestion_job(data_dir, persona_name, job_id)
        break


def _run_ingestion_job(data_dir: Path, persona_name: str, job_id: str):
    job = BookIngestionJob(data_dir=data_dir, persona_name=persona_name, job_id=job_id)
    try:
        console.print(f"[cyan]Starting ingestion job {job_id}...[/cyan]")
        report = job.run()
        console.print(f"\n[green]✓ Ingestion completed successfully![/green]")
        console.print(f"Book Key: [bold]{report.book_key}[/bold]")
        console.print(f"Viewpoints: {report.actual_viewpoints}")
        console.print(f"Duration: {report.duration_seconds:.1f}s")
        if report.warnings:
            console.print(f"[yellow]Warnings: {len(report.warnings)} (see book-report for details)[/yellow]")
    except Exception as e:
        console.print(f"[red]Job failed: {e}[/red]")


def handle_persona_books(args: argparse.Namespace) -> None:
    """List ingested books for a persona."""
    persona_name = str(args.name).strip()
    data_dir = _get_data_dir()
    
    if not persona_exists(data_dir, persona_name):
        console.print(f"[red]Error: Persona '{persona_name}' does not exist.[/red]")
        return

    rows = book_service.list_authored_books(data_dir=data_dir, persona_name=persona_name)
    
    if not rows:
        console.print(f"[yellow]No books ingested for persona '{persona_name}'.[/yellow]")
        return

    table = Table(title=f"Books for {persona_name}")
    table.add_column("Key", style="cyan")
    table.add_column("Title")
    table.add_column("Year", justify="right")
    table.add_column("ISBN")
    table.add_column("Viewpoints", justify="right")
    table.add_column("Last Ingested", style="dim")

    for row in rows:
        table.add_row(
            row.book_key,
            row.title,
            str(row.publication_year or ""),
            row.isbn or "",
            str(row.viewpoint_count),
            row.last_ingested_at,
        )

    console.print(table)


def handle_persona_book_report(args: argparse.Namespace) -> None:
    """Show ingestion report for a book."""
    persona_name = str(args.name).strip()
    book_key = str(args.book_key).strip()
    data_dir = _get_data_dir()

    try:
        report = book_service.get_authored_book_report(
            data_dir=data_dir,
            persona_name=persona_name,
            book_key=book_key
        )
        
        console.print(f"\n[bold cyan]Ingestion Report: {book_key}[/bold cyan]")
        console.print(f"Title: {report.metadata.title}")
        console.print(f"Authors: {', '.join(report.metadata.authors)}")
        console.print(f"Status: [green]Completed[/green]")
        console.print(f"Started: {report.started_at}")
        console.print(f"Completed: {report.completed_at}")
        console.print(f"Duration: {report.duration_seconds:.1f}s")
        
        console.print(f"\n[bold]Extraction Results:[/bold]")
        console.print(f"Topics:     {report.actual_topics} (Target: {report.targets.topic_target})")
        console.print(f"Viewpoints: {report.actual_viewpoints} (Target: {report.targets.viewpoint_target})")
        
        if report.stage_timings:
            console.print("\n[bold]Stage Timings:[/bold]")
            for stage, duration in report.stage_timings.items():
                console.print(f"  {stage:25} {duration:6.1f}s")
        
        if report.warnings:
            console.print("\n[yellow]Warnings:[/yellow]")
            for w in report.warnings:
                console.print(f"- {w}")
    except FileNotFoundError:
        console.print(f"[red]Report not found for book '{book_key}' in persona '{persona_name}'.[/red]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def handle_persona_viewpoints(args: argparse.Namespace) -> None:
    """List extracted viewpoints."""
    persona_name = str(args.name).strip()
    target_book = getattr(args, "book", None)
    target_source = getattr(args, "source", None)
    target_topic = getattr(args, "topic", None)
    limit = int(getattr(args, "limit", 20))
    data_dir = _get_data_dir()

    if not persona_exists(data_dir, persona_name):
        console.print(f"[red]Error: Persona '{persona_name}' does not exist.[/red]")
        return

    # Query both authored books and milestone-3 sources
    viewpoints = []
    
    # Authored books
    if not target_source:
        viewpoints.extend(book_service.query_authored_viewpoints(
            data_dir=data_dir,
            persona_name=persona_name,
            book_key=target_book,
            topic_query=target_topic,
            limit=limit
        ))
    
    # Milestone-3 sources
    if not target_book:
        source_vps = source_service.query_approved_viewpoints(
            data_dir=data_dir,
            persona_name=persona_name,
            source_id=target_source
        )
        # Filter source_vps by topic if requested
        if target_topic:
            source_vps = [v for v in source_vps if target_topic.lower() in v.metadata.get("topic", "").lower() or target_topic.lower() in v.text.lower()]
        
        # Convert to a common display format if needed, but here we just append
        # In a real implementation we'd unify the models for display
        for v in source_vps:
            # Simple conversion for display
            class ViewpointStub:
                def __init__(self, v):
                    self.topic = v.metadata.get("topic", "unknown")
                    self.claim = v.text
                    self.confidence = v.metadata.get("confidence", 0.0)
                    self.book_title = f"Source: {v.source_id}"
                    self.publication_year = ""
                    self.evidence = []
            viewpoints.append(ViewpointStub(v))

    viewpoints = viewpoints[:limit]

    if not viewpoints:
        console.print("[yellow]No viewpoints found matching criteria.[/yellow]")
        return

    for v in viewpoints:
        console.print(f"\n[bold cyan]Topic: {v.topic}[/bold cyan] (Conf: {v.confidence:.2f})")
        console.print(f"[bold]Claim:[/bold] {v.claim}")
        console.print(f"[dim]Source: {v.book_title} {f'({v.publication_year})' if v.publication_year else ''}[/dim]")
        
        if v.evidence:
            console.print("[italic]Evidence:[/italic]")
            for e in v.evidence:
                console.print(f"- {e.excerpt} [{e.section_ref}]")

    if len(viewpoints) >= limit:
        console.print(f"\n[dim]... showing {limit} viewpoints. Use --limit to see more.[/dim]")


def handle_persona_ingest_source(args: argparse.Namespace) -> None:
    """Ingest a non-book source into a persona."""
    persona_name = str(args.name).strip()
    kind_str = str(args.kind).strip()
    source_path = Path(args.path).expanduser()
    data_dir = _get_data_dir()

    from asky.plugins.manual_persona_creator.source_types import PersonaSourceKind
    try:
        kind = PersonaSourceKind(kind_str)
    except ValueError:
        console.print(f"[red]Error: Invalid source kind '{kind_str}'.[/red]")
        console.print(f"Supported kinds: {', '.join([k.value for k in PersonaSourceKind])}")
        return

    if not persona_exists(data_dir, persona_name):
        console.print(f"[red]Error: Persona '{persona_name}' does not exist.[/red]")
        return

    try:
        preflight = source_service.prepare_source_preflight(data_dir, persona_name, kind, source_path)
        
        console.print("\n[bold cyan]Source Preflight[/bold cyan]")
        console.print(f"Persona: [bold]{persona_name}[/bold]")
        console.print(f"Kind:    [bold]{kind}[/bold]")
        console.print(f"Source:  {source_path}")
        console.print(f"Class:   {preflight['source_class']}")
        console.print(f"Trust:   {preflight['trust_class']}")
        console.print(f"Status:  [bold]{preflight['initial_status']}[/bold]")
        
        if preflight["initial_status"] == "pending":
            console.print("\n[yellow]Note: This source will require manual approval before knowledge is projected.[/yellow]")
        
        if not Confirm.ask("\nProceed with ingestion?"):
            return
            
        job_id = source_service.create_source_ingestion_job(data_dir, persona_name, kind, source_path)
        with console.status(f"[cyan]Running ingestion job {job_id}...[/cyan]"):
            report = source_service.run_source_job(data_dir, persona_name, job_id)
            
        console.print(f"\n[green]✓ Source ingested successfully![/green]")
        console.print(f"Source ID: [bold]{report.source_id}[/bold]")
        console.print(f"Results:   {report.extracted_counts['viewpoints']} viewpoints, {report.extracted_counts['facts']} facts, {report.extracted_counts['timeline']} events")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def handle_persona_sources(args: argparse.Namespace) -> None:
    """List ingested source bundles."""
    persona_name = str(args.name).strip()
    status_filter = getattr(args, "status", None)
    kind_filter = getattr(args, "kind", None)
    limit = int(getattr(args, "limit", 20))
    data_dir = _get_data_dir()

    if not persona_exists(data_dir, persona_name):
        console.print(f"[red]Error: Persona '{persona_name}' does not exist.[/red]")
        return

    bundles = source_service.list_source_bundles_for_persona(data_dir, persona_name)
    
    if status_filter:
        bundles = [b for b in bundles if b.get("review_status") == status_filter]
    if kind_filter:
        bundles = [b for b in bundles if b.get("kind") == kind_filter]
        
    bundles = bundles[:limit]

    if not bundles:
        console.print("[yellow]No source bundles found.[/yellow]")
        return

    table = Table(title=f"Sources for {persona_name}")
    table.add_column("ID", style="cyan")
    table.add_column("Label")
    table.add_column("Kind")
    table.add_column("Status")
    table.add_column("Updated", style="dim")

    for b in bundles:
        status_style = "green" if b.get("review_status") == "approved" else "yellow"
        table.add_row(
            b.get("source_id"),
            b.get("label"),
            b.get("kind"),
            f"[{status_style}]{b.get('review_status')}[/{status_style}]",
            b.get("updated_at"),
        )

    console.print(table)


def handle_persona_source_report(args: argparse.Namespace) -> None:
    """Show ingestion report for a source bundle."""
    persona_name = str(args.name).strip()
    source_id = str(args.source_id).strip()
    data_dir = _get_data_dir()

    report = source_service.get_source_report(data_dir, persona_name, source_id)
    if not report:
        console.print(f"[red]Error: Report not found for source '{source_id}'.[/red]")
        return

    console.print(f"\n[bold cyan]Source Report: {source_id}[/bold cyan]")
    console.print(f"Kind:   {report['kind']}")
    console.print(f"Status: {report['status']}")
    
    console.print("\n[bold]Extracted Counts:[/bold]")
    for k, v in report['extracted_counts'].items():
        console.print(f"  {k:12} {v}")
        
    if report.get("stage_timings"):
        console.print("\n[bold]Stage Timings:[/bold]")
        for stage, duration in report['stage_timings'].items():
            console.print(f"  {stage:20} {duration:6.1f}s")


def handle_persona_approve_source(args: argparse.Namespace) -> None:
    """Approve a source bundle and project its knowledge."""
    persona_name = str(args.name).strip()
    source_id = str(args.source_id).strip()
    data_dir = _get_data_dir()

    if not Confirm.ask(f"Approve source '{source_id}' and project into '{persona_name}'?"):
        return

    try:
        source_service.approve_source_bundle(data_dir, persona_name, source_id)
        console.print(f"[green]✓ Source '{source_id}' approved and projected successfully.[/green]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def handle_persona_retract_source(args: argparse.Namespace) -> None:
    """Retract an approved source bundle."""
    persona_name = str(args.name).strip()
    source_id = str(args.source_id).strip()
    data_dir = _get_data_dir()

    if not Confirm.ask(f"Retract source '{source_id}' and remove from '{persona_name}' knowledge? (Bundle files will be kept)"):
        return

    try:
        source_service.retract_source_bundle(data_dir, persona_name, source_id)
        console.print(f"[green]✓ Source '{source_id}' retracted successfully.[/green]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def handle_persona_reject_source(args: argparse.Namespace) -> None:
    """Reject a source bundle."""
    persona_name = str(args.name).strip()
    source_id = str(args.source_id).strip()
    data_dir = _get_data_dir()

    if not Confirm.ask(f"Reject source '{source_id}'?"):
        return

    try:
        source_service.reject_source_bundle(data_dir, persona_name, source_id)
        console.print(f"[green]✓ Source '{source_id}' rejected.[/green]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def handle_persona_facts(args: argparse.Namespace) -> None:
    """Query approved facts."""
    persona_name = str(args.name).strip()
    source_id = getattr(args, "source", None)
    topic = getattr(args, "topic", None)
    limit = int(getattr(args, "limit", 20))
    data_dir = _get_data_dir()

    facts = source_service.query_approved_facts(data_dir, persona_name, source_id, topic=topic)
    facts = facts[:limit]

    if not facts:
        console.print("[yellow]No approved facts found.[/yellow]")
        return

    for f in facts:
        console.print(f"\n[bold cyan]Fact:[/bold cyan] {f.text}")
        if f.metadata.get("topic"):
            console.print(f"[dim]Topic: {f.metadata['topic']}[/dim]")
        console.print(f"[dim]Source: {f.source_id}[/dim]")


def handle_persona_timeline(args: argparse.Namespace) -> None:
    """Query approved timeline events."""
    persona_name = str(args.name).strip()
    source_id = getattr(args, "source", None)
    year = getattr(args, "year", None)
    topic = getattr(args, "topic", None)
    limit = int(getattr(args, "limit", 20))
    data_dir = _get_data_dir()

    events = source_service.query_approved_timeline(data_dir, persona_name, source_id, topic=topic)
    if year:
        events = [e for e in events if e.metadata.get("year") == int(year)]
    events = events[:limit]

    if not events:
        console.print("[yellow]No approved timeline events found.[/yellow]")
        return

    for e in events:
        year_label = f"[{e.metadata.get('year')}]" if e.metadata.get('year') else "[????]"
        console.print(f"\n[bold cyan]{year_label}[/bold cyan] {e.text}")
        console.print(f"[dim]Source: {e.source_id}[/dim]")


def handle_persona_conflicts(args: argparse.Namespace) -> None:
    """Query approved conflict groups."""
    persona_name = str(args.name).strip()
    source_id = getattr(args, "source", None)
    topic = getattr(args, "topic", None)
    limit = int(getattr(args, "limit", 20))
    data_dir = _get_data_dir()

    conflicts = source_service.query_approved_conflicts(data_dir, persona_name, source_id, topic=topic)
    conflicts = conflicts[:limit]

    if not conflicts:
        console.print("[yellow]No approved conflict groups found.[/yellow]")
        return

    for c in conflicts:
        console.print(f"\n[bold red]Conflict Topic: {c['topic']}[/bold red]")
        console.print(f"Description: {c['description']}")
        console.print(f"[dim]Source: {c.get('source_id')}[/dim]")


def handle_persona_rebuild_index(args: argparse.Namespace) -> None:
    """Manually rebuild the runtime index for a persona."""
    persona_name = str(args.name).strip()
    data_dir = _get_data_dir()

    if not persona_exists(data_dir, persona_name):
        console.print(f"[red]Error: Persona '{persona_name}' does not exist.[/red]")
        return

    try:
        from asky.plugins.manual_persona_creator.runtime_index import (
            rebuild_runtime_index,
        )
        from asky.plugins.manual_persona_creator.storage import get_persona_paths

        paths = get_persona_paths(data_dir, persona_name)

        with console.status(
            f"[cyan]Rebuilding runtime index for '{persona_name}'...[/cyan]"
        ):
            result = rebuild_runtime_index(paths.root_dir)

        if result.get("rebuilt"):
            console.print(f"[green]✓[/green] Runtime index rebuilt successfully.")
            console.print(f"  Indexed entries: {result.get('indexed_entries', 0)}")
        else:
            console.print(
                f"[red]Error rebuilding index: {result.get('reason', 'unknown')}[/red]"
            )

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
from asky.plugins.persona_manager.errors import (
    InvalidAliasError,
    InvalidPersonaPackageError,
    NoActiveSessionError,
    PersonaNotFoundError,
)
from asky.plugins.persona_manager.importer import import_persona_archive
from asky.plugins.persona_manager.resolver import (
    get_persona_aliases,
    list_all_aliases,
    remove_persona_alias,
    set_persona_alias,
)
from asky.plugins.persona_manager.session_binding import (
    get_session_binding,
    set_session_binding,
)
from asky.storage import get_session_by_id

console = Console()


def _get_data_dir() -> Path:
    """Get the plugin data directory."""
    return _get_config_dir() / "plugins"


def handle_persona_create(args: argparse.Namespace) -> None:
    """Create a new persona."""
    persona_name = str(args.name).strip()
    prompt_file = Path(args.prompt).expanduser()
    description = str(getattr(args, 'description', '')).strip()
    
    if not persona_name:
        console.print("[red]Error: Persona name is required[/red]")
        return
    
    if not prompt_file.exists():
        console.print(f"[red]Error: Prompt file not found: {prompt_file}[/red]")
        return
    
    data_dir = _get_data_dir()
    
    if persona_exists(data_dir, persona_name):
        console.print(f"[red]Error: Persona '{persona_name}' already exists[/red]")
        return
    
    try:
        behavior_prompt = prompt_file.read_text(encoding='utf-8')
        paths = create_persona(
            data_dir=data_dir,
            persona_name=persona_name,
            description=description,
            behavior_prompt=behavior_prompt,
        )
        console.print(f"[green]✓[/green] Created persona '[cyan]{persona_name}[/cyan]'")
        console.print(f"  Location: {paths.root_dir}")
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Error creating persona: {e}[/red]")


def handle_persona_add_sources(args: argparse.Namespace) -> None:
    """Add knowledge sources to an existing persona."""
    persona_name = str(args.name).strip()
    sources = getattr(args, 'sources', [])
    
    if not persona_name:
        console.print("[red]Error: Persona name is required[/red]")
        return
    
    if not sources:
        console.print("[red]Error: At least one source is required[/red]")
        return
    
    data_dir = _get_data_dir()
    
    if not persona_exists(data_dir, persona_name):
        console.print(f"[red]Error: Persona '{persona_name}' not found[/red]")
        available = list_persona_names(data_dir)
        if available:
            console.print(f"Available personas: {', '.join(available)}")
        return
    
    try:
        from asky.plugins.manual_persona_creator.source_service import add_manual_sources
        
        paths = get_persona_paths(data_dir, persona_name)
        
        console.print(f"[cyan]Ingesting {len(sources)} source(s)...[/cyan]")
        result = add_manual_sources(persona_root=paths.root_dir, sources=sources)
        
        if result.processed_sources > 0:
            console.print(f"[green]✓[/green] Added {result.processed_sources} new source(s) to '[cyan]{persona_name}[/cyan]'")
        
        if result.skipped_existing_sources > 0:
            console.print(f"[yellow]![/yellow] Skipped {result.skipped_existing_sources} source(s) that already exist in this persona")
            
        if result.added_chunks > 0:
            console.print(f"  Added {result.added_chunks} chunk(s)")
            
        if result.warning_count > 0:
            console.print(f"[yellow]Warnings ({result.warning_count}):[/yellow]")
            for warning in result.warnings:
                console.print(f"  - {warning}")
                
        if result.processed_sources == 0 and result.skipped_existing_sources == 0:
             console.print("[yellow]No sources were processed.[/yellow]")

    except Exception as e:
        console.print(f"[red]Error adding sources: {e}[/red]")


def handle_persona_import(args: argparse.Namespace) -> None:
    """Import a persona package from a ZIP file or directory."""
    import_path = str(args.path).strip()
    
    if not import_path:
        console.print("[red]Error: Import path is required[/red]")
        return
    
    path = Path(import_path).expanduser()
    
    if not path.exists():
        console.print(f"[red]Error: Path not found: {path}[/red]")
        return
    
    data_dir = _get_data_dir()
    
    try:
        if path.is_file() and path.suffix == '.zip':
            console.print(f"[cyan]Importing persona from ZIP: {path}[/cyan]")
            result = import_persona_archive(data_dir=data_dir, archive_path=str(path))
            console.print(f"[green]✓[/green] Imported persona '[cyan]{result['name']}[/cyan]'")
            console.print(f"  Chunks: {result['chunks']}")
            console.print(f"  Location: {result['path']}")
        else:
            console.print(f"[red]Error: Only ZIP file imports are currently supported[/red]")
            console.print(f"  Provided: {path}")
    except InvalidPersonaPackageError as e:
        console.print(f"[red]Error: {e}[/red]")
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Error importing persona: {e}[/red]")


def handle_persona_export(args: argparse.Namespace) -> None:
    """Export a persona package to a ZIP file."""
    persona_name = str(args.name).strip()
    output_path = getattr(args, 'output', None)
    
    if not persona_name:
        console.print("[red]Error: Persona name is required[/red]")
        return
    
    data_dir = _get_data_dir()
    
    if not persona_exists(data_dir, persona_name):
        console.print(f"[red]Error: Persona '{persona_name}' not found[/red]")
        available = list_persona_names(data_dir)
        if available:
            console.print(f"Available personas: {', '.join(available)}")
        return
    
    try:
        console.print(f"[cyan]Exporting persona '{persona_name}'...[/cyan]")
        result_path = export_persona_package(
            data_dir=data_dir,
            persona_name=persona_name,
            output_path=output_path,
        )
        console.print(f"[green]✓[/green] Exported persona '[cyan]{persona_name}[/cyan]'")
        console.print(f"  Output: {result_path}")
    except Exception as e:
        console.print(f"[red]Error exporting persona: {e}[/red]")


def handle_persona_load(args: argparse.Namespace) -> None:
    """Load a persona into the current session."""
    persona_name = str(args.name).strip()
    
    if not persona_name:
        console.print("[red]Error: Persona name is required[/red]")
        return
    
    data_dir = _get_data_dir()
    
    try:
        if not persona_exists(data_dir, persona_name):
            available = list_persona_names(data_dir)
            raise PersonaNotFoundError(
                persona_name,
                available_personas=available,
            )
        
        session_id = get_shell_session_id()
        if session_id is None:
            raise NoActiveSessionError("persona load")
        
        session = get_session_by_id(session_id)
        if session is None:
            console.print(f"[red]Error: Session {session_id} not found[/red]")
            return
        
        set_session_binding(
            data_dir,
            session_id=session_id,
            persona_name=persona_name,
        )
        
        session_name = session.name or f"#{session_id}"
        console.print(f"[green]✓[/green] Loaded persona '[cyan]{persona_name}[/cyan]' into session {session_name}")
    
    except PersonaNotFoundError as e:
        console.print(f"[red]Error: {e}[/red]")
    except NoActiveSessionError as e:
        console.print(f"[red]Error: {e}[/red]")


def handle_persona_unload(args: argparse.Namespace) -> None:
    """Unload the current persona from the session."""
    session_id = get_shell_session_id()
    if session_id is None:
        console.print("[red]Error: No active session[/red]")
        return
    
    data_dir = _get_data_dir()
    current_persona = get_session_binding(data_dir, session_id)
    
    if current_persona is None:
        console.print("[yellow]No persona is currently loaded[/yellow]")
        return
    
    set_session_binding(
        data_dir,
        session_id=session_id,
        persona_name=None,
    )
    
    console.print(f"[green]✓[/green] Unloaded persona '[cyan]{current_persona}[/cyan]'")


def handle_persona_current(args: argparse.Namespace) -> None:
    """Display the currently loaded persona."""
    session_id = get_shell_session_id()
    if session_id is None:
        console.print("[yellow]No active session[/yellow]")
        return
    
    data_dir = _get_data_dir()
    current_persona = get_session_binding(data_dir, session_id)
    
    if current_persona is None:
        console.print("[yellow]No persona is currently loaded[/yellow]")
        return
    
    try:
        paths = get_persona_paths(data_dir, current_persona)
        metadata = read_metadata(paths.metadata_path)
        description = metadata.get("persona", {}).get("description", "")
        
        console.print(f"\n[bold cyan]Current Persona:[/bold cyan] {current_persona}")
        if description:
            console.print(f"[dim]{description}[/dim]")
        
        prompt_text = read_prompt(paths.prompt_path)
        if prompt_text:
            preview = prompt_text[:200]
            if len(prompt_text) > 200:
                preview += "..."
            console.print(f"\n[bold]Behavior Prompt:[/bold]\n{preview}\n")
    except Exception as e:
        console.print(f"[red]Error reading persona details: {e}[/red]")


def handle_persona_list(args: argparse.Namespace) -> None:
    """List all available personas."""
    data_dir = _get_data_dir()
    personas = list_persona_names(data_dir)
    
    if not personas:
        console.print("[yellow]No personas available[/yellow]")
        console.print("Create one with: asky persona create <name> --prompt <file>")
        return
    
    session_id = get_shell_session_id()
    current_persona = None
    if session_id is not None:
        current_persona = get_session_binding(data_dir, session_id)
    
    table = Table(title="Available Personas", show_header=True, header_style="bold cyan")
    table.add_column("Name", style="white")
    table.add_column("Description", style="dim")
    table.add_column("Status", style="green")
    
    for persona_name in personas:
        try:
            paths = get_persona_paths(data_dir, persona_name)
            metadata = read_metadata(paths.metadata_path)
            description = metadata.get("persona", {}).get("description", "")
            
            if len(description) > 60:
                description = description[:57] + "..."
            
            status = "● Active" if persona_name == current_persona else ""
            table.add_row(persona_name, description, status)
        except Exception:
            table.add_row(persona_name, "[red]Error reading metadata[/red]", "")
    
    console.print(table)


def handle_persona_alias(args: argparse.Namespace) -> None:
    """Create an alias for a persona."""
    alias = str(args.alias).strip()
    persona_name = str(args.persona_name).strip()
    
    if not alias:
        console.print("[red]Error: Alias name is required[/red]")
        return
    
    if not persona_name:
        console.print("[red]Error: Persona name is required[/red]")
        return
    
    data_dir = _get_data_dir()
    kvstore = PluginKVStore("persona_manager")
    
    try:
        set_persona_alias(alias, persona_name, kvstore, data_dir)
        console.print(f"[green]✓[/green] Created alias '[cyan]{alias}[/cyan]' → '[cyan]{persona_name}[/cyan]'")
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        available = list_persona_names(data_dir)
        if available:
            console.print(f"Available personas: {', '.join(available)}")
    except InvalidAliasError as e:
        console.print(f"[red]Error: {e}[/red]")


def handle_persona_unalias(args: argparse.Namespace) -> None:
    """Remove a persona alias."""
    alias = str(args.alias).strip()
    
    if not alias:
        console.print("[red]Error: Alias name is required[/red]")
        return
    
    kvstore = PluginKVStore("persona_manager")
    
    removed = remove_persona_alias(alias, kvstore)
    
    if removed:
        console.print(f"[green]✓[/green] Removed alias '[cyan]{alias}[/cyan]'")
    else:
        console.print(f"[yellow]Alias '{alias}' does not exist[/yellow]")


def handle_persona_aliases(args: argparse.Namespace) -> None:
    """List all persona aliases or aliases for a specific persona."""
    persona_name = getattr(args, 'persona_name', None)
    
    data_dir = _get_data_dir()
    kvstore = PluginKVStore("persona_manager")
    
    if persona_name:
        persona_name = persona_name.strip()
        
        if not persona_exists(data_dir, persona_name):
            console.print(f"[red]Error: Persona '{persona_name}' not found[/red]")
            available = list_persona_names(data_dir)
            if available:
                console.print(f"Available personas: {', '.join(available)}")
            return
        
        aliases = get_persona_aliases(persona_name, kvstore)
        
        if not aliases:
            console.print(f"[yellow]No aliases for persona '{persona_name}'[/yellow]")
            return
        
        console.print(f"\n[bold cyan]Aliases for '{persona_name}':[/bold cyan]")
        for alias in aliases:
            console.print(f"  • {alias}")
    else:
        all_aliases = list_all_aliases(kvstore)
        
        if not all_aliases:
            console.print("[yellow]No aliases defined[/yellow]")
            console.print("Create one with: asky persona alias <alias> <persona_name>")
            return
        
        table = Table(title="Persona Aliases", show_header=True, header_style="bold cyan")
        table.add_column("Alias", style="white")
        table.add_column("→", style="dim", justify="center")
        table.add_column("Persona", style="cyan")
        
        for alias, target_persona in all_aliases:
            table.add_row(alias, "→", target_persona)
        
        console.print(table)


# --- Web Collection Handlers ---

def handle_persona_web_collect(args: argparse.Namespace) -> None:
    """Start a bounded seed-domain web collection."""
    persona_name = str(args.name).strip()
    target_results = int(args.target_results)
    urls = args.url or []
    url_file = Path(args.url_file) if args.url_file else None
    data_dir = _get_data_dir()

    if not persona_exists(data_dir, persona_name):
        console.print(f"[red]Error: Persona '{persona_name}' does not exist.[/red]")
        return

    try:
        with console.status(f"[cyan]Starting web collection for '{persona_name}'...[/cyan]"):
            collection_id = web_service.start_seed_domain_collection(
                data_dir=data_dir,
                persona_name=persona_name,
                target_results=target_results,
                urls=urls,
                url_file=url_file,
            )
        console.print(f"[green]✓ Web collection '{collection_id}' started successfully.[/green]")
        console.print(f"Use 'asky persona web-review {persona_name} {collection_id}' to check progress.")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def handle_persona_web_expand(args: argparse.Namespace) -> None:
    """Start a broad public-web expansion."""
    persona_name = str(args.name).strip()
    target_results = int(args.target_results)
    query = args.query
    urls = args.url or []
    url_file = Path(args.url_file) if args.url_file else None
    data_dir = _get_data_dir()

    if not persona_exists(data_dir, persona_name):
        console.print(f"[red]Error: Persona '{persona_name}' does not exist.[/red]")
        return

    try:
        with console.status(f"[cyan]Starting broad web expansion for '{persona_name}'...[/cyan]"):
            collection_id = web_service.start_broad_web_expansion(
                data_dir=data_dir,
                persona_name=persona_name,
                target_results=target_results,
                query=query,
                urls=urls,
                url_file=url_file,
            )
        console.print(f"[green]✓ Broad web expansion '{collection_id}' started successfully.[/green]")
        console.print(f"Use 'asky persona web-review {persona_name} {collection_id}' to check progress.")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def handle_persona_web_collections(args: argparse.Namespace) -> None:
    """List web collections for a persona."""
    persona_name = str(args.name).strip()
    status_filter = args.status
    limit = int(args.limit)
    data_dir = _get_data_dir()

    paths = get_persona_paths(data_dir, persona_name)
    from asky.plugins.manual_persona_creator.storage import list_web_collections, get_web_collection_paths
    import tomllib

    collection_ids = list_web_collections(paths.root_dir)
    collection_ids = collection_ids[-limit:]

    if not collection_ids:
        console.print("[yellow]No web collections found.[/yellow]")
        return

    table = Table(title=f"Web Collections for '{persona_name}'")
    table.add_column("Collection ID", style="cyan")
    table.add_column("Mode", style="magenta")
    table.add_column("Status", style="green")
    table.add_column("Target", justify="right")
    table.add_column("Created At", style="dim")

    for cid in reversed(collection_ids):
        c_paths = get_web_collection_paths(paths.root_dir, cid)
        if c_paths.manifest_path.exists():
            with c_paths.manifest_path.open("rb") as f:
                m = tomllib.load(f)
                if status_filter and m.get("status") != status_filter:
                    continue
                table.add_row(
                    cid,
                    m.get("mode", "unknown"),
                    m.get("status", "unknown"),
                    str(m.get("target_results", 0)),
                    m.get("created_at", "unknown")[:16],
                )

    console.print(table)


def handle_persona_web_review(args: argparse.Namespace) -> None:
    """Review pages in a web collection."""
    persona_name = str(args.name).strip()
    collection_id = str(args.collection_id).strip()
    status_filter = args.status
    limit = int(args.limit)
    data_dir = _get_data_dir()

    pages = web_service.get_collection_review_pages(
        data_dir=data_dir,
        persona_name=persona_name,
        collection_id=collection_id,
        status=status_filter,
    )
    pages = pages[:limit]

    if not pages:
        console.print(f"[yellow]No pages found for collection '{collection_id}'.[/yellow]")
        return

    table = Table(title=f"Web Pages for Collection '{collection_id}'")
    table.add_column("Page ID", style="cyan")
    table.add_column("Title", style="bold")
    table.add_column("Status", style="green")
    table.add_column("Classification", style="magenta")
    table.add_column("Final URL", style="dim")

    for p in pages:
        table.add_row(
            p.get("page_id", "unknown"),
            p.get("title", "No Title")[:50],
            p.get("status", "unknown"),
            p.get("classification", "unknown"),
            p.get("final_url", "unknown")[:40],
        )

    console.print(table)


def handle_persona_web_page_report(args: argparse.Namespace) -> None:
    """Show detailed report for a scraped page."""
    persona_name = str(args.name).strip()
    collection_id = str(args.collection_id).strip()
    page_id = str(args.page_id).strip()
    data_dir = _get_data_dir()

    paths = get_persona_paths(data_dir, persona_name)
    from asky.plugins.manual_persona_creator.storage import (
        get_web_collection_paths, 
        get_web_page_paths,
        read_web_page_report
    )
    import tomllib

    c_paths = get_web_collection_paths(paths.root_dir, collection_id)
    p_paths = get_web_page_paths(c_paths.collection_dir, page_id)

    if not p_paths.manifest_path.exists():
        console.print(f"[red]Error: Page '{page_id}' not found in collection '{collection_id}'.[/red]")
        return

    with p_paths.manifest_path.open("rb") as f:
        m = tomllib.load(f)
    
    report = read_web_page_report(p_paths.report_path)
    
    console.print(f"\n[bold cyan]Web Page Report: {page_id}[/bold cyan]")
    console.print(f"Title: {m.get('title')}")
    console.print(f"Status: {m.get('status')}")
    console.print(f"Final URL: {m.get('final_url')}")
    console.print(f"Classification: {m.get('classification')}")
    
    if report.get("retrieval"):
        ret = report["retrieval"]
        console.print(f"\n[bold]Retrieval Provenance:[/bold]")
        console.print(f"  Provider: {ret.get('provider')}")
        console.print(f"  Source:   {ret.get('source')}")
        if ret.get("fallback_reason"):
            console.print(f"  Fallback: [yellow]{ret.get('fallback_reason')}[/yellow]")
        if ret.get("error"):
            console.print(f"  Error:    [red]{ret.get('error')}[/red]")

    if p_paths.preview_path.exists():
        preview = json.loads(p_paths.preview_path.read_text(encoding="utf-8"))
        console.print(f"\n[bold]Summary:[/bold] {preview.get('short_summary')}")
        
        if preview.get("candidate_viewpoints"):
            console.print("\n[bold]Candidate Viewpoints:[/bold]")
            for vp in preview["candidate_viewpoints"]:
                console.print(f"  • {vp.get('viewpoint')}")
        
        if preview.get("candidate_facts"):
            console.print("\n[bold]Candidate Facts:[/bold]")
            for f in preview["candidate_facts"]:
                console.print(f"  • {f.get('fact')}")

        if preview.get("candidate_timeline_events"):
            console.print("\n[bold]Candidate Timeline Events:[/bold]")
            for ev in preview["candidate_timeline_events"]:
                console.print(f"  • {ev.get('event')}")

        if preview.get("conflict_candidates"):
            console.print("\n[bold]Conflict Candidates:[/bold]")
            for c in preview["conflict_candidates"]:
                console.print(f"  • {c.get('description')}")

    if p_paths.content_path.exists():
        content = p_paths.content_path.read_text(encoding="utf-8")
        console.print(f"\n[bold]Content Preview (First 500 chars):[/bold]")
        console.print(content[:500] + "...")


def handle_persona_web_continue(args: argparse.Namespace) -> None:
    """Continue an existing web collection."""
    persona_name = str(args.name).strip()
    collection_id = str(args.collection_id).strip()
    data_dir = _get_data_dir()

    try:
        with console.status(f"[cyan]Continuing web collection '{collection_id}'...[/cyan]"):
            web_service.continue_collection(
                data_dir=data_dir,
                persona_name=persona_name,
                collection_id=collection_id,
            )
        console.print(f"[green]✓ Web collection '{collection_id}' resumed and finished batch.[/green]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def handle_persona_web_approve_page(args: argparse.Namespace) -> None:
    """Approve a scraped page and project into persona knowledge."""
    persona_name = str(args.name).strip()
    collection_id = str(args.collection_id).strip()
    page_id = str(args.page_id).strip()
    trust_as = args.trust_as
    data_dir = _get_data_dir()

    if not Confirm.ask(f"Approve page '{page_id}' and project into '{persona_name}'?"):
        return

    try:
        from asky.plugins.manual_persona_creator.web_service import approve_web_page
        approve_web_page(
            data_dir=data_dir,
            persona_name=persona_name,
            collection_id=collection_id,
            page_id=page_id,
            trust_as=trust_as,
        )
        console.print(f"[green]✓ Page '{page_id}' approved and projected successfully.[/green]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def handle_persona_web_retract_page(args: argparse.Namespace) -> None:
    """Retract an approved scraped page."""
    persona_name = str(args.name).strip()
    collection_id = str(args.collection_id).strip()
    page_id = str(args.page_id).strip()
    data_dir = _get_data_dir()

    try:
        from asky.plugins.manual_persona_creator.web_service import retract_web_page
        retract_web_page(
            data_dir=data_dir,
            persona_name=persona_name,
            collection_id=collection_id,
            page_id=page_id,
        )
        console.print(f"[green]✓ Page '{page_id}' retracted back to review_ready.[/green]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


def handle_persona_web_reject_page(args: argparse.Namespace) -> None:
    """Reject a scraped page."""
    persona_name = str(args.name).strip()
    collection_id = str(args.collection_id).strip()
    page_id = str(args.page_id).strip()
    data_dir = _get_data_dir()

    try:
        from asky.plugins.manual_persona_creator.web_service import reject_web_page
        reject_web_page(
            data_dir=data_dir,
            persona_name=persona_name,
            collection_id=collection_id,
            page_id=page_id,
        )
        console.print(f"[green]✓ Page '{page_id}' rejected.[/green]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
