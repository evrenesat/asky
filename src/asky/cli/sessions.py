"""Session-related CLI commands for asky."""

from rich.console import Console
from rich.table import Table
from rich.markdown import Markdown

from asky.storage.session import SessionRepository
from asky.rendering import render_to_browser
from asky.config import MODELS


def show_session_history_command(limit: int) -> None:
    """List recent sessions."""
    repo = SessionRepository()
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
            f"S{s.id}",
            s.name or "-",
            s.model,
            str(len(msgs)),
            f"[{status_style}]{status}[/]",
            s.created_at[:16].replace("T", " "),
        )

    console.print(table)


def print_session_command(
    session_id_val: str,
    open_browser: bool = False,
    mail_recipients: str = None,
    subject: str = None,
) -> None:
    """Print or open session content."""
    repo = SessionRepository()

    # Resolve ID
    session = None
    if session_id_val.isdigit():
        session = repo.get_session_by_id(int(session_id_val))
    else:
        session = repo.get_session_by_name(session_id_val)

    if not session:
        print(f"Error: Session '{session_id_val}' not found.")
        return

    msgs = repo.get_session_messages(session.id)
    if not msgs:
        print(f"Session S{session.id} is empty.")
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
        print(f"Opening Session S{session.id} in browser...")
        render_to_browser(full_text)
    else:
        console = Console()
        console.print(Markdown(full_text))

    if mail_recipients:
        from asky.email_sender import send_email

        recipients = [x.strip() for x in mail_recipients.split(",")]
        email_subject = (
            subject or f"asky Session S{session.id}: {session.name or 'Untold'}"
        )
        send_email(recipients, email_subject, full_text)


def end_session_command() -> None:
    """End the currently active session."""
    from asky.core import clear_shell_session

    repo = SessionRepository()
    active = repo.get_active_session()
    if active:
        repo.end_session(active.id)
        clear_shell_session()
        print(f"Session S{active.id} ({active.name or 'unnamed'}) ended.")
    else:
        print("No active session to end.")
