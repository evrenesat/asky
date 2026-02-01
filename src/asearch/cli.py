"""Command-line interface for asearch."""

import argparse
import re
from typing import Dict, List, Optional

from asearch.config import DEFAULT_MODEL, MODELS
from asearch.storage import (
    init_db,
    get_history,
    get_interaction_context,
    cleanup_db,
    save_interaction,
)
from asearch.llm import (
    construct_system_prompt,
    run_conversation_loop,
    generate_summaries,
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Tool-calling CLI with model selection."
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
        help="Enable deep dive mode (extracts links and encourages recursive research)",
    )
    parser.add_argument(
        "-H",
        "--history",
        nargs="?",
        type=int,
        const=10,
        help="Show last N queries (default 10) and exit.",
    )
    parser.add_argument(
        "-c",
        "--continue-chat",
        dest="continue_ids",
        help="Continue conversation with context from specific history IDs (comma-separated, e.g. '1,2').",
    )
    parser.add_argument(
        "-f",
        "--full",
        action="store_true",
        help="Use full content of previous answers for context instead of summaries.",
    )
    parser.add_argument(
        "-s",
        "--summarize",
        action="store_true",
        help="Enable summarize mode (summarizes the content of the URL)",
    )
    parser.add_argument(
        "-fs",
        "--force-search",
        action="store_true",
        help="Force the model to use web search (default: False).",
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
        "-p",
        "--print-answer",
        dest="print_ids",
        help="Print the answer(s) for specific history IDs (comma-separated).",
    )
    parser.add_argument("query", nargs="*", help="The query string")
    return parser.parse_args()


def show_history(history_arg: int) -> None:
    """Display recent query history."""
    limit = history_arg if history_arg > 0 else 10
    rows = get_history(limit)
    print(f"\nLast {len(rows)} Queries:")
    print("-" * 60)
    for row in rows:
        rid, ts, query, q_sum, a_sum, mod = row
        display_query = q_sum if q_sum else query
        if len(display_query) > 50:
            display_query = display_query[:47] + "..."
        if len(a_sum) > 50:
            a_sum = a_sum[:47] + "..."

        print(f"{rid:<4} | {display_query:<50} | {a_sum:<50}")
    print("-" * 60)


def load_context(continue_ids: str, full_content: bool) -> Optional[str]:
    """Load context from previous interactions."""
    try:
        ids = [int(x.strip()) for x in continue_ids.split(",")]
        context_str = get_interaction_context(ids, full=full_content)
        if context_str:
            print(f"\n[Loaded context from IDs: {continue_ids}]")
        return context_str
    except ValueError:
        print(
            "Error: Invalid format for -c/--continue-chat. Use comma-separated integers."
        )
        return None


def build_messages(args: argparse.Namespace, context_str: str) -> List[Dict[str, str]]:
    """Build the initial message list for the conversation."""
    messages = [
        {
            "role": "system",
            "content": construct_system_prompt(
                args.deep_research, args.deep_dive, args.force_search
            ),
        },
    ]

    if context_str:
        messages.append(
            {
                "role": "user",
                "content": f"Context from previous queries:\n{context_str}\n\nMy new query is below.",
            }
        )

    query_text = " ".join(args.query)
    messages.append({"role": "user", "content": query_text})
    return messages


def print_answers(ids_str: str, full: bool) -> None:
    """Print answers for specific history IDs."""
    try:
        ids = [int(x.strip()) for x in ids_str.split(",")]
    except ValueError:
        print("Error: Invalid ID format. Use comma-separated integers.")
        return

    context = get_interaction_context(ids, full=full)
    if not context:
        print("No records found for the given IDs.")
        return

    print(f"\n[Retrieving answers for IDs: {ids_str}]\n")
    print("-" * 60)
    print(context)
    print("-" * 60)


def handle_cleanup(args: argparse.Namespace) -> bool:
    """Handle cleanup command. Returns True if cleanup was performed."""
    if args.cleanup_db or (args.cleanup_db is None and args.all):
        target = args.cleanup_db
        if args.all:
            cleanup_db(None, delete_all=True)
        elif target and target != "interactive":
            cleanup_db(target)
        else:
            print("Error: Please specify target IDs (e.g. 1, 1-5, 1,3) or use --all")
        return True
    return False


def handle_print_answer_implicit(args: argparse.Namespace) -> bool:
    """Handle implicit print answer (query is list of ints). Returns True if handled."""
    if not args.query:
        return False

    query_str = " ".join(args.query).strip()
    if re.match(r"^(\d+\s*,?\s*)+$", query_str):
        possible_ids = re.split(r"[,\s]+", query_str)
        possible_ids = [x for x in possible_ids if x]
        try:
            clean_ids_str = ",".join(possible_ids)
            print_answers(clean_ids_str, args.full)
            return True
        except ValueError:
            pass
    return False


def main() -> None:
    """Main entry point for the CLI."""
    args = parse_args()
    init_db()

    # Handle History Request
    if args.history is not None:
        show_history(args.history)
        return

    # Handle Cleanup
    if handle_cleanup(args):
        return

    # Handle Explicit Print Answer
    if args.print_ids:
        print_answers(args.print_ids, args.full)
        return

    # Handle Implicit Print Answer (query is list of ints)
    if handle_print_answer_implicit(args):
        return

    if not args.query:
        print("Error: Query argument is required unless -H/--history is used.")
        return

    # Handle Context
    context_str = ""
    if args.continue_ids:
        context_str = load_context(args.continue_ids, args.full)
        if context_str is None:
            return

    messages = build_messages(args, context_str)
    model_config = MODELS[args.model]

    final_answer = run_conversation_loop(model_config, messages, args.summarize)

    # Save Interaction
    if final_answer:
        print("\n[Saving interaction...]")
        query_text = " ".join(args.query)
        query_summary, answer_summary = generate_summaries(query_text, final_answer)
        save_interaction(
            query_text, final_answer, args.model, query_summary, answer_summary
        )


if __name__ == "__main__":
    main()
