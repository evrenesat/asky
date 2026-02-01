"""Command-line interface for asearch."""

import argparse
import os
import pyperclip
import re
from typing import Dict, List, Optional

from rich.console import Console
from rich.markdown import Markdown


from asearch.config import DEFAULT_MODEL, MODELS, USER_PROMPTS
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
    is_markdown,
)


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


def load_context(continue_ids: str, summarize: bool) -> Optional[str]:
    """Load context from previous interactions."""
    try:
        raw_ids = [x.strip() for x in continue_ids.split(",")]
        resolved_ids = []
        relative_indices = []

        for raw_id in raw_ids:
            if raw_id.startswith("~"):
                try:
                    # ~1 means last record (index 0), ~2 means second to last (index 1)
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
            # Fetch enough history to cover the requested depth
            history_rows = get_history(limit=max_depth)

            for rel_val in relative_indices:
                list_index = rel_val - 1
                if list_index < len(history_rows):
                    # history_rows is ordered by ID DESC
                    # row format: (id, timestamp, query, q_sum, a_sum, mod)
                    real_id = history_rows[list_index][0]
                    resolved_ids.append(real_id)
                else:
                    print(
                        f"Error: Relative ID {rel_val} is out of range (only {len(history_rows)} records available)."
                    )
                    return None

        # Remove duplicates while preserving order? Or just sort?
        # get_interaction_context uses "WHERE id IN (...)" so order in list might not match output order if SQL doesn't enforce it.
        # But commonly we want context in chronological order usually.
        # get_interaction_context implementation:
        #   c.execute(query_str, ids)
        #   results = c.fetchall()
        # It doesn't enforce order passed in `ids` unless we do explicit ordering.
        # But `load_context` returns a joined string.
        # Let's keep distinct IDs.
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


def print_answers(ids_str: str, summarize: bool) -> None:
    """Print answers for specific history IDs."""
    try:
        ids = [int(x.strip()) for x in ids_str.split(",")]
    except ValueError:
        print("Error: Invalid ID format. Use comma-separated integers.")
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


def expand_query_text(text: str, verbose: bool = False) -> str:
    """Recursively expand slash commands like /cp and predefined prompts."""
    expanded = text
    max_depth = 5
    depth = 0

    while depth < max_depth:
        original = expanded

        # 1. Expand /cp
        if "/cp" in expanded:
            try:
                clipboard_content = pyperclip.paste()
                if clipboard_content:
                    expanded = expanded.replace("/cp", clipboard_content)
                    if verbose:
                        print("[Expanded /cp from clipboard]")
                else:
                    if verbose:
                        print("[Warning: Clipboard is empty, /cp not expanded]")
            except Exception as e:
                if verbose:
                    print(f"[Error reading clipboard: {e}]")

        # 2. Expand predefined prompts from USER_PROMPTS
        # Pattern: /command followed by space or end of string
        # We use a pattern that matches /word but avoids matching /cp if we already handled it
        # Actually, let's just iterate over USER_PROMPTS keys
        for key, prompt_val in USER_PROMPTS.items():
            pattern = rf"/{re.escape(key)}(\s|$)"
            if re.search(pattern, expanded):
                expanded = re.sub(pattern, rf"{prompt_val}\1", expanded)
                if verbose:
                    print(f"[Expanded Prompt '/{key}']")

        if expanded == original:
            break
        depth += 1

    return expanded.strip()


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
            print_answers(clean_ids_str, args.summarize)
            return True
        except ValueError:
            pass
    return False


def main() -> None:
    """Main entry point for the CLI."""
    args = parse_args()

    if args.verbose:
        print("\n=== CONFIGURATION ===")
        print(f"Selected Model: {args.model}")
        print(f"Deep Research: {args.deep_research}")
        print(f"Deep Dive: {args.deep_dive}")
        print(f"Summarize: {args.summarize}")
        print(f"Force Search: {args.force_search}")
        print("-" * 20)
        from asearch.config import (
            DEFAULT_MODEL,
            MAX_TURNS,
            QUERY_SUMMARY_MAX_CHARS,
            ANSWER_SUMMARY_MAX_CHARS,
        )

        print(f"DEFAULT_MODEL: {DEFAULT_MODEL}")
        print(f"MAX_TURNS: {MAX_TURNS}")
        print(f"QUERY_SUMMARY_MAX_CHARS: {QUERY_SUMMARY_MAX_CHARS}")
        print(f"ANSWER_SUMMARY_MAX_CHARS: {ANSWER_SUMMARY_MAX_CHARS}")
        print("-" * 20)
        print("MODELS Config:")
        for m_alias, m_conf in MODELS.items():
            print(f"  [{m_alias}]: {m_conf['id']}")
            for k, v in m_conf.items():
                if k == "id":
                    continue

                # Special handling for api_key_env
                if k == "api_key_env":
                    print(f"    {k}: {v}")
                    # Check if env var is set
                    env_val = os.environ.get(v)
                    if env_val:
                        masked = (
                            env_val[:5] + "..." + env_val[-4:]
                            if len(env_val) > 10
                            else "***"
                        )
                        print(f"      [Status]: SET ({masked})")
                    else:
                        print("      [Status]: NOT SET")
                    continue

                if "key" in k.lower() and v and k != "api_key_env":
                    # Mask key directly
                    masked = v[:5] + "..." + v[-4:] if len(v) > 10 else "***"
                    print(f"    {k}: {masked}")
                else:
                    print(f"    {k}: {v}")
        print("=====================\n")

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
        print_answers(args.print_ids, args.summarize)
        return

    # Handle Implicit Print Answer (query is list of ints)
    if handle_print_answer_implicit(args):
        return

    if args.prompts:
        print("\n=== USER PROMPTS ===")
        if USER_PROMPTS:
            for key, prompt in USER_PROMPTS.items():
                print(f"  /{key:<10} : {prompt}")
        else:
            print("  (No prompts configured)")
        print("====================\n")
        return

    if not args.query:
        print(
            "Error: Query argument is required unless -H/--history or --prompts is used."
        )
        return

    # Join query tokens and expand slash commands
    query_text = " ".join(args.query)
    query_text = expand_query_text(query_text, verbose=args.verbose)

    # Update args.query to the expanded version for later use (saving interaction)
    # Note: args.query was a list, we'll keep it as a list with one element for compatibility
    args.query = [query_text]

    # Handle Context
    context_str = ""
    if args.continue_ids:
        context_str = load_context(args.continue_ids, args.summarize)
        if context_str is None:
            return

    messages = build_messages(args, context_str)
    model_config = MODELS[args.model]

    final_answer = run_conversation_loop(
        model_config, messages, args.summarize, verbose=args.verbose
    )

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
