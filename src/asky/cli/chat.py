"""Chat implementation for asky CLI."""

from __future__ import annotations
import argparse
import logging
import time
from typing import Any, List, Dict, Optional, Set, TYPE_CHECKING

from rich.console import Console

if TYPE_CHECKING:
    from asky.api.types import PreloadResolution
from rich.panel import Panel
from rich.table import Table

from asky.config import (
    MODELS,
    LIVE_BANNER,
)
from asky.api import AskyClient, AskyConfig, AskyTurnRequest, ContextOverflowError
from asky.api.context import load_context_from_history
from asky.api.preload import (
    build_shortlist_stats as api_build_shortlist_stats,
    combine_preloaded_source_context as api_combine_preloaded_source_context,
    shortlist_enabled_for_request as api_shortlist_enabled_for_request,
)
from asky.core import (
    ConversationEngine,
    UsageTracker,
    construct_system_prompt,
    construct_research_system_prompt,
    generate_summaries,
    SessionManager,
    get_shell_session_id,
    set_shell_session_id,
    append_research_guidance,
)
from asky.storage import (
    get_history,
    get_interaction_context,
    save_interaction,
)
from asky.cli.display import InterfaceRenderer
from asky.lazy_imports import call_attr
from asky.core.session_manager import generate_session_name

logger = logging.getLogger(__name__)
BACKGROUND_SUMMARY_DRAIN_STATUS = "Finalizing background page summaries..."


