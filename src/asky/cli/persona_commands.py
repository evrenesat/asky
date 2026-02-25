"""CLI handlers for persona management commands."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table

from asky.config.loader import _get_config_dir
from asky.core import get_shell_session_id
from asky.plugins.kvstore import PluginKVStore
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
        from asky.research.ingestion import ingest_sources
        from asky.plugins.persona_manager.knowledge import rebuild_embeddings
        
        paths = get_persona_paths(data_dir, persona_name)
        existing_chunks = read_chunks(paths.chunks_path)
        
        console.print(f"[cyan]Ingesting {len(sources)} source(s)...[/cyan]")
        new_chunks = ingest_sources(sources)
        
        all_chunks = existing_chunks + new_chunks
        write_chunks(paths.chunks_path, all_chunks)
        
        console.print("[cyan]Rebuilding embeddings...[/cyan]")
        stats = rebuild_embeddings(persona_dir=paths.root_dir, chunks=all_chunks)
        
        touch_updated_at(paths.metadata_path)
        
        console.print(f"[green]✓[/green] Added {len(new_chunks)} chunk(s) to persona '[cyan]{persona_name}[/cyan]'")
        console.print(f"  Total chunks: {stats['embedded_chunks']}")
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
