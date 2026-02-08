"""Chat implementation for asky CLI."""

import argparse
import logging
import time
from typing import Any, List, Dict, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from asky.config import MODELS, LIVE_BANNER
from asky.core import (
    ConversationEngine,
    create_default_tool_registry,
    create_research_tool_registry,
    UsageTracker,
    construct_system_prompt,
    construct_research_system_prompt,
    generate_summaries,
    SessionManager,
    get_shell_session_id,
    set_shell_session_id,
)
from asky.storage import (
    get_history,
    get_interaction_context,
    save_interaction,
)
from asky.cli.display import InterfaceRenderer
from asky.research.source_shortlist import (
    shortlist_prompt_sources,
    format_shortlist_context,
)

logger = logging.getLogger(__name__)


def load_context(continue_ids: str, summarize: bool) -> Optional[str]:
    """Load context from previous interactions."""
    console = Console()
    try:
        raw_ids = [x.strip() for x in continue_ids.split(",")]
        resolved_ids = []
        relative_indices = []

        for raw_id in raw_ids:
            if raw_id.startswith("~"):
                try:
                    rel_val = int(raw_id[1:])
                    if rel_val < 1:
                        console.print(
                            f"[bold red]Error:[/] Relative ID must be >= 1 (got {raw_id})"
                        )
                        return None
                    relative_indices.append(rel_val)
                except ValueError:
                    console.print(
                        f"[bold red]Error:[/] Invalid relative ID format: {raw_id}"
                    )
                    return None
            else:
                resolved_ids.append(int(raw_id))

        if relative_indices:
            max_depth = max(relative_indices)
            history_rows = get_history(limit=max_depth)

            for rel_val in relative_indices:
                list_index = rel_val - 1
                if list_index < len(history_rows):
                    real_id = history_rows[list_index][0]
                    resolved_ids.append(real_id)
                else:
                    console.print(
                        "[bold red]Error:[/] "
                        f"Relative ID {rel_val} is out of range "
                        f"(only {len(history_rows)} records available)."
                    )
                    return None

        resolved_ids = sorted(list(set(resolved_ids)))
        full_content = not summarize
        context_str = get_interaction_context(resolved_ids, full=full_content)
        if context_str:
            console.print(
                f"\n[Loaded context from IDs: {', '.join(map(str, resolved_ids))}]"
            )
        return context_str
    except ValueError:
        console.print(
            "[bold red]Error:[/] Invalid format for -c/--continue-chat. "
            "Use comma-separated integers or ~N for relative."
        )
        return None


