"""History-related CLI commands for asky."""

from rich.console import Console
from rich.markdown import Markdown

from asky.core import is_markdown
from asky.rendering import render_to_browser
from asky.storage import (
    get_history,
    get_interaction_context,
    cleanup_db,
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
    """Print answers for specific history IDs or session IDs."""
    import re

    # Check if this is a session ID (S123) or a session name (not a plain integer or comma-list of integers)
    if re.match(r"^[sS]\d+$", ids_str.strip()) or (
        not re.match(r"^(\d+\s*,?\s*)+$", ids_str.strip()) and "," not in ids_str
    ):
        from asky.cli.sessions import print_session_command

        val = ids_str.strip()
        if val.lower().startswith("s") and val[1:].isdigit():
            val = val[1:]  # Pass the numeric part to session command
        print_session_command(val, open_browser, mail_recipients, subject)
        return

    try:
        ids = [int(x.strip()) for x in ids_str.split(",")]
    except ValueError:
        # Fallback to session name if it's not a valid history ID list
        from asky.cli.sessions import print_session_command

        print_session_command(ids_str.strip(), open_browser, mail_recipients, subject)
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


def handle_cleanup_command(args) -> bool:
    """Handle cleanup-db flag."""
    if args.cleanup_db or (args.cleanup_db is None and getattr(args, "all", False)):
        if args.all:
            count = cleanup_db(delete_all=True)
            print(f"Deleted all {count} records from history.")
        elif "-" in args.cleanup_db or "," in args.cleanup_db:
            count = cleanup_db(ids=args.cleanup_db)
            print(f"Deleted {count} records from history.")
        else:
            try:
                days = int(args.cleanup_db)
                count = cleanup_db(days=days)
                print(f"Deleted {count} records older than {days} days.")
            except ValueError:
                print(
                    "Error: Invalid cleanup format. Use days (int), range (start-end), or list (1,2,3)."
                )
        return True
    return False
