"""History-related CLI commands for asky."""

from rich.console import Console
from rich.markdown import Markdown

from asky.core import is_markdown
from asky.rendering import render_to_browser
from asky.storage import (
    get_history,
    get_interaction_context,
    delete_messages,
)


def show_history_command(history_arg: int) -> None:
    """Display recent query history."""
    limit = history_arg if history_arg > 0 else 10
    rows = get_history(limit)
    print(f"\nLast {len(rows)} Queries:")
    print("-" * 60)
    for row in rows:
        rid = row[0]
        query = row[2]
        query_summary = row[3]
        answer_summary = row[4]

        display_query = query_summary if query_summary else query
        a_sum = answer_summary if answer_summary else ""

        if len(display_query) > 50:
            display_query = display_query[:47] + "..."
        if len(a_sum) > 50:
            a_sum = a_sum[:47] + "..."

        print(f"{rid:<4} | {display_query:<50} | {a_sum:<50}")
    print("-" * 60)


def print_answers_command(
    ids_str: str,
    summarize: bool,
    open_browser: bool = False,
    mail_recipients: str = None,
    subject: str = None,
) -> None:
    """Print answers for specific history IDs."""
    try:
        ids = [int(x.strip()) for x in ids_str.split(",")]
    except ValueError:
        print(
            f"Error: Invalid history ID format: '{ids_str}'. Use integers or comma-separated list."
        )
        return

    context = get_interaction_context(ids, full=not summarize)
    if not context:
        print("No records found for the given IDs.")
        return

    print(f"\n[Retrieving answers for IDs: {ids_str}]\n")
    print("-" * 60)
    if is_markdown(context):
        console = Console()
        console.print(Markdown(context))
    else:
        print(context)
    print("-" * 60)

    if open_browser:
        render_to_browser(context)

    if mail_recipients:
        from asky.email_sender import send_email

        recipients = [x.strip() for x in mail_recipients.split(",")]
        # Use provided subject or default
        email_subject = subject or f"asky History: {ids_str}"
        send_email(recipients, email_subject, context)


def handle_delete_messages_command(args) -> bool:
    """Handle delete-messages flag."""
    # Safety check: if --all is present but no explicit delete flag, warn user.
    if getattr(args, "all", False) and args.delete_messages is None:
        print("Warning: --all must be used with --delete-messages to confirm deletion.")
        return False

    if args.delete_messages or (
        args.delete_messages is None
        and getattr(args, "all", False)  # redundant now but safe
    ):
        if args.all:
            count = delete_messages(delete_all=True)
            print(f"Deleted all {count} message records from history.")
        elif args.delete_messages and (
            "-" in args.delete_messages or "," in args.delete_messages
        ):
            count = delete_messages(ids=args.delete_messages)
            print(f"Deleted {count} message records from history.")
        elif args.delete_messages:
            # Single ID
            count = delete_messages(ids=args.delete_messages)
            print(f"Deleted {count} message record(s) from history.")
        return True
    return False
