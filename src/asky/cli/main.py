"""Command-line interface for asky."""

import argparse
import re

from rich.console import Console

from asky.config import (
    DEFAULT_MODEL,
    MODELS,
    SUMMARIZATION_MODEL,
    DEFAULT_CONTEXT_SIZE,
    MAX_TURNS,
    QUERY_SUMMARY_MAX_CHARS,
    ANSWER_SUMMARY_MAX_CHARS,
    LOG_LEVEL,
    LOG_FILE,
)
from asky.banner import get_banner, BannerState
from asky.logger import setup_logging
from asky.storage import init_db, get_db_record_count
from . import history, prompts, chat, utils, sessions


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Tool-calling CLI with model selection.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "-m",
        "--model",
        default=DEFAULT_MODEL,
        choices=MODELS.keys(),
        help="Select the model alias",
    )
    parser.add_argument(
        "-d",
        "--deep-research",
        nargs="?",
        type=int,
        const=5,
        default=0,
        help="Enable deep research mode (optional: specify min number of queries, default 5)",
    )
    parser.add_argument(
        "-dd",
        "--deep-dive",
        action="store_true",
        help="Enable deep dive mode (extracts links and encourages reading more pages from same domain)",
    )
    parser.add_argument(
        "-c",
        "--continue-chat",
        dest="continue_ids",
        help="Continue conversation with context from specific history IDs (comma-separated, e.g. '1,2').",
    )
    parser.add_argument(
        "-s",
        "--summarize",
        action="store_true",
        help="Enable summarize mode (summarizes URL content and uses summaries for chat context)",
    )
    parser.add_argument(
        "-fs",
        "--force-search",
        action="store_true",
        help="Force the model to use web search (default: False).\n"
        "Helpful for avoiding hallucinations with small models",
    )
    parser.add_argument(
        "--delete-messages",
        nargs="?",
        const="interactive",
        help="Delete message history records. usage: --delete-messages [ID|ID-ID|ID,ID] or --delete-messages --all",
    )
    parser.add_argument(
        "--delete-sessions",
        nargs="?",
        const="interactive",
        help="Delete session records and their messages. usage: --delete-sessions [ID|ID-ID|ID,ID] or --delete-sessions --all",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Used with --delete-messages or --delete-sessions to delete ALL records.",
    )
    parser.add_argument(
        "-H",
        "--history",
        nargs="?",
        type=int,
        const=10,
        help="Show last N queries and answer summaries (default 10).\n"
        "Use with --print-answer to print the full answer(s).",
    )
    parser.add_argument(
        "-pa",
        "--print-answer",
        dest="print_ids",
        help="Print the answer(s) for specific history IDs (comma-separated).",
    )
    parser.add_argument(
        "-ps",
        "--print-session",
        dest="print_session",
        help="Print session content by session ID or name.",
    )
    parser.add_argument(
        "-p",
        "--prompts",
        action="store_true",
        help="List all configured user prompts.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output (prints config and LLM inputs).",
    )
    parser.add_argument(
        "-o",
        "--open",
        action="store_true",
        help="Open the final answer in a browser using a markdown template.",
    )
    parser.add_argument(
        "--mail",
        dest="mail_recipients",
        help="Send the final answer via email to comma-separated addresses.",
    )
    parser.add_argument(
        "--subject",
        help="Subject line for the email (used with --mail).",
    )
    parser.add_argument(
        "-ss",
        "--sticky-session",
        nargs="+",
        help="Create and activate a new named session (then exits). Usage: -ss My Session Name",
    )
    parser.add_argument(
        "-rs",
        "--resume-session",
        nargs="+",
        help="Resume an existing session by ID or name (partial match supported).",
    )
    parser.add_argument(
        "--session-end",
        action="store_true",
        help="End the current active session",
    )
    parser.add_argument(
        "-sh",
        "--session-history",
        nargs="?",
        type=int,
        const=10,
        help="Show last N sessions (default 10).",
    )
    parser.add_argument("query", nargs="*", help="The query string")
    return parser.parse_args()


def show_banner(args) -> None:
    """Display the application banner."""
    model_alias = args.model
    model_id = MODELS[model_alias]["id"]
    sum_alias = SUMMARIZATION_MODEL
    sum_id = MODELS[sum_alias]["id"]

    model_ctx = MODELS[model_alias].get("context_size", DEFAULT_CONTEXT_SIZE)
    sum_ctx = MODELS[sum_alias].get("context_size", DEFAULT_CONTEXT_SIZE)
    db_count = get_db_record_count()

    state = BannerState(
        model_alias=model_alias,
        model_id=model_id,
        sum_alias=sum_alias,
        sum_id=sum_id,
        model_ctx=model_ctx,
        sum_ctx=sum_ctx,
        max_turns=MAX_TURNS,
        current_turn=0,
        db_count=db_count,
        # session details (initial state)
        session_name=None,
        session_msg_count=0,
        total_sessions=0,
    )

    banner = get_banner(state)
    Console().print(banner)


def handle_print_answer_implicit(args) -> bool:
    """Handle implicit print answer (query is list of ints or session IDs)."""
    if not args.query:
        return False
    query_str = " ".join(args.query).strip()
    # Match integers or S-prefixed integers (e.g. 1, 2, S3, s4)
    if re.match(r"^([sS]?\d+\s*,?\s*)+$", query_str):
        # Clean up spaces
        clean_query_str = re.sub(r"\s+", "", query_str)
        history.print_answers_command(
            clean_query_str,
            args.summarize,
            open_browser=args.open,
            mail_recipients=args.mail_recipients,
            subject=args.subject,
        )
        return True
    return False


def main() -> None:
    """Main entry point."""
    setup_logging(LOG_LEVEL, LOG_FILE)
    args = parse_args()
    init_db()

    # Commands that don't require banner or query
    if args.history is not None:
        history.show_history_command(args.history)
        return
    if history.handle_delete_messages_command(args):
        return
    if sessions.handle_delete_sessions_command(args):
        return
    if args.print_session:
        sessions.print_session_command(
            args.print_session,
            open_browser=args.open,
            mail_recipients=args.mail_recipients,
            subject=args.subject,
        )
        return
    if args.print_ids:
        history.print_answers_command(
            args.print_ids,
            args.summarize,
            open_browser=args.open,
            mail_recipients=args.mail_recipients,
            subject=args.subject,
        )
        return
    if handle_print_answer_implicit(args):
        return
    if args.session_history is not None:
        sessions.show_session_history_command(args.session_history)
        return
    if args.session_end:
        sessions.end_session_command()
        return
    if args.prompts:
        prompts.list_prompts_command()
        return

    # From here on, we need a query
    if not args.query and not any(
        [
            args.history is not None,
            args.print_ids,
            args.print_session,
            args.delete_messages is not None,
            args.delete_sessions is not None,
            args.prompts,
            args.session_history is not None,
            args.session_end,
            getattr(args, "sticky_session", None),
            getattr(args, "resume_session", None),
        ]
    ):
        print("Error: Query argument is required.")
        return

    # Expand query
    query_text = utils.expand_query_text(" ".join(args.query), verbose=args.verbose)

    # Verbose config
    if args.verbose:
        utils.print_config(
            args,
            MODELS,
            DEFAULT_MODEL,
            MAX_TURNS,
            QUERY_SUMMARY_MAX_CHARS,
            ANSWER_SUMMARY_MAX_CHARS,
        )

    # Show banner
    show_banner(args)

    # Run Chat
    chat.run_chat(args, query_text)


if __name__ == "__main__":
    main()
