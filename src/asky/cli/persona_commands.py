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
from asky.plugins.manual_persona_creator import book_service
from asky.plugins.manual_persona_creator.book_ingestion import BookIngestionJob
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
    target_topic = getattr(args, "topic", None)
    limit = int(getattr(args, "limit", 20))
    data_dir = _get_data_dir()

    if not persona_exists(data_dir, persona_name):
        console.print(f"[red]Error: Persona '{persona_name}' does not exist.[/red]")
        return

    viewpoints = book_service.query_authored_viewpoints(
        data_dir=data_dir,
        persona_name=persona_name,
        book_key=target_book,
        topic_query=target_topic,
        limit=limit
    )

    if not viewpoints:
        console.print("[yellow]No viewpoints found matching criteria.[/yellow]")
        return

    for v in viewpoints:
        console.print(f"\n[bold cyan]Topic: {v.topic}[/bold cyan] (Conf: {v.confidence:.2f})")
        console.print(f"[bold]Claim:[/bold] {v.claim}")
        console.print(f"[dim]Source: {v.book_title} ({v.publication_year})[/dim]")
        
        if v.evidence:
            console.print("[italic]Evidence:[/italic]")
            for e in v.evidence:
                console.print(f"- {e.excerpt} [{e.section_ref}]")

    if len(viewpoints) >= limit:
        console.print(f"\n[dim]... showing {limit} viewpoints. Use --limit to see more.[/dim]")
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
