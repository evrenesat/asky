"""Chat implementation for asky CLI."""

import argparse
from typing import List, Dict, Optional

from asky.config import (
    MODELS,
)
from asky.core import (
    ConversationEngine,
    create_default_tool_registry,
    create_deep_dive_tool_registry,
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


def build_messages(
    args: argparse.Namespace,
    context_str: str,
    query_text: str,
    session_manager: Optional[SessionManager] = None,
) -> List[Dict[str, str]]:
    """Build the initial message list for the conversation."""
    messages = [
        {
            "role": "system",
            "content": construct_system_prompt(
                args.deep_research, args.deep_dive, args.force_search
            ),
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

    messages = build_messages(args, context_str, query_text)

    # Initialize Components
    usage_tracker = UsageTracker()
    summarization_tracker = UsageTracker()
    model_config = MODELS[args.model]

    # Handle Sessions
    session_manager = None
    shell_session_id = get_shell_session_id()

    # Explicit session start/resume
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

    messages = build_messages(
        args, context_str, query_text, session_manager=session_manager
    )

    if args.deep_dive:
        registry = create_deep_dive_tool_registry(
            usage_tracker=usage_tracker, summarization_tracker=summarization_tracker
        )
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
        deep_dive=args.deep_dive,
        session_manager=session_manager,
    )

    # Run loop
    try:
        from rich.console import Console
        from rich.markdown import Markdown
        from asky.banner import get_banner, BannerState
        from asky.config import (
            DEFAULT_CONTEXT_SIZE,
            MAX_TURNS,
            SUMMARIZATION_MODEL,
            LIVE_BANNER,
        )
        from asky.storage import get_db_record_count
        from asky.cli.utils import clear_screen

        console = Console()

        def redraw_interface(current_turn: int):
            clear_screen()

            # --- Prepare Banner State ---
            model_id = model_config["id"]
            model_alias = args.model

            sum_alias = SUMMARIZATION_MODEL
            sum_id = MODELS[sum_alias]["id"]

            model_ctx = model_config.get("context_size", DEFAULT_CONTEXT_SIZE)
            sum_ctx = MODELS[sum_alias].get("context_size", DEFAULT_CONTEXT_SIZE)

            db_count = get_db_record_count()

            # Session info
            s_name = None
            s_msg_count = 0
            total_sessions = 0

            if session_manager and session_manager.current_session:
                s_name = session_manager.current_session.name
                # Count messages in current session (in DB + current query/answer pending)
                # This is a bit rough, but we can query the manager or repo
                s_msg_count = len(
                    session_manager.repo.get_session_messages(
                        session_manager.current_session.id
                    )
                )
                total_sessions = session_manager.repo.count_sessions()
            else:
                # If not in session mode, we might still want total sessions count
                # We can instantiate a repo just for stats if needed, or skip
                pass

            state = BannerState(
                model_alias=model_alias,
                model_id=model_id,
                sum_alias=sum_alias,
                sum_id=sum_id,
                model_ctx=model_ctx,
                sum_ctx=sum_ctx,
                max_turns=MAX_TURNS,
                current_turn=current_turn,
                db_count=db_count,
                session_name=s_name,
                session_msg_count=s_msg_count,
                total_sessions=total_sessions,
                token_usage=usage_tracker.usage,
                tool_usage=usage_tracker.get_tool_usage(),
            )

            # Print Banner
            banner = get_banner(state)
            console.print(banner)

            # Print Conversation History
            # We skip system prompts and huge blocks if possible, or just print nicely
            # The engine messages list has the history
            for m in messages:
                role = m.get("role")
                content = m.get("content", "")

                if role == "system":
                    continue

                if role == "user":
                    console.print(f"\n[bold green]User[/]: {content}")
                elif role == "assistant":
                    # Check if it has tool calls
                    if m.get("tool_calls"):
                        # Maybe summarize tool calls?
                        pass

                    if content:
                        console.print(f"\n[bold blue]Assistant[/]:")
                        console.print(Markdown(content))
                if role == "tool":
                    # Tool outputs are shown in banner statistics, no need to print raw output here
                    pass

        # Callback injection based on config
        display_cb = redraw_interface if LIVE_BANNER else None

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

        # Send Email if requested
        if final_answer and getattr(args, "mail_recipients", None):
            from asky.email_sender import send_email

            recipients = [x.strip() for x in args.mail_recipients.split(",")]
            email_subject = args.subject or f"asky Result: {query_text[:50]}"
            send_email(recipients, email_subject, final_answer)

    except KeyboardInterrupt:
        print("\nAborted by user.")
    except Exception as e:
        print(f"\nAn error occurred: {e}")
        if args.verbose:
            import traceback

            traceback.print_exc()
    finally:
        # If LIVE_BANNER was on, the screen is showing the state at the beginning of the last turn.
        # We might want one final update to show the final token usage?
        # Or if LIVE_BANNER was off, we MUST show the banner now.

        # We can re-use redraw_interface logic but we need to pass the final turn count
        # Getting turn count from messages?
        current_turns = sum(1 for m in messages if m.get("role") == "user")

        if not LIVE_BANNER:
            # Show full banner stats at the end if not live
            # We need to construct state manually here as redraw_interface is inside try block...
            # Actually let's just copy the logic or refactor.
            # Given the constraints, I will duplicate the state construction logic for the final report
            # OR I can move redraw_interface out, but it relies on closure variables.

            # Better: just use usage_tracker report as before, but maybe prettier?
            # The requirement said: "Display session-wide token usage statistics from the database when in session mode."
            # The existing usage report code at the end of the file does print token usage.
            # I should ensure it meets the new requirements.
            pass
        else:
            # If live banner is on, just do one final redraw with updated stats
            if "redraw_interface" in locals():
                redraw_interface(current_turns)

        # Legacy Usage Report (kept for non-live mode or detailed breakdown)
        def print_tracker_usage(tracker: UsageTracker, title: str):
            if tracker.usage:
                print(f"\n=== {title} ===")
                print(f"  {'Model':<15} {'Input':<10} {'Output':<10} {'Total':<10}")
                print("  " + "-" * 45)

                total_input = 0
                total_output = 0

                for m_alias in tracker.usage.keys():
                    breakdown = tracker.get_usage_breakdown(m_alias)
                    inp = breakdown["input"]
                    out = breakdown["output"]
                    total = inp + out

                    print(f"  {m_alias:<15} {inp:<10,} {out:<10,} {total:<10,}")

                    total_input += inp
                    total_output += out

                print("  " + "-" * 45)
                print(
                    f"  {'TOTAL':<15} {total_input:<10,} {total_output:<10,} {total_input + total_output:<10,}"
                )
                print("===========================\n")

        print_tracker_usage(usage_tracker, "SESSION TOKEN USAGE")
        if summarization_tracker.usage:
            print_tracker_usage(summarization_tracker, "SUMMARIZATION TOKEN USAGE")
