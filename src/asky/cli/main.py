"""Command-line interface for asky."""

import argparse
import importlib
import re
import threading
from types import ModuleType
from typing import Optional

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
    USER_PROMPTS,
)
from asky.banner import get_banner, BannerState
from asky.logger import setup_logging, generate_timestamped_log_path
from asky.storage import init_db, get_db_record_count
from asky.storage.sqlite import SQLiteHistoryRepository


class _LazyModuleProxy:
    """Module proxy that defers imports until first attribute access."""

    def __init__(self, module_name: str):
        self._module_name = module_name
        self._module: Optional[ModuleType] = None

    def _load(self) -> ModuleType:
        if self._module is None:
            self._module = importlib.import_module(self._module_name)
        return self._module

    def __getattr__(self, item: str):
        return getattr(self._load(), item)


# Keep these names stable for tests while avoiding eager imports.
history = _LazyModuleProxy("asky.cli.history")
prompts = _LazyModuleProxy("asky.cli.prompts")
chat = _LazyModuleProxy("asky.cli.chat")
utils = _LazyModuleProxy("asky.cli.utils")
sessions = _LazyModuleProxy("asky.cli.sessions")

CACHE_CLEANUP_JOIN_TIMEOUT_SECONDS = 0.05


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    from asky.cli.completion import (
        complete_answer_ids,
        complete_history_ids,
        complete_model_aliases,
        complete_session_tokens,
        complete_single_answer_id,
        parse_answer_selector_token,
        parse_session_selector_token,
        enable_argcomplete,
        complete_tool_names,
    )

    parser = argparse.ArgumentParser(
        description="Tool-calling CLI with model selection.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    model_action = parser.add_argument(
        "-m",
        "--model",
        default=DEFAULT_MODEL,
        choices=MODELS.keys(),
        help="Select the model alias",
    )
    continue_chat_action = parser.add_argument(
        "-c",
        "--continue-chat",
        dest="continue_ids",
        metavar="HISTORY_IDS",
        help="Continue conversation with context from specific history IDs (comma-separated, e.g. '1,2').",
    )
    parser.add_argument(
        "-s",
        "--summarize",
        action="store_true",
        help="Enable summarize mode (summarizes URL content and uses summaries for chat context)",
    )
    parser.add_argument(
        "--delete-messages",
        nargs="?",
        const="interactive",
        metavar="MESSAGE_SELECTOR",
        help="Delete message history records. usage: --delete-messages [ID|ID-ID|ID,ID] or --delete-messages --all",
    )
    parser.add_argument(
        "--delete-sessions",
        nargs="?",
        const="interactive",
        metavar="SESSION_SELECTOR",
        help="Delete session records and their messages. usage: --delete-sessions [ID|ID-ID|ID,ID] or --delete-sessions --all",
    )
    parser.add_argument(
        "--clean-session-research",
        metavar="SESSION_SELECTOR",
        help="Delete research data (findings and vectors) for a session but keep messages. usage: --clean-session-research [ID|NAME]",
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
        metavar="COUNT",
        help="Show last N queries and answer summaries (default 10).\n"
        "Use with --print-answer to print the full answer(s).",
    )
    print_answer_action = parser.add_argument(
        "-pa",
        "--print-answer",
        dest="print_ids",
        metavar="HISTORY_IDS",
        help="Print the answer(s) for specific history IDs (comma-separated).",
    )
    print_session_action = parser.add_argument(
        "-ps",
        "--print-session",
        dest="print_session",
        metavar="SESSION_SELECTOR",
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
        metavar="RECIPIENTS",
        help="Send the final answer via email to comma-separated addresses.",
    )
    parser.add_argument(
        "--subject",
        metavar="EMAIL_SUBJECT",
        help="Subject line for the email (used with --mail).",
    )
    parser.add_argument(
        "--push-data",
        dest="push_data_endpoint",
        metavar="ENDPOINT",
        help="Push query result to a configured endpoint after query completes.",
    )
    parser.add_argument(
        "--push-param",
        dest="push_params",
        action="append",
        nargs=2,
        metavar=("KEY", "VALUE"),
        help="Dynamic parameter for --push-data. Can be repeated. Example: --push-param title 'My Title'",
    )

    parser.add_argument(
        "-ss",
        "--sticky-session",
        nargs="+",
        metavar="SESSION_NAME",
        help="Create and activate a new named session (then exits). Usage: -ss My Session Name",
    )

    parser.add_argument(
        "--add-model",
        action="store_true",
        help="Interactively add a new model definition.",
    )

    parser.add_argument(
        "--edit-model",
        nargs="?",
        const="",
        metavar="MODEL_ALIAS",
        help="Interactively edit an existing model definition.",
    )

    resume_session_action = parser.add_argument(
        "-rs",
        "--resume-session",
        nargs="+",
        metavar="SESSION_SELECTOR",
        help="Resume an existing session by ID or name (partial match supported).",
    )
    parser.add_argument(
        "-se",
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
        metavar="COUNT",
        help="Show last N sessions (default 10).",
    )
    parser.add_argument(
        "-r",
        "--research",
        action="store_true",
        help="Enable deep research mode with link extraction and RAG-based content retrieval.\n"
        "In this mode, the LLM uses specialized tools:\n"
        "  - extract_links: Discover links (content cached, only links returned)\n"
        "  - get_link_summaries: Get AI summaries of cached pages\n"
        "  - get_relevant_content: RAG-based retrieval of relevant sections\n"
        "  - get_full_content: Get complete cached content",
    )
    parser.add_argument(
        "-lc",
        "--local-corpus",
        nargs="+",
        metavar="PATH",
        help="Local file or directory paths to ingest as research corpus. Implies --research.",
    )
    session_from_message_action = parser.add_argument(
        "-sfm",
        "--session-from-message",
        dest="session_from_message",
        metavar="HISTORY_ID",
        help="Convert a specific history message ID into a session and resume it.",
    )
    parser.add_argument(
        "--from-message",
        dest="session_from_message",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--reply",
        action="store_true",
        help="Resume the last conversation (converting history to session if needed).",
    )
    parser.add_argument(
        "-L",
        "--lean",
        action="store_true",
        help="Disable pre-LLM source shortlisting for this run (lean mode).",
    )
    parser.add_argument(
        "-off",
        "-tool-off",
        "--tool-off",
        dest="tool_off",
        action="append",
        default=[],
        metavar="TOOL",
        help='Disable an LLM tool for this run. Repeat or use comma-separated names, use "all" to disable all tools.  (e.g. -off web_search -off get_url_content).',
    )
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="List all available tools and exit.",
    )
    parser.add_argument(
        "--list-memories",
        action="store_true",
        help="List all saved user memories and exit.",
    )
    parser.add_argument(
        "--delete-memory",
        metavar="MEMORY_ID",
        type=int,
        help="Delete a user memory by ID and exit.",
    )
    parser.add_argument(
        "--clear-memories",
        action="store_true",
        help="Delete ALL user memories and exit.",
    )
    parser.add_argument(
        "-em",
        "--elephant-mode",
        action="store_true",
        help="Enable automatic memory extraction for this session.",
    )
    parser.add_argument(
        "-tl",
        "--terminal-lines",
        nargs="?",
        const="__default__",
        metavar="LINE_COUNT",
        help="Include the last N lines of terminal context in the query (default 10 if flag used without value).",
    )
    parser.add_argument(
        "-sp",
        "--system-prompt",
        help="Override the configured default system prompt for this run.",
    )
    parser.add_argument(
        "--completion-script",
        choices=["bash", "zsh"],
        help="Print shell setup snippet for argcomplete and exit.",
    )
    parser.add_argument("query", nargs="*", help="The query string")

    model_action.completer = complete_model_aliases
    continue_chat_action.completer = complete_history_ids
    print_answer_action.completer = complete_answer_ids
    print_session_action.completer = complete_session_tokens
    resume_session_action.completer = complete_session_tokens
    session_from_message_action.completer = complete_single_answer_id
    parser._option_string_actions["--tool-off"].completer = complete_tool_names

    enable_argcomplete(parser)
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


