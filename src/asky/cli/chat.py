"""Chat implementation for asky CLI."""

import sys
import argparse
from typing import List, Dict, Any, Optional

from asky.config import (
    MODELS,
    SUMMARIZATION_MODEL,
    QUERY_EXPANSION_MAX_DEPTH,
)
from asky.core import (
    ConversationEngine,
    create_default_tool_registry,
    UsageTracker,
    construct_system_prompt,
    generate_summaries,
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
    args: argparse.Namespace, context_str: str, query_text: str
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

    if context_str:
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
    registry = create_default_tool_registry()
    model_config = MODELS[args.model]

    engine = ConversationEngine(
        model_config=model_config,
        tool_registry=registry,
        summarize=args.summarize,
        verbose=args.verbose,
        usage_tracker=usage_tracker,
        open_browser=args.open,
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
            save_interaction(
                query_text, final_answer, args.model, query_summary, answer_summary
            )

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
