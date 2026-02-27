"""History-related CLI commands for asky."""

from rich.console import Console
from rich.table import Table
from rich.markdown import Markdown

from asky.cli.completion import parse_answer_selector_token
from asky.core.prompts import is_markdown
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

    if not rows:
        print("No history found.")
        return

    console = Console()
    table = Table(title=f"Recent History (Last {len(rows)})")
    table.add_column("ID", style="cyan", justify="right")
    table.add_column("Query", style="green")
    table.add_column("Answer Preview", style="blue")
    table.add_column("Model", style="dim")
    table.add_column("Date", style="dim")

    for row in rows:
        # row is an Interaction object
        # Use summary if available, fallback to content/query
        display_query = row.summary if row.summary else row.query
        if not display_query:
            display_query = row.content

        display_answer = row.answer
        if not display_answer and row.role == "assistant":
            display_answer = row.content

        # Truncate
        if len(display_query) > 50:
            display_query = display_query[:47] + "..."
        if len(display_answer) > 50:
            display_answer = display_answer[:47] + "..."

        date_str = row.timestamp[:16].replace("T", " ")

        table.add_row(
            str(row.id),
            display_query or "-",
            display_answer or "-",
            row.model or "-",
            date_str,
        )

    console.print(table)


def print_answers_command(
    ids_str: str,
    summarize: bool,
    open_browser: bool = False,
) -> None:
    """Print answers for specific history IDs."""
    ids = []
    for raw_token in ids_str.split(","):
        token = raw_token.strip()
        parsed_id = parse_answer_selector_token(token)
        if parsed_id is None:
            print(
                f"Error: Invalid history ID format: '{ids_str}'. "
                "Use integer IDs, comma-separated IDs, or completion selector tokens."
            )
            return
        ids.append(parsed_id)

    context = get_interaction_context(ids, full=not summarize)
    if not context:
        print("No records found for the given IDs.")
        return

    print(f"\n[Retrieving answers for IDs: {', '.join(str(i) for i in ids)}]\n")
    print("-" * 60)
    if is_markdown(context):
        console = Console()
        console.print(Markdown(context))
    else:
        print(context)
    print("-" * 60)

    if open_browser:
        render_to_browser(context, filename_hint=f"history_answers_{ids_str}")

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