def ResearchCache(*args, **kwargs):
    """Lazy constructor proxy used for startup cleanup and tests."""
    from asky.research.cache import ResearchCache as research_cache_cls

    return research_cache_cls(*args, **kwargs)


def _run_research_cache_cleanup() -> None:
    """Best-effort cleanup of expired research cache entries."""
    import logging

    try:
        ResearchCache().cleanup_expired()
    except Exception as e:
        logging.getLogger(__name__).warning(f"Failed to cleanup research cache: {e}")


def _start_research_cache_cleanup_thread() -> threading.Thread:
    """Start expired-cache cleanup in background."""
    thread = threading.Thread(
        target=_run_research_cache_cleanup,
        name="asky-cache-cleanup",
        daemon=True,
    )
    thread.start()
    return thread


def main() -> None:
    """Main entry point."""
    args = parse_args()
    legacy_from_message = getattr(args, "from_message", None)
    if getattr(args, "session_from_message", None) is None and isinstance(
        legacy_from_message, int
    ):
        args.session_from_message = legacy_from_message

    if getattr(args, "print_session", None):
        parsed_session_id = parse_session_selector_token(str(args.print_session))
        if parsed_session_id is not None:
            args.print_session = str(parsed_session_id)

    if getattr(args, "resume_session", None):
        normalized_resume_tokens = []
        for token in args.resume_session:
            parsed_session_id = parse_session_selector_token(str(token))
            if parsed_session_id is None:
                normalized_resume_tokens.append(token)
            else:
                normalized_resume_tokens.append(str(parsed_session_id))
        args.resume_session = normalized_resume_tokens

    # Configure logging based on verbose flag
    if args.verbose:
        # Verbose: Timestamped file, DEBUG level
        session_log_file = generate_timestamped_log_path(LOG_FILE)
        setup_logging("DEBUG", session_log_file)
        import logging

        logging.debug("Verbose mode enabled. Log level set to DEBUG.")
    else:
        # Default: Standard file, Configured level
        setup_logging(LOG_LEVEL, LOG_FILE)

    if args.completion_script:
        from asky.cli.completion import build_completion_script

        print(build_completion_script(args.completion_script))
        return

    if args.add_model:
        from asky.cli.models import add_model_command

        add_model_command()
        return

    if args.edit_model is not None:
        from asky.cli.models import edit_model_command

        edit_model_command(args.edit_model or None)
        return

    if args.prompts:
        utils.load_custom_prompts()
        prompts.list_prompts_command()
        return

    if getattr(args, "list_tools", False):
        from asky.core.tool_registry_factory import get_all_available_tool_names

        tools = get_all_available_tool_names()
        print("\nAvailable LLM tools:")
        for t in tools:
            print(f"  - {t}")
        print()
        return

    if getattr(args, "list_memories", False):
        init_db()
        from asky.cli.memory_commands import handle_list_memories

        handle_list_memories()
        return

    if getattr(args, "delete_memory", None) is not None:
        init_db()
        from asky.cli.memory_commands import handle_delete_memory

        handle_delete_memory(args.delete_memory)
        return

    if getattr(args, "clear_memories", False):
        init_db()
        from asky.cli.memory_commands import handle_clear_memories

        handle_clear_memories()
        return

    needs_db = any(
        [
            args.history is not None,
            args.delete_messages is not None,
            args.delete_sessions is not None,
            args.print_session,
            args.print_ids,
            args.session_history is not None,
            args.session_end,
            bool(args.query),
            args.reply,  # Added for new logic
            getattr(args, "session_from_message", None),  # Added for new logic
        ]
    )
    if needs_db:
        init_db()

    # Handle Reply / From-Message shortcuts
    if args.reply or getattr(args, "session_from_message", None):
        repo = SQLiteHistoryRepository()
        target_id = None
        selector = getattr(args, "session_from_message", None)
        if selector is not None:
            target_id = parse_answer_selector_token(str(selector))
            if target_id is None:
                print(
                    "Error: Invalid value for --session-from-message. "
                    "Use an answer ID or a completion token ending with '__id_<ID>'."
                )
                return

        if args.reply:
            last = repo.get_last_interaction()
            if not last:
                print("Error: No conversation history to reply to.")
                return
            target_id = last.id

        if target_id:
            interaction = repo.get_interaction_by_id(target_id)
            if not interaction:
                print(f"Error: Message ID {target_id} not found.")
                return

            if interaction.session_id:
                # Already in a session
                args.resume_session = [str(interaction.session_id)]
                # If using --reply with no query, user might just want to resume?
                # But typically reply implies sending a message.
            else:
                # Convert to session
                try:
                    new_sid = repo.convert_history_to_session(target_id)
                    args.resume_session = [str(new_sid)]
                    print(f"Converted message {target_id} to Session {new_sid}.")
                except Exception as e:
                    print(f"Error converting message to session: {e}")
                    return

    # Commands that don't require banner or query
    if args.history is not None:
        history.show_history_command(args.history)
        return
    if history.handle_delete_messages_command(args):
        return
    if sessions.handle_delete_sessions_command(args):
        return
    if sessions.handle_clean_session_research_command(args):
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

    # Handle terminal lines argument
    # (Checking before query check because it might modify args.query)
    from asky.config import TERMINAL_CONTEXT_LINES

    if args.terminal_lines is not None:
        if args.terminal_lines == "__default__":
            # Flag used without value -> use config default
            args.terminal_lines = TERMINAL_CONTEXT_LINES
        else:
            # Value provided, check if integer
            try:
                val = int(args.terminal_lines)
                args.terminal_lines = val
            except ValueError:
                # Not an integer, treat as part of query
                # Push back to query list
                args.query.insert(0, args.terminal_lines)
                # Set terminal lines to default since flag was present
                args.terminal_lines = TERMINAL_CONTEXT_LINES

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
    raw_query_text = " ".join(args.query)
    if "/" in raw_query_text:
        utils.load_custom_prompts()
    query_text = utils.expand_query_text(raw_query_text, verbose=args.verbose)

    # Check for unresolved slash command
    if query_text.startswith("/"):
        parts = query_text.split(maxsplit=1)
        first_part = parts[0]  # e.g., "/" or "/gn" or "/nonexistent"

        if first_part == "/":
            # Just "/" - list all prompts
            prompts.list_prompts_command()
            return

        # Check if it's an unresolved prompt (still has / prefix after expansion)
        prefix = first_part[1:]  # Remove leading /
        if prefix and prefix not in USER_PROMPTS:
            # Unresolved - show filtered list
            prompts.list_prompts_command(filter_prefix=prefix)
            return

    # Verbose config logic is now handled at start of main (logging setup)

    # Note: When LIVE_BANNER is enabled, the InterfaceRenderer in run_chat
    # handles all banner display. When disabled, no banner is shown during chat.
    # The old show_banner() call here was redundant because the first redraw
    # in engine.run() would immediately clear it anyway.

    # Run Chat
    cleanup_thread = _start_research_cache_cleanup_thread()
    # Give the cleanup worker a brief head-start without blocking startup.
    cleanup_thread.join(timeout=CACHE_CLEANUP_JOIN_TIMEOUT_SECONDS)
    chat.run_chat(args, query_text)


if __name__ == "__main__":
    main()
