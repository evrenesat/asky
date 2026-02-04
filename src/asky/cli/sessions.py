"""Session-related CLI commands for asky."""

from rich.console import Console
from rich.table import Table
from rich.markdown import Markdown

from asky.storage.sqlite import SQLiteHistoryRepository
from asky.rendering import render_to_browser
from asky.config import MODELS


def show_session_history_command(limit: int) -> None:
    """List recent sessions."""
    repo = SQLiteHistoryRepository()
    sessions = repo.list_sessions(limit)

    if not sessions:
        print("No sessions found.")
        return

    console = Console()
    table = Table(title=f"Recent Sessions (Last {limit})")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Model", style="blue")
    table.add_column("Msgs", justify="right")
    table.add_column("Status", justify="center")
    table.add_column("Created At", style="dim")

    for s in sessions:
        msgs = repo.get_session_messages(s.id)
        status = "Active" if s.is_active else "Ended"
        status_style = "bold green" if s.is_active else "dim"

        table.add_row(
            str(s.id),
            s.name or "-",
            s.model,
            str(len(msgs)),
            f"[{status_style}]{status}[/]",
            s.created_at[:16].replace("T", " "),
        )

    console.print(table)


def print_session_command(
    id_or_name: str,
    open_browser: bool = False,
    mail_recipients: str = None,
    subject: str = None,
) -> None:
    """Print session messages."""
    repo = SQLiteHistoryRepository()

    # Try to get by ID first
    session = None
    try:
        session_id = int(id_or_name)
        session = repo.get_session_by_id(session_id)
    except ValueError:
        # If not an integer, try by name
        pass

    if not session:
        # Try by name
        session = repo.get_session_by_name(id_or_name)

    if not session:
        print(f"Error: Session '{id_or_name}' not found.")
        return

    msgs = repo.get_session_messages(session.id)
    if not msgs:
        print(f"Session {session.id} is empty.")
        return

    # Build full conversation text
    full_content = []
    if session.compacted_summary:
        full_content.append(
            f"### [Compacted Summary]\n{session.compacted_summary}\n---"
        )

    for m in msgs:
        role_label = "User" if m.role == "user" else "Assistant"
        full_content.append(f"**{role_label}**:\n{m.content}\n")

    full_text = "\n".join(full_content)

    if open_browser:
        print(f"Opening Session #{session.id} in browser...")
        render_to_browser(full_text)
    else:
        console = Console()
        console.print(Markdown(full_text))

    if mail_recipients:
        from asky.email_sender import send_email

        recipients = [x.strip() for x in mail_recipients.split(",")]
        email_subject = (
            subject or f"asky Session #{session.id}: {session.name or 'Untold'}"
        )
        send_email(recipients, email_subject, full_text)


def end_session_command() -> None:
    """End the currently active session."""
    from asky.core import clear_shell_session

    repo = SQLiteHistoryRepository()
    active = repo.get_active_session()
    if active:
        repo.end_session(active.id)
        clear_shell_session()
        print(f"Session {active.id} ({active.name or 'unnamed'}) ended.")
    else:
        print("No active session to end.")


def handle_delete_sessions_command(args) -> bool:
    """Handle delete-sessions flag."""
    from asky.storage import delete_sessions

    if args.delete_sessions or (
        args.delete_sessions is None and getattr(args, "all", False)
    ):
        if args.all:
            count = delete_sessions(delete_all=True)
            print(f"Deleted all {count} session records and their messages.")
        elif args.delete_sessions and (
            "-" in args.delete_sessions or "," in args.delete_sessions
        ):
            count = delete_sessions(ids=args.delete_sessions)
            print(f"Deleted {count} session record(s) and their messages.")
        elif args.delete_sessions:
            # Single ID
            count = delete_sessions(ids=args.delete_sessions)
            print(f"Deleted {count} session record(s) and their messages.")
        return True
    return False
