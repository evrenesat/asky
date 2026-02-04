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
    # Handle Context
    context_str = ""
    if args.continue_ids:
        context_str = load_context(args.continue_ids, args.summarize)
        if context_str is None:
            return

    messages = build_messages(args, context_str, query_text)

    # Initialize Components
    usage_tracker = UsageTracker()
    model_config = MODELS[args.model]

    # Handle Sessions
    session_manager = None
    shell_session_id = get_shell_session_id()

    # Explicit session start/resume
    if getattr(args, "sticky_session", None):
        session_manager = SessionManager(model_config, usage_tracker)
        s = session_manager.start_or_resume(
            args.sticky_session if args.sticky_session != "auto" else None
        )
        set_shell_session_id(s.id)
        print(f"\n[Session {s.id} ({s.name or 'auto'}) active]")

    # Auto-resume from shell lock file
    elif shell_session_id:
        session_manager = SessionManager(model_config, usage_tracker)
        session = session_manager.repo.get_session_by_id(shell_session_id)
        if session and session.is_active:
            session_manager.current_session = session
            print(f"\n[Resuming session {session.id} ({session.name or 'auto'})]")
        else:
            # Lock file points to an ended session, clear it
            from asky.core import clear_shell_session

            clear_shell_session()
            session_manager = None

    messages = build_messages(
        args, context_str, query_text, session_manager=session_manager
    )

    if args.deep_dive:
        registry = create_deep_dive_tool_registry()
    else:
        registry = create_default_tool_registry()

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
        final_answer = engine.run(messages)

        # Save Interaction
        if final_answer:
            print("\n[Saving interaction...]")
            query_summary, answer_summary = generate_summaries(
                query_text, final_answer, usage_tracker=usage_tracker
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
        # Report usage
        if usage_tracker.usage:
            print("\n=== SESSION TOKEN USAGE ===")
            total_session_tokens = 0
            for m_alias, tokens in usage_tracker.usage.items():
                print(f"  {m_alias:<15}: {tokens:,} tokens")
                total_session_tokens += tokens
            print("-" * 30)
            print(f"  {'TOTAL':<15}: {total_session_tokens:,} tokens")
            print("===========================\n")