def shortlist_prompt_sources(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Lazy-import shortlist pipeline so startup cost is paid only when enabled."""
    return call_attr(
        "asky.research.source_shortlist", "shortlist_prompt_sources", *args, **kwargs
    )


def preload_local_research_sources(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Lazy-import local ingestion flow to keep startup fast for non-research chats."""
    return call_attr(
        "asky.cli.local_ingestion_flow",
        "preload_local_research_sources",
        *args,
        **kwargs,
    )


def format_shortlist_context(shortlist_payload: Dict[str, Any]) -> str:
    """Lazy-import shortlist formatter for same startup behavior as shortlist collection."""
    return call_attr(
        "asky.research.source_shortlist",
        "format_shortlist_context",
        shortlist_payload,
    )


def format_local_ingestion_context(local_payload: Dict[str, Any]) -> Optional[str]:
    """Lazy-import local-ingestion context formatter."""
    return call_attr(
        "asky.cli.local_ingestion_flow",
        "format_local_ingestion_context",
        local_payload,
    )


def load_context(continue_ids: str, summarize: bool) -> Optional[str]:
    """Load context from previous interactions."""
    console = Console()

    try:
        resolution = load_context_from_history(
            continue_ids,
            summarize,
            get_history_fn=get_history,
            get_interaction_context_fn=get_interaction_context,
        )
        if resolution.context_str:
            console.print(
                f"\n[Loaded context from IDs: {', '.join(map(str, resolution.resolved_ids))}]"
            )
        return resolution.context_str
    except ValueError as exc:
        message = str(exc)
        if message.startswith("Invalid continue IDs format"):
            console.print(
                "[bold red]Error:[/] Invalid format for -c/--continue-chat. "
                "Use comma-separated IDs, completion selector tokens, or ~N for relative."
            )
        else:
            console.print(f"[bold red]Error:[/] {message}")
        return None


def build_messages(
    args: argparse.Namespace,
    context_str: str,
    query_text: str,
    session_manager: Optional[SessionManager] = None,
    research_mode: bool = False,
    preload: Optional[PreloadResolution] = None,
    local_kb_hint_enabled: bool = False,
    system_prompt_override: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Build the initial message list for the conversation."""
    # Use research prompt if in research mode
    if system_prompt_override:
        system_prompt = system_prompt_override
    elif research_mode:
        system_prompt = construct_research_system_prompt()
        system_prompt = append_research_guidance(
            system_prompt,
            corpus_preloaded=preload.is_corpus_preloaded if preload else False,
            local_kb_hint_enabled=local_kb_hint_enabled,
        )
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
    if preload and preload.combined_context:
        user_content = (
            f"{query_text}\n\n"
            f"Preloaded sources gathered before tool calls:\n"
            f"{preload.combined_context}\n\n"
            "Use this preloaded corpus as a starting point, then verify with tools before citing."
        )

    messages.append({"role": "user", "content": user_content})
    return messages


def _build_shortlist_banner_stats(
    shortlist_payload: Dict[str, Any], shortlist_elapsed_ms: float
) -> Dict[str, Any]:
    """Extract compact shortlist stats for banner rendering."""
    return api_build_shortlist_stats(shortlist_payload, shortlist_elapsed_ms)


def _shortlist_enabled_for_request(
    args: argparse.Namespace,
    model_config: Dict[str, Any],
    research_mode: bool,
) -> tuple[bool, str]:
    """Resolve shortlist enablement with precedence: lean > model > global flags."""
    return api_shortlist_enabled_for_request(
        lean=bool(getattr(args, "lean", False)),
        model_config=model_config,
        research_mode=research_mode,
    )


def _parse_disabled_tools(raw_values: Optional[List[str]]) -> Set[str]:
    """Parse repeated/comma-separated --tool-off values into unique tool names."""
    disabled_tools: Set[str] = set()
    for raw_value in raw_values or []:
        for token in str(raw_value).split(","):
            tool_name = token.strip()
            if tool_name:
                disabled_tools.add(tool_name)

    if "all" in disabled_tools:
        from asky.core.tool_registry_factory import get_all_available_tool_names

        return set(get_all_available_tool_names())

    return disabled_tools


def _append_enabled_tool_guidelines(
    messages: List[Dict[str, str]], tool_guidelines: List[str]
) -> None:
    """Append enabled-tool guidance block to the system prompt."""
    if not tool_guidelines:
        return
    if not messages or messages[0].get("role") != "system":
        return

    guideline_lines = [
        "",
        "Enabled Tool Guidelines:",
        *[f"- {guideline}" for guideline in tool_guidelines],
    ]
    messages[0]["content"] = f"{messages[0].get('content', '')}\n" + "\n".join(
        guideline_lines
    )


def _ensure_research_session(
    session_manager: Optional[SessionManager],
    model_config: Dict[str, Any],
    usage_tracker: UsageTracker,
    summarization_tracker: UsageTracker,
    query_text: str,
    console: Console,
) -> SessionManager:
    """Ensure research mode always has an active session for memory isolation."""
    if session_manager and session_manager.current_session:
        return session_manager

    active_manager = session_manager or SessionManager(
        model_config,
        usage_tracker,
        summarization_tracker=summarization_tracker,
    )
    session_name = generate_session_name(query_text or "research")
    session = active_manager.create_session(session_name)
    set_shell_session_id(session.id)
    console.print(
        f"\n[Research mode: started session {session.id} ('{session.name or 'auto'}')]"
    )
    return active_manager


def _print_shortlist_verbose(
    console: Console, shortlist_payload: Dict[str, Any]
) -> None:
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


def _combine_preloaded_source_context(
    *context_blocks: Optional[str],
) -> Optional[str]:
    """Merge multiple preloaded-source context blocks into one message section."""
    return api_combine_preloaded_source_context(*context_blocks)


def _drain_research_background_summaries() -> None:
    """Wait for pending research cache background summaries."""
    try:
        from asky.research.cache import ResearchCache

        ResearchCache().wait_for_background_summaries()
    except Exception as exc:
        logger.debug("Skipping background summary drain: %s", exc)


def run_chat(args: argparse.Namespace, query_text: str) -> None:
    """Run the chat conversation flow."""
    from asky.core import clear_shell_session
    from asky.storage.sqlite import SQLiteHistoryRepository

    console = Console()

    usage_tracker = UsageTracker()
    summarization_tracker = UsageTracker()
    model_config = MODELS[args.model]
    research_mode = bool(getattr(args, "research", False))
    local_corpus = getattr(args, "local_corpus", None)
    if local_corpus:
        research_mode = True

    disabled_tools = _parse_disabled_tools(getattr(args, "tool_off", []))

    is_lean = bool(getattr(args, "lean", False))
    if is_lean:
        from asky.core.tool_registry_factory import get_all_available_tool_names

        # In lean mode, disable ALL tools
        all_tools = get_all_available_tool_names()
        disabled_tools.update(all_tools)

    # Setup display renderer early so pre-LLM shortlist work is visible in banner
    renderer = InterfaceRenderer(
        model_config=model_config,
        model_alias=args.model,
        usage_tracker=usage_tracker,
        summarization_tracker=summarization_tracker,
        session_manager=None,
        messages=[],
        research_mode=research_mode,
        max_turns=getattr(args, "turns", None),
    )

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
                if is_lean:
                    # Render raw markdown without "Assistant:" label
                    from rich.markdown import Markdown

                    renderer.console.print(Markdown(final_answer))
                else:
                    renderer.print_final_answer(final_answer)
        else:
            # Update banner in-place
            if use_banner:
                renderer.update_banner(current_turn, status_message)

    def verbose_output_callback(renderable: Any) -> None:
        """Route verbose output through the active live console when present."""
        if isinstance(renderable, dict):
            tool_name = str(renderable.get("tool_name", "unknown_tool"))
            call_index = int(renderable.get("call_index", 0) or 0)
            total_calls = int(renderable.get("total_calls", 0) or 0)
            turn = int(renderable.get("turn", 0) or 0)
            args_value = renderable.get("arguments", {})
            renderable = Panel(
                str(args_value),
                title=f"Tool {call_index}/{total_calls} | Turn {turn} | {tool_name}",
                border_style="cyan",
                expand=False,
            )
        if use_banner and renderer.live:
            renderer.live.console.print(renderable)
            return
        renderer.console.print(renderable)

    def summarization_status_callback(message: Optional[str]) -> None:
        """Refresh banner during internal summarization calls."""
        if not use_banner:
            return
        renderer.update_banner(renderer.current_turn, status_message=message)

    # Wrap in try/finally to ensure renderer.stop_live() is called.
    try:
        effective_query_text = query_text
        use_banner = LIVE_BANNER and not is_lean
        if use_banner:
            renderer.start_live()

        # Handle Terminal Context
        lines_count = args.terminal_lines if args.terminal_lines is not None else 0

        if lines_count > 0:
            from asky.cli.terminal import inject_terminal_context

            working_messages = [{"role": "user", "content": effective_query_text}]
            warn_on_error = args.terminal_lines is not None

            status_cb = lambda msg: (
                renderer.update_banner(0, status_message=msg) if use_banner else None
            )

            inject_terminal_context(
                working_messages,
                lines_count,
                verbose=args.verbose,
                warn_on_error=warn_on_error,
                status_callback=status_cb,
            )
            if working_messages and working_messages[-1]["role"] == "user":
                effective_query_text = working_messages[-1]["content"]

            if use_banner:
                renderer.update_banner(0, status_message=None)

        asky_client = AskyClient(
            AskyConfig(
                model_alias=args.model,
                summarize=args.summarize,
                verbose=args.verbose,
                open_browser=args.open,
                research_mode=research_mode,
                disabled_tools=disabled_tools,
                system_prompt_override=getattr(args, "system_prompt", None),
            ),
            usage_tracker=usage_tracker,
            summarization_tracker=summarization_tracker,
        )

        elephant_mode = bool(getattr(args, "elephant_mode", False))
        has_session = bool(
            getattr(args, "sticky_session", None)
            or getattr(args, "resume_session", None)
            or get_shell_session_id()
        )
        if elephant_mode and not has_session:
            console.print(
                "[yellow]Warning:[/] --elephant-mode requires an active session "
                "(-ss or -rs). Flag ignored."
            )
            elephant_mode = False

        turn_request = AskyTurnRequest(
            query_text=effective_query_text,
            continue_ids=args.continue_ids,
            summarize_context=args.summarize,
            sticky_session_name=(
                " ".join(args.sticky_session)
                if getattr(args, "sticky_session", None)
                else None
            ),
            resume_session_term=(
                " ".join(args.resume_session)
                if getattr(args, "resume_session", None)
                else None
            ),
            shell_session_id=get_shell_session_id(),
            lean=bool(getattr(args, "lean", False)),
            preload_local_sources=True,
            preload_shortlist=True,
            additional_source_context=None,
            local_corpus_paths=local_corpus,
            save_history=False,  # We handle saving manually after rendering
            elephant_mode=elephant_mode,
            max_turns=getattr(args, "turns", None),
        )

        display_cb = display_callback
        turn_result = asky_client.run_turn(
            turn_request,
            display_callback=display_cb,
            verbose_output_callback=verbose_output_callback,
            summarization_status_callback=summarization_status_callback,
            preload_status_callback=(
                (lambda message: renderer.update_banner(0, status_message=message))
                if use_banner
                else None
            ),
            messages_prepared_callback=lambda msgs: setattr(renderer, "messages", msgs),
            session_resolved_callback=lambda sm: setattr(
                renderer, "session_manager", sm
            ),
            set_shell_session_id_fn=set_shell_session_id,
            clear_shell_session_fn=clear_shell_session,
            shortlist_executor=shortlist_prompt_sources,
            shortlist_formatter=format_shortlist_context,
            shortlist_stats_builder=_build_shortlist_banner_stats,
            local_ingestion_executor=preload_local_research_sources,
            local_ingestion_formatter=format_local_ingestion_context,
            initial_notice_callback=lambda notice: console.print(
                f"[bold red]Error:[/] {notice}"
                if notice.startswith("No sessions")
                else f"\n[{notice}]"
            ),
        )
        final_answer = turn_result.final_answer

        renderer.set_shortlist_stats(turn_result.preload.shortlist_stats)

        if args.verbose and turn_result.preload.shortlist_payload:
            verbose_console = (
                renderer.live.console
                if use_banner and renderer.live
                else renderer.console
            )
            _print_shortlist_verbose(
                verbose_console, turn_result.preload.shortlist_payload
            )

        for notice in turn_result.notices:
            if notice.startswith("No sessions found matching"):
                console.print(f"[bold red]Error:[/] {notice}")
                continue
            if notice.startswith("Multiple sessions found for"):
                console.print(notice + ":")
                for session in turn_result.session.matched_sessions:
                    console.print(
                        f"  {session['id']}: {session['name'] or '(no name)'} ({session['created_at']})"
                    )
                continue
            console.print(f"\n[{notice}]")

        if turn_result.halted:
            return

        # Auto-generate HTML Report FIRST, before saving history (so the CLI responds faster)
        if final_answer and not is_lean:
            from asky.rendering import save_html_report, extract_markdown_title

            html_source = ""
            if turn_result.session_id:
                # Generate full session transcript
                try:
                    repo = SQLiteHistoryRepository()
                    msgs = repo.get_session_messages(int(turn_result.session_id))
                    transcript_parts = []
                    for m in msgs:
                        role_title = "User" if m.role == "user" else "Assistant"
                        transcript_parts.append(f"## {role_title}\n\n{m.content}")

                    # Append the current turn that isn't saved yet
                    transcript_parts.append(f"## User\n\n{effective_query_text}")
                    transcript_parts.append(f"## Assistant\n\n{final_answer}")

                    html_source = "\n\n---\n\n".join(transcript_parts)
                except Exception as e:
                    console.print(
                        f"[bold red]Error:[/] fetching session messages for HTML report: {e}"
                    )
                    html_source = f"## Query\n{effective_query_text}\n\n## Assistant\n{final_answer}"
            else:
                # Single turn report
                html_source = (
                    f"## Query\n{effective_query_text}\n\n## Assistant\n{final_answer}"
                )

            # Extract title explicitly from the new answer to fix "untitled" archives
            filename_hint = extract_markdown_title(final_answer)

            report_path, sidebar_url = save_html_report(
                html_source, filename_hint=filename_hint
            )
            if report_path:
                console.print(f"Open in browser: [bold cyan]file://{report_path}[/]")
                console.print(f"Open with index: [bold cyan]{sidebar_url}[/]")

        # NOW save history synchronously with a live status banner
        if final_answer and not is_lean:
            try:
                if use_banner:
                    renderer.start_live()

                def on_history_status(msg: str) -> None:
                    if use_banner:
                        renderer.update_banner(0, status_message=msg)

                extra_notices = asky_client.finalize_turn_history(
                    turn_request,
                    turn_result,
                    summarization_status_callback=on_history_status,
                )
                for notice in extra_notices:
                    console.print(f"\n[{notice}]")
                if use_banner and research_mode:
                    renderer.update_banner(
                        renderer.current_turn,
                        status_message=BACKGROUND_SUMMARY_DRAIN_STATUS,
                    )
                    _drain_research_background_summaries()
            finally:
                if use_banner:
                    renderer.update_banner(renderer.current_turn, status_message=None)
                    renderer.stop_live()

        # Send Email if requested
        if final_answer and getattr(args, "mail_recipients", None):
            from asky.email_sender import send_email

            recipients = [x.strip() for x in args.mail_recipients.split(",")]
            email_subject = args.subject or f"asky Result: {effective_query_text[:50]}"
            send_email(recipients, email_subject, final_answer)

        # Push data to configured endpoint if requested
        if final_answer and getattr(args, "push_data_endpoint", None):
            from asky.push_data import execute_push_data

            dynamic_args = dict(args.push_params) if args.push_params else {}
            result = execute_push_data(
                args.push_data_endpoint,
                dynamic_args=dynamic_args,
                query=effective_query_text,
                answer=final_answer,
                model=args.model,
            )
            if result["success"]:
                if not is_lean:
                    console.print(
                        f"[Push data successful: {result['endpoint']} - {result['status_code']}]"
                    )
            else:
                # Always print errors
                console.print(
                    f"[Push data failed: {result['endpoint']} - {result['error']}]"
                )

    except KeyboardInterrupt:
        console.print("\nAborted by user.")
    except ContextOverflowError as e:
        console.print(
            "\n[bold red]Context overflow:[/] "
            f"{e}. Try a larger-context model or narrower query."
        )
    except Exception as e:
        console.print(f"\n[bold red]An error occurred:[/] {e}")
        if args.verbose:
            import traceback

            traceback.print_exc()
    finally:
        # Ensure Live is stopped on any exit path
        renderer.stop_live()
