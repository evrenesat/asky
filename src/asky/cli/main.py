"""Command-line interface for asky."""

import argparse
import re
import sys

from rich.console import Console

from asky.config import (
    DEFAULT_MODEL,
    MODELS,
    SUMMARIZATION_MODEL,
    SEARCH_PROVIDER,
    DEFAULT_CONTEXT_SIZE,
    MAX_TURNS,
    QUERY_SUMMARY_MAX_CHARS,
    ANSWER_SUMMARY_MAX_CHARS,
    LOG_LEVEL,
    LOG_FILE,
)
from asky.banner import get_banner
from asky.logger import setup_logging
from asky.storage import init_db, get_db_record_count
from . import history, prompts, chat, utils


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
        "--cleanup-db",
        nargs="?",
        const="interactive",
        help="Delete history records. usage: --cleanup-db [ID|ID-ID|ID,ID] or --cleanup-db --all",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Used with --cleanup-db to delete ALL history.",
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

    banner = get_banner(
        model_alias,
        model_id,
        sum_alias,
        sum_id,
        DEFAULT_MODEL,
        SEARCH_PROVIDER,
        model_ctx,
        sum_ctx,
        MAX_TURNS,
        db_count,
    )
    Console().print(banner)


def handle_print_answer_implicit(args) -> bool:
    """Handle implicit print answer (query is list of ints)."""
    if not args.query:
        return False
    query_str = " ".join(args.query).strip()
    if re.match(r"^(\d+\s*,?\s*)+$", query_str):
        possible_ids = re.split(r"[,\s]+", query_str)
        clean_ids_str = ",".join([x for x in possible_ids if x])
        history.print_answers_command(
            clean_ids_str, args.summarize, open_browser=args.open
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
    if history.handle_cleanup_command(args):
        return
    if args.print_ids:
        history.print_answers_command(
            args.print_ids, args.summarize, open_browser=args.open
        )
        return
    if handle_print_answer_implicit(args):
        return
    if args.prompts:
        prompts.list_prompts_command()
        return

    # From here on, we need a query
    if not args.query:
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