def build_messages(
    args: argparse.Namespace,
    context_str: str,
    query_text: str,
    session_manager: Optional[SessionManager] = None,
    research_mode: bool = False,
    source_shortlist_context: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Build the initial message list for the conversation."""
    # Use research prompt if in research mode
    if research_mode:
        system_prompt = construct_research_system_prompt()
    else:
        system_prompt = construct_system_prompt()

    messages = [
        {
            "role": "system",
            "content": system_prompt,
        },
    ]

    if session_manager:
        messages.extend(session_manager.build_context_messages())
    elif context_str:
        messages.append(
            {
                "role": "user",
                "content": f"Context from previous queries:\n{context_str}\n\nMy new query is below.",
            }
        )

    user_content = query_text
    if source_shortlist_context:
        user_content = (
            f"{query_text}\n\n"
            f"Pre-ranked sources gathered before tool calls:\n"
            f"{source_shortlist_context}\n\n"
            "Use this shortlist as a starting point, then verify with tools before citing."
        )

    messages.append({"role": "user", "content": user_content})
    return messages


def _build_shortlist_banner_stats(
    shortlist_payload: Dict[str, Any], shortlist_elapsed_ms: float
) -> Dict[str, Any]:
    """Extract compact shortlist stats for banner rendering."""
    stats = shortlist_payload.get("stats", {})
    metrics = stats.get("metrics", {}) if isinstance(stats, dict) else {}

    return {
        "enabled": bool(shortlist_payload.get("enabled")),
        "collected": int(metrics.get("candidate_deduped", 0) or 0),
        "processed": int(metrics.get("fetch_calls", 0) or 0),
        "selected": len(shortlist_payload.get("candidates", []) or []),
        "warnings": len(shortlist_payload.get("warnings", []) or []),
        "elapsed_ms": float(shortlist_elapsed_ms),
    }


def _print_shortlist_verbose(console: Console, shortlist_payload: Dict[str, Any]) -> None:
    """Render shortlist processing/selection trace for verbose terminal output."""
    if not shortlist_payload.get("enabled"):
        console.print(
            Panel(
                "Shortlist disabled for current mode.",
                title="Pre-LLM Shortlist",
                border_style="yellow",
            )
        )
        return

    trace = shortlist_payload.get("trace", {}) or {}
    processed = trace.get("processed_candidates", []) or []
    selected = shortlist_payload.get("candidates", []) or []

    processed_table = Table(
        title="Shortlist Processed Links",
        show_header=True,
        header_style="bold cyan",
    )
    processed_table.add_column("#", justify="right", style="dim", width=4)
    processed_table.add_column("Source", style="magenta", width=10)
    processed_table.add_column("URL", style="white")

    if processed:
        for idx, item in enumerate(processed, start=1):
            processed_table.add_row(
                str(idx),
                str(item.get("source_type", "")),
                str(item.get("url", "")),
            )
    else:
        processed_table.add_row("-", "-", "No links were processed.")

    selected_table = Table(
        title="Shortlist Selected Links Passed To Model Context",
        show_header=True,
        header_style="bold green",
    )
    selected_table.add_column("Rank", justify="right", width=5)
    selected_table.add_column("Score", justify="right", width=8)
    selected_table.add_column("Source", style="magenta", width=10)
    selected_table.add_column("URL", style="white")

    if selected:
        for item in selected:
            selected_table.add_row(
                str(item.get("rank", "")),
                f"{float(item.get('final_score', 0.0)):.3f}",
                str(item.get("source_type", "")),
                str(item.get("url", "")),
            )
    else:
        selected_table.add_row("-", "-", "-", "No links selected.")

    console.print(processed_table)
    console.print(selected_table)

    warnings = shortlist_payload.get("warnings", []) or []
    if warnings:
        warning_text = "\n".join(f"- {warning}" for warning in warnings[:8])
        console.print(
            Panel(
                warning_text,
                title=f"Shortlist Warnings ({len(warnings)})",
                border_style="yellow",
            )
        )


def run_chat(args: argparse.Namespace, query_text: str) -> None:
    """Run the chat conversation flow."""
    from asky.core import clear_shell_session
    console = Console()

    # Handle Context
    context_str = ""
    if args.continue_ids:
        context_str = load_context(args.continue_ids, args.summarize)
        if context_str is None:
            return

    # Initialize Components
    usage_tracker = UsageTracker()
    summarization_tracker = UsageTracker()
    model_config = MODELS[args.model]

    # Handle Sessions
    session_manager = None
    shell_session_id = get_shell_session_id()

    # Explicit session create (-ss)
    if getattr(args, "sticky_session", None):
        session_name = " ".join(args.sticky_session)
        session_manager = SessionManager(
            model_config, usage_tracker, summarization_tracker=summarization_tracker
        )
        s = session_manager.create_session(session_name)
        set_shell_session_id(s.id)
        console.print(f"\n[Session {s.id} ('{s.name}') created and active]")
        return

    # Explicit session resume (-rs)
    elif getattr(args, "resume_session", None):
        search_term = " ".join(args.resume_session)
        session_manager = SessionManager(
            model_config, usage_tracker, summarization_tracker=summarization_tracker
        )
        matches = session_manager.find_sessions(search_term)

        if not matches:
            console.print(f"[bold red]Error:[/] No sessions found matching '{search_term}'")
            return
        elif len(matches) > 1:
            console.print(f"Multiple sessions found for '{search_term}':")
            for s in matches:
                console.print(f"  {s.id}: {s.name or '(no name)'} ({s.created_at})")
            return
        else:
            s = matches[0]
            session_manager.current_session = s
            set_shell_session_id(s.id)
            console.print(f"\n[Resumed session {s.id} ('{s.name or 'auto'}')]")
            if not query_text:
                return

    # Auto-resume from shell lock file
    elif shell_session_id:
        session_manager = SessionManager(
            model_config, usage_tracker, summarization_tracker=summarization_tracker
        )
        session = session_manager.repo.get_session_by_id(shell_session_id)
        if session:
            session_manager.current_session = session
            console.print(f"\n[Resuming session {session.id} ({session.name or 'auto'})]")
        else:
            # Lock file points to deleted session, clear it
            clear_shell_session()
            session_manager = None

    # Check for research mode
    research_mode = getattr(args, "research", False)
    if research_mode:
        console.print("\n[Research mode enabled - using link extraction and RAG tools]")

    # Setup display renderer early so pre-LLM shortlist work is visible in banner
    renderer = InterfaceRenderer(
        model_config=model_config,
        model_alias=args.model,
        usage_tracker=usage_tracker,
        summarization_tracker=summarization_tracker,
        session_manager=session_manager,
        messages=[],
        research_mode=research_mode,
    )
    if LIVE_BANNER:
        renderer.start_live()
        renderer.update_banner(0, status_message="Shortlist: starting pre-LLM retrieval")

    def shortlist_status_reporter(message: str) -> None:
        if LIVE_BANNER and message:
            renderer.update_banner(0, status_message=message)

    shortlist_context: Optional[str] = None
    try:
        shortlist_start = time.perf_counter()
        shortlist_payload = shortlist_prompt_sources(
            user_prompt=query_text,
            research_mode=research_mode,
            status_callback=shortlist_status_reporter if LIVE_BANNER else None,
        )
        shortlist_elapsed = (time.perf_counter() - shortlist_start) * 1000
    except Exception:
        renderer.stop_live()
        raise
    shortlist_banner_stats = _build_shortlist_banner_stats(
        shortlist_payload, shortlist_elapsed
    )
    renderer.set_shortlist_stats(shortlist_banner_stats)

    if shortlist_payload.get("enabled"):
        shortlist_context = format_shortlist_context(shortlist_payload)
        logger.debug(
            "chat shortlist mode=%s enabled=%s candidates=%d warnings=%d context_len=%d elapsed=%.2fms",
            "research" if research_mode else "standard",
            shortlist_payload.get("enabled"),
            len(shortlist_payload.get("candidates", [])),
            len(shortlist_payload.get("warnings", [])),
            len(shortlist_context or ""),
            shortlist_elapsed,
        )
    else:
        logger.debug(
            "chat shortlist mode=%s enabled=%s elapsed=%.2fms",
            "research" if research_mode else "standard",
            shortlist_payload.get("enabled"),
            shortlist_elapsed,
        )
    if LIVE_BANNER:
        warnings_count = len(shortlist_payload.get("warnings", []) or [])
        status_msg = (
            f"Shortlist ready: {shortlist_banner_stats['selected']} selected "
            f"in {shortlist_elapsed:.0f}ms"
        )
        if warnings_count > 0:
            status_msg += f" ({warnings_count} warning(s))"
        renderer.update_banner(0, status_message=status_msg)

    if args.verbose:
        verbose_console = (
            renderer.live.console if LIVE_BANNER and renderer.live else renderer.console
        )
        _print_shortlist_verbose(verbose_console, shortlist_payload)
    if LIVE_BANNER:
        renderer.update_banner(0, status_message=None)

    messages = build_messages(
        args,
        context_str,
        query_text,
        session_manager=session_manager,
        research_mode=research_mode,
        source_shortlist_context=shortlist_context,
    )
    renderer.messages = messages

    # Create display callback for live banner mode
    def display_callback(
        current_turn: int,
        status_message: Optional[str] = None,
        is_final: bool = False,
        final_answer: Optional[str] = None,
    ):
        if is_final:
            # Stop the Live display before printing final answer
            renderer.stop_live()
            if final_answer:
                renderer.print_final_answer(final_answer)
        else:
            # Update banner in-place
            renderer.update_banner(current_turn, status_message)

    def verbose_output_callback(renderable: Any) -> None:
        """Route verbose output through the active live console when present."""
        if LIVE_BANNER and renderer.live:
            renderer.live.console.print(renderable)
            return
        renderer.console.print(renderable)

    # Wrap in try/finally to ensure renderer.stop_live() is called
    try:
        # Handle Terminal Context
        # Check if requested via flag OR configured default
        # from asky.config import TERMINAL_CONTEXT_LINES

        # Determine effective lines count
        if args.terminal_lines is not None:
            lines_count = args.terminal_lines
        else:
            lines_count = 0

        if lines_count > 0:
            from asky.cli.terminal import inject_terminal_context

            # Warn if the flag was explicitly provided but failed.
            warn_on_error = args.terminal_lines is not None

            # Use banner callback if live mode is active
            status_cb = lambda msg: (
                renderer.update_banner(0, status_message=msg) if LIVE_BANNER else None
            )

            inject_terminal_context(
                messages,
                lines_count,
                verbose=args.verbose,
                warn_on_error=warn_on_error,
                status_callback=status_cb,
            )

            # Clear status after context fetch
            if LIVE_BANNER:
                renderer.update_banner(0, status_message=None)

        # Use research registry if in research mode, otherwise default
        if research_mode:
            registry = create_research_tool_registry(usage_tracker=usage_tracker)
        else:
            registry = create_default_tool_registry(
                usage_tracker=usage_tracker, summarization_tracker=summarization_tracker
            )

        engine = ConversationEngine(
            model_config=model_config,
            tool_registry=registry,
            summarize=args.summarize,
            verbose=args.verbose,
            usage_tracker=usage_tracker,
            open_browser=args.open,
            session_manager=session_manager,
            verbose_output_callback=verbose_output_callback,
        )

        # Run loop
        display_cb = display_callback if LIVE_BANNER else None
        final_answer = engine.run(messages, display_callback=display_cb)

        # Save Interaction
        if final_answer:
            console.print("\n[Saving interaction...]")
            query_summary, answer_summary = generate_summaries(
                query_text,
                final_answer,
                usage_tracker=summarization_tracker,
            )

            # Save to session if active (session mode handles its own storage)
            if session_manager:
                session_manager.save_turn(
                    query_text, final_answer, query_summary, answer_summary
                )
                if session_manager.check_and_compact():
                    console.print("[Session context compacted]")
            else:
                # Save to global history (non-session mode only)
                save_interaction(
                    query_text, final_answer, args.model, query_summary, answer_summary
                )

        # Auto-generate HTML Report
        if final_answer:
            from asky.rendering import save_html_report

            html_source = ""
            if session_manager and session_manager.current_session:
                # Generate full session transcript
                try:
                    msgs = session_manager.repo.get_session_messages(
                        session_manager.current_session.id
                    )
                    transcript_parts = []
                    for m in msgs:
                        role_title = "User" if m.role == "user" else "Assistant"
                        transcript_parts.append(f"## {role_title}\n\n{m.content}")
                    html_source = "\n\n---\n\n".join(transcript_parts)
                except Exception as e:
                    console.print(
                        f"[bold red]Error:[/] fetching session messages for HTML report: {e}"
                    )
                    html_source = f"## Query\n{query_text}\n\n## Answer\n{final_answer}"
            else:
                # Single turn report
                html_source = f"## Query\n{query_text}\n\n## Answer\n{final_answer}"

            report_path = save_html_report(html_source)
            if report_path:
                console.print(f"Open in browser: [bold cyan]file://{report_path}[/]")

        # Send Email if requested
        if final_answer and getattr(args, "mail_recipients", None):
            from asky.email_sender import send_email

            recipients = [x.strip() for x in args.mail_recipients.split(",")]
            email_subject = args.subject or f"asky Result: {query_text[:50]}"
            send_email(recipients, email_subject, final_answer)

        # Push data to configured endpoint if requested
        if final_answer and getattr(args, "push_data_endpoint", None):
            from asky.push_data import execute_push_data

            dynamic_args = dict(args.push_params) if args.push_params else {}
            result = execute_push_data(
                args.push_data_endpoint,
                dynamic_args=dynamic_args,
                query=query_text,
                answer=final_answer,
                model=args.model,
            )
            if result["success"]:
                console.print(
                    f"[Push data successful: {result['endpoint']} - {result['status_code']}]"
                )
            else:
                console.print(
                    f"[Push data failed: {result['endpoint']} - {result['error']}]"
                )

    except KeyboardInterrupt:
        console.print("\nAborted by user.")
    except Exception as e:
        console.print(f"\n[bold red]An error occurred:[/] {e}")
        if args.verbose:
            import traceback

            traceback.print_exc()
    finally:
        # Ensure Live is stopped on any exit path
        renderer.stop_live()
