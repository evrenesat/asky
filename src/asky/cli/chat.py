"""Chat implementation for asky CLI."""

import argparse
from typing import List, Dict, Optional

from rich.console import Console

from asky.config import MODELS, LIVE_BANNER, RESEARCH_SYSTEM_PROMPT
from asky.core import (
    ConversationEngine,
    create_default_tool_registry,
    create_research_tool_registry,
    UsageTracker,
    construct_system_prompt,
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


def load_context(continue_ids: str, summarize: bool) -> Optional[str]:
    """Load context from previous interactions."""
    try:
        raw_ids = [x.strip() for x in continue_ids.split(",")]
        resolved_ids = []
        relative_indices = []

        for raw_id in raw_ids:
            if raw_id.startswith("~"):
                try:
                    rel_val = int(raw_id[1:])
                    if rel_val < 1:
                        print(f"Error: Relative ID must be >= 1 (got {raw_id})")
                        return None
                    relative_indices.append(rel_val)
                except ValueError:
                    print(f"Error: Invalid relative ID format: {raw_id}")
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
                    print(
                        f"Error: Relative ID {rel_val} is out of range (only {len(history_rows)} records available)."
                    )
                    return None

        resolved_ids = sorted(list(set(resolved_ids)))
        full_content = not summarize
        context_str = get_interaction_context(resolved_ids, full=full_content)
        if context_str:
            print(f"\n[Loaded context from IDs: {', '.join(map(str, resolved_ids))}]")
        return context_str
    except ValueError:
        print(
            "Error: Invalid format for -c/--continue-chat. Use comma-separated integers or ~N for relative."
        )
        return None


def construct_research_system_prompt() -> str:
    """Construct the system prompt for research mode."""
    from datetime import datetime

    current_date = datetime.now().strftime("%A, %B %d, %Y at %H:%M")
    prompt = RESEARCH_SYSTEM_PROMPT.replace("{CURRENT_DATE}", current_date)
    return prompt


def build_messages(
    args: argparse.Namespace,
    context_str: str,
    query_text: str,
    session_manager: Optional[SessionManager] = None,
    research_mode: bool = False,
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

    messages.append({"role": "user", "content": query_text})
    return messages


def run_chat(args: argparse.Namespace, query_text: str) -> None:
    """Run the chat conversation flow."""
    from asky.core import clear_shell_session

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
        print(f"\n[Session {s.id} ('{s.name}') created and active]")
        return

    # Explicit session resume (-rs)
    elif getattr(args, "resume_session", None):
        search_term = " ".join(args.resume_session)
        session_manager = SessionManager(
            model_config, usage_tracker, summarization_tracker=summarization_tracker
        )
        matches = session_manager.find_sessions(search_term)

        if not matches:
            print(f"Error: No sessions found matching '{search_term}'")
            return
        elif len(matches) > 1:
            print(f"Multiple sessions found for '{search_term}':")
            for s in matches:
                print(f"  {s.id}: {s.name or '(no name)'} ({s.created_at})")
            return
        else:
            s = matches[0]
            session_manager.current_session = s
            set_shell_session_id(s.id)
            print(f"\n[Resumed session {s.id} ('{s.name or 'auto'}')]")
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
            print(f"\n[Resuming session {session.id} ({session.name or 'auto'})]")
        else:
            # Lock file points to deleted session, clear it
            clear_shell_session()
            session_manager = None

    # Check for research mode
    research_mode = getattr(args, "research", False)
    if research_mode:
        print("\n[Research mode enabled - using link extraction and RAG tools]")

    messages = build_messages(
        args,
        context_str,
        query_text,
        session_manager=session_manager,
        research_mode=research_mode,
    )

    # Setup display renderer
    renderer = InterfaceRenderer(
        model_config=model_config,
        model_alias=args.model,
        usage_tracker=usage_tracker,
        summarization_tracker=summarization_tracker,
        session_manager=session_manager,
        messages=messages,
        research_mode=research_mode,
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
                renderer.print_final_answer(final_answer)
        else:
            # Update banner in-place
            renderer.update_banner(current_turn, status_message)

    # Start Live banner display if enabled, BEFORE terminal context
    if LIVE_BANNER:
        renderer.start_live()

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
        )

        # Run loop
        display_cb = display_callback if LIVE_BANNER else None
        final_answer = engine.run(messages, display_callback=display_cb)

        # Save Interaction
        if final_answer:
            print("\n[Saving interaction...]")
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
                    print("[Session context compacted]")
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
                    print(f"Error fetching session messages for HTML report: {e}")
                    html_source = f"## Query\n{query_text}\n\n## Answer\n{final_answer}"
            else:
                # Single turn report
                html_source = f"## Query\n{query_text}\n\n## Answer\n{final_answer}"

            report_path = save_html_report(html_source)
            if report_path:
                Console().print(f"Open in browser: [bold cyan]file://{report_path}[/]")

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
                print(
                    f"[Push data successful: {result['endpoint']} - {result['status_code']}]"
                )
            else:
                print(f"[Push data failed: {result['endpoint']} - {result['error']}]")

    except KeyboardInterrupt:
        print("\nAborted by user.")
    except Exception as e:
        print(f"\nAn error occurred: {e}")
        if args.verbose:
            import traceback

            traceback.print_exc()
    finally:
        # Ensure Live is stopped on any exit path
        renderer.stop_live()
