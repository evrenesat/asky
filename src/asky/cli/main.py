"""Command-line interface for asky."""

import argparse
import importlib
import logging
import platform
import re
import threading
import os
import subprocess
import sys
import time
from pathlib import Path
from asky.config import RESEARCH_LOCAL_DOCUMENT_ROOTS
from types import ModuleType
from typing import Any, Optional

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
from asky.storage import init_db, get_db_record_count, get_total_session_count
from asky.storage.sqlite import SQLiteHistoryRepository
from asky.cli.completion import (
    parse_answer_selector_token,
    parse_session_selector_token,
)
from asky.core import get_shell_session_id, set_shell_session_id
from asky.core.session_manager import generate_session_name


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
research_commands = _LazyModuleProxy("asky.cli.research_commands")
section_commands = _LazyModuleProxy("asky.cli.section_commands")

CACHE_CLEANUP_JOIN_TIMEOUT_SECONDS = 0.05
DEFAULT_MANUAL_QUERY_MAX_SOURCES = 20
DEFAULT_MANUAL_QUERY_MAX_CHUNKS = 3
DEFAULT_SECTION_DETAIL = "balanced"
MENUBAR_BOOTSTRAP_LOG_FILE = "~/.config/asky/logs/asky-menubar-bootstrap.log"
UNNAMED_SESSION_SENTINEL = "unnamed"
QUERY_DEFAULT_PENDING_AUTO_NAME_KEY = "pending_auto_name"
QUERY_DEFAULT_MODEL_KEY = "model"
QUERY_DEFAULT_SUMMARIZE_KEY = "summarize"
QUERY_DEFAULT_RESEARCH_KEY = "research"
QUERY_DEFAULT_LEAN_KEY = "lean"
QUERY_DEFAULT_SYSTEM_PROMPT_KEY = "system_prompt"
QUERY_DEFAULT_TOOL_OFF_KEY = "tool_off"
QUERY_DEFAULT_TERMINAL_LINES_KEY = "terminal_lines"
logger = logging.getLogger(__name__)
HELP_FLAG_TOKENS = {"-h", "--help"}


def _format_contribution_lines(contribution: "CLIContribution") -> list[str]:
    """Format one CLIContribution into indented help lines."""
    flags_str = ", ".join(contribution.flags)
    metavar = contribution.kwargs.get("metavar")
    if isinstance(metavar, tuple):
        metavar_str = " ".join(metavar)
    elif metavar:
        metavar_str = str(metavar)
    else:
        metavar_str = ""
    header = f"  {flags_str} {metavar_str}".rstrip() if metavar_str else f"  {flags_str}"
    help_text = contribution.kwargs.get("help", "")
    if help_text:
        return [header, f"      {help_text}"]
    return [header]


def _print_top_level_help(plugin_manager=None) -> None:
    """Print curated top-level help focused on user-facing command surface."""
    from asky.plugins.base import CATEGORY_LABELS, CapabilityCategory

    lines = [
        "usage: asky [query ...]",
        "       asky --config <domain> <action>",
        "       asky <group> <action> [args]",
        "",
        "Tool-calling CLI with grouped operational commands.",
        "",
        "Grouped commands:",
        "  history list [count]                    List recent history entries.",
        "  history show <id_selector>              Show full answer(s) for selected history item(s).",
        "  history delete <id_selector|--all>      Delete history entries.",
        "  session list [count]                    List recent sessions.",
        "  session show <session_selector>         Print session transcript.",
        "  session create <name>                   Create and activate a named session.",
        "  session use <session_selector>          Resume a session by id/name.",
        "  session end                             End active shell-bound session.",
        "  session delete <session_selector|--all> Delete sessions and their messages.",
        "  session clean-research <session_selector>",
        "                                          Remove research cache data for a session.",
        "  session from-message <history_id|last>  Convert history message into a session.",
        "  memory list                             List user memories.",
        "  memory delete <id>                      Delete one memory.",
        "  memory clear                            Delete all memories.",
        "  corpus query <text>                     Deterministic corpus query (no main model call).",
        "  corpus summarize [query]                Deterministic section summary flow.",
        "  prompts list                            List configured user prompts.",
        "",
        "Configuration:",
        "  --config model add",
        "  --config model edit [alias]",
        "  --config daemon edit",
        "",
        "Query options:",
        "  -m, --model ALIAS",
        "      Select model alias for this run.",
        "  -r, --research [CORPUS_POINTER]",
        "      Enable deep research mode; optionally bind local/web corpus source(s).",
        "  -s, --summarize",
        "      Summarize URL content before main answer generation.",
        "  -L, --lean",
        "      Lean mode: disable all tool calls, skip shortlist/memory recall preload,",
        "      and skip memory extraction/context compaction side effects.",
        "  -t, --turns MAX_TURNS",
        "      Set per-session max turns.",
        "  -sp, --system-prompt TEXT",
        "      Override system prompt.",
        "  -tl, --terminal-lines [LINE_COUNT]",
        "      Include recent terminal context in query.",
        "  --shortlist {on,off,reset}",
        "      Persist shortlist preference to current session (or clear with reset).",
        "  --tools [off [a,b,c]|reset]",
        "      List tools, disable all/some tools, or clear tool override.",
        "  --session <query...>",
        "      Create a new session named from query text and run the query.",
        "  -v, --verbose",
        "      Verbose output (-vv for double-verbose).",
    ]

    # Collect plugin contributions grouped by category.
    contributions_by_category: dict[str, list] = {}
    if plugin_manager is not None:
        for _, contrib in plugin_manager.collect_cli_contributions():
            contributions_by_category.setdefault(contrib.category, []).append(contrib)

    # Output Delivery: core --open is always present; plugins may add more.
    output_title, _ = CATEGORY_LABELS[CapabilityCategory.OUTPUT_DELIVERY]
    lines += ["", f"{output_title}:", "  -o, --open", "      Open final answer in browser."]
    for contrib in contributions_by_category.get(CapabilityCategory.OUTPUT_DELIVERY, []):
        lines += _format_contribution_lines(contrib)

    # Other categories appear only when a plugin contributes to them.
    for category in (
        CapabilityCategory.BROWSER_SETUP,
        CapabilityCategory.BACKGROUND_SERVICE,
        CapabilityCategory.SESSION_CONTROL,
    ):
        contribs = contributions_by_category.get(category, [])
        if contribs:
            cat_title, _ = CATEGORY_LABELS[category]
            lines += ["", f"{cat_title}:"]
            for contrib in contribs:
                lines += _format_contribution_lines(contrib)

    lines += [
        "",
        "Process options:",
        "  --completion-script {bash,zsh}",
        "",
        "More help:",
        "  asky --help-all",
        "  asky corpus --help",
        "  asky corpus query --help",
        "  asky corpus summarize --help",
        "  asky history --help",
        "  asky session --help",
        "  asky memory --help",
    ]
    print("\n".join(lines))


def _print_corpus_help() -> None:
    """Print grouped help for corpus operations."""
    print(
        """usage: asky corpus <query|summarize> ...

Corpus commands:
  asky corpus query <text>
  asky corpus summarize [query]

Run:
  asky corpus query --help
  asky corpus summarize --help"""
    )


def _print_corpus_query_help() -> None:
    """Print help for corpus query subcommand."""
    print(
        """usage: asky corpus query <text> [options]

Deterministically query cached/ingested corpus without invoking the main model.

Options:
  --query-corpus-max-sources COUNT
      Maximum corpus sources to scan (default 20).
  --query-corpus-max-chunks COUNT
      Maximum chunks per source (default 3).
  --section-include-toc
      Include TOC/micro heading rows in corpus section output."""
    )


def _print_corpus_summarize_help() -> None:
    """Print help for corpus summarize subcommand."""
    print(
        """usage: asky corpus summarize [query] [options]

Summarize corpus sections without invoking the main model.

Options:
  --section-source SOURCE
      Select corpus source (corpus://cache/<id>, cache id, title/url match).
  --section-id SECTION_ID
      Select exact section ID.
  --section-include-toc
      Include TOC/micro heading rows when listing sections.
  --section-detail {balanced,max,compact}
      Section summary detail profile (default balanced).
  --section-max-chunks COUNT
      Optional chunk limit for section summarization."""
    )


def _print_history_help() -> None:
    """Print grouped help for history operations."""
    print(
        """usage: asky history <list|show|delete> [args]

Commands:
  asky history list [count]
  asky history show <id_selector>
  asky history delete <id_selector|--all>"""
    )


def _print_session_help() -> None:
    """Print grouped help for session operations."""
    print(
        """usage: asky session <action> [args]

Commands:
  asky session list [count]
  asky session show <session_selector>
  asky session create <name>
  asky session use <session_selector>
  asky session end
  asky session delete <session_selector|--all>
  asky session clean-research <session_selector>
  asky session from-message <history_id|last>"""
    )


def _print_memory_help() -> None:
    """Print grouped help for memory operations."""
    print(
        """usage: asky memory <list|delete|clear> [args]

Commands:
  asky memory list
  asky memory delete <id>
  asky memory clear"""
    )


def _print_prompts_help() -> None:
    """Print grouped help for prompts operations."""
    print(
        """usage: asky prompts list

Commands:
  asky prompts list"""
    )


def _consume_grouped_help(tokens: list[str], plugin_manager=None) -> bool:
    """Render grouped help pages and short-circuit parse flow when requested."""
    option_tokens = list(tokens)
    if "--" in option_tokens:
        option_tokens = option_tokens[: option_tokens.index("--")]
    if not any(token in HELP_FLAG_TOKENS for token in option_tokens):
        return False

    visible_tokens = [t for t in option_tokens if t not in HELP_FLAG_TOKENS]
    if not visible_tokens or str(visible_tokens[0]).startswith("-"):
        _print_top_level_help(plugin_manager)
        raise SystemExit(0)

    group = str(visible_tokens[0]).strip().lower()
    action = (
        str(visible_tokens[1]).strip().lower()
        if len(visible_tokens) >= 2
        else ""
    )
    if group == "corpus":
        if action == "query":
            _print_corpus_query_help()
            raise SystemExit(0)
        if action in {"summarize", "summarize-section"}:
            _print_corpus_summarize_help()
            raise SystemExit(0)
        _print_corpus_help()
        raise SystemExit(0)
    if group == "history":
        _print_history_help()
        raise SystemExit(0)
    if group == "session":
        _print_session_help()
        raise SystemExit(0)
    if group == "memory":
        _print_memory_help()
        raise SystemExit(0)
    if group == "prompts":
        _print_prompts_help()
        raise SystemExit(0)
    return False


def _is_flag_token(token: str) -> bool:
    """Return True when token looks like a flag."""
    return str(token).startswith("-")


def _consume_text_until_flag(tokens: list[str]) -> tuple[str, list[str]]:
    """Split positional text tokens from trailing option tokens."""
    text_tokens: list[str] = []
    index = 0
    while index < len(tokens):
        token = str(tokens[index])
        if _is_flag_token(token):
            break
        text_tokens.append(token)
        index += 1
    text = " ".join(t for t in text_tokens if str(t).strip()).strip()
    return text, list(tokens[index:])


def _translate_config_tokens(tokens: list[str]) -> list[str]:
    """Translate --config domain/action surface to internal flags."""
    if "--config" not in tokens:
        return tokens
    config_index = tokens.index("--config")
    if config_index + 2 >= len(tokens):
        raise ValueError("Usage: --config <domain> <action>")

    prefix = list(tokens[:config_index])
    domain = str(tokens[config_index + 1]).strip().lower()
    action = str(tokens[config_index + 2]).strip().lower()
    rest = list(tokens[config_index + 3 :])

    if domain == "model" and action == "add":
        if rest:
            raise ValueError("Usage: --config model add")
        return [*prefix, "--add-model"]
    if domain == "model" and action == "edit":
        if len(rest) > 1:
            raise ValueError("Usage: --config model edit [alias]")
        if not rest:
            return [*prefix, "--edit-model"]
        return [*prefix, "--edit-model", str(rest[0])]
    if domain == "daemon" and action == "edit":
        if rest:
            raise ValueError("Usage: --config daemon edit")
        return [*prefix, "--edit-daemon"]

    raise ValueError(f"Unknown config command: --config {domain} {action}")


def _translate_grouped_command_tokens(tokens: list[str]) -> list[str]:
    """Translate grouped noun/action commands into legacy parser flags."""
    if len(tokens) < 2 or _is_flag_token(tokens[0]):
        return tokens

    noun = str(tokens[0]).strip().lower()
    action = str(tokens[1]).strip().lower()
    rest = list(tokens[2:])

    if noun == "history":
        if action == "list":
            return ["--history"] + rest[:1]
        if action == "show":
            selector = " ".join(rest).strip()
            if not selector:
                return tokens
            return ["--print-answer", selector]
        if action == "delete":
            if not rest:
                return tokens
            if rest[0] == "--all":
                return ["--delete-messages", "--all"]
            selector = " ".join(rest).strip()
            return ["--delete-messages", selector]
        return tokens

    if noun == "session":
        if action == "list":
            return ["--session-history"] + rest[:1]
        if action == "show":
            selector = " ".join(rest).strip()
            if not selector:
                return tokens
            return ["--print-session", selector]
        if action == "create":
            if not rest:
                return tokens
            return ["--sticky-session", *rest]
        if action == "use":
            if not rest:
                return tokens
            return ["--resume-session", *rest]
        if action == "end":
            return ["--session-end"]
        if action == "delete":
            if not rest:
                return tokens
            if rest[0] == "--all":
                return ["--delete-sessions", "--all"]
            selector = " ".join(rest).strip()
            return ["--delete-sessions", selector]
        if action == "clean-research":
            selector = " ".join(rest).strip()
            if not selector:
                return tokens
            return ["--clean-session-research", selector]
        if action == "from-message":
            selector = " ".join(rest).strip()
            if not selector:
                return tokens
            if selector.lower() == "last":
                return ["--reply"]
            return ["--session-from-message", selector]
        return tokens

    if noun == "memory":
        if action == "list":
            return ["--list-memories"]
        if action == "delete":
            if not rest:
                return tokens
            return ["--delete-memory", str(rest[0])]
        if action == "clear":
            return ["--clear-memories"]
        return tokens

    if noun == "corpus":
        if action == "query":
            text, options = _consume_text_until_flag(rest)
            if not text:
                return tokens
            return ["--query-corpus", text, *options]
        if action in {"summarize", "summarize-section"}:
            text, options = _consume_text_until_flag(rest)
            if text:
                return ["--summarize-section", text, *options]
            return ["--summarize-section", *options]
        return tokens

    if noun == "prompts" and action == "list":
        return ["--prompts"]

    return tokens


def _translate_tools_tokens(tokens: list[str]) -> list[str]:
    """Translate --tools UX surface to existing tool flags."""
    if "--tools" not in tokens:
        return tokens

    translated: list[str] = []
    index = 0
    while index < len(tokens):
        token = str(tokens[index])
        if token != "--tools":
            translated.append(token)
            index += 1
            continue

        next_token = str(tokens[index + 1]) if index + 1 < len(tokens) else ""
        if not next_token or _is_flag_token(next_token):
            translated.append("--list-tools")
            index += 1
            continue

        mode = next_token.strip().lower()
        if mode == "off":
            value_token = (
                str(tokens[index + 2]) if index + 2 < len(tokens) else ""
            )
            if not value_token or _is_flag_token(value_token):
                translated.extend(["--tool-off", "all"])
                index += 2
            else:
                translated.extend(["--tool-off", value_token])
                index += 3
            continue

        if mode == "reset":
            translated.append("--tools-reset")
            index += 2
            continue

        raise ValueError("Usage: --tools [off [a,b,c]|reset]")

    return translated


def _translate_process_tokens(tokens: list[str]) -> list[str]:
    """Translate top-level process aliases to internal flags."""
    translated: list[str] = []
    index = 0
    while index < len(tokens):
        token = str(tokens[index])
        if token == "--daemon":
            translated.append("--xmpp-daemon")
            index += 1
            continue
        translated.append(token)
        index += 1
    return translated


def _translate_session_query_tokens(tokens: list[str]) -> list[str]:
    """Translate --session <query...> to sticky-session + query."""
    if "--session" not in tokens:
        return tokens
    session_index = tokens.index("--session")
    query_tokens = [str(t) for t in tokens[session_index + 1 :]]
    if not query_tokens:
        raise ValueError("Usage: --session <query...>")
    query_text = " ".join(query_tokens).strip()
    session_name = generate_session_name(query_text) or UNNAMED_SESSION_SENTINEL
    return [
        *tokens[:session_index],
        "--sticky-session",
        session_name,
        "--",
        *query_tokens,
    ]


def _translate_cli_tokens(tokens: list[str]) -> list[str]:
    """Translate new command surface into parser-compatible tokens."""
    translated = list(tokens)
    translated = _translate_config_tokens(translated)
    translated = _translate_grouped_command_tokens(translated)
    translated = _translate_process_tokens(translated)
    translated = _translate_tools_tokens(translated)
    translated = _translate_session_query_tokens(translated)
    return translated


def _flag_present(tokens: list[str], *flag_names: str) -> bool:
    """Check whether any of the provided flags are present."""
    available = set(flag_names)
    return any(str(token) in available for token in tokens)


_INTERNAL_ONLY_FLAGS = frozenset({
    # Commands that handle themselves before any plugin flags are needed.
    "--config", "--add-model", "--edit-model", "-me",
    "--help-all",
    "--completion-script", "--prompts", "-p",
    "--delete-messages", "--delete-sessions",
})


def _bootstrap_plugin_manager_for_cli(argv: Optional[list[str]] = None):
    """Load the plugin roster for CLI arg collection without activating plugins.

    Returns a PluginManager with roster loaded, or None on any error or when
    the invocation is clearly an internal-only command that does not benefit
    from plugin-contributed CLI flags.
    """
    raw = list(sys.argv[1:] if argv is None else argv)
    if any(token in _INTERNAL_ONLY_FLAGS for token in raw):
        return None
    try:
        from asky.plugins.manager import PluginManager

        manager = PluginManager()
        manager.load_roster()
        return manager
    except Exception:
        logger.debug("Plugin manager bootstrap failed; skipping plugin CLI contributions", exc_info=True)
        return None


def _add_plugin_contributions_to_parser(
    parser: argparse.ArgumentParser,
    plugin_manager,
    pre_created_groups: Optional[dict[str, Any]] = None,
) -> None:
    """Add plugin-contributed CLI flags to named argparse groups.

    ``pre_created_groups`` maps category constants to already-created
    ArgumentGroup objects so they can be reused rather than duplicated.
    """
    from asky.plugins.base import CATEGORY_LABELS

    contributions = plugin_manager.collect_cli_contributions()
    if not contributions:
        return

    groups_by_category: dict[str, Any] = dict(pre_created_groups or {})
    for _plugin_name, contribution in contributions:
        category = contribution.category
        if category not in groups_by_category:
            title, description = CATEGORY_LABELS.get(category, (category, ""))
            groups_by_category[category] = parser.add_argument_group(title, description)
        try:
            groups_by_category[category].add_argument(*contribution.flags, **contribution.kwargs)
        except argparse.ArgumentError:
            logger.debug(
                "Plugin CLI contribution conflict for flags %s; skipping",
                contribution.flags,
            )


def parse_args(argv: Optional[list[str]] = None, plugin_manager=None) -> argparse.Namespace:
    """Parse command-line arguments."""
    raw_tokens = list(sys.argv[1:] if argv is None else argv)
    _consume_grouped_help(raw_tokens, plugin_manager=plugin_manager)
    try:
        legacy_config_flags = {
            "--add-model": "--config model add",
            "--edit-model": "--config model edit [alias]",
            "--edit-daemon": "--config daemon edit",
        }
        for legacy_flag, replacement in legacy_config_flags.items():
            if legacy_flag in raw_tokens:
                raise ValueError(
                    f"{legacy_flag} is removed. Use `{replacement}` instead."
                )
        normalized_tokens = _translate_cli_tokens(raw_tokens)
    except ValueError as exc:
        parser = argparse.ArgumentParser(prog="asky")
        parser.error(str(exc))
        raise AssertionError("unreachable")

    from asky.cli.completion import (
        complete_answer_ids,
        complete_history_ids,
        complete_model_aliases,
        complete_session_tokens,
        complete_single_answer_id,
        parse_session_selector_token,
        enable_argcomplete,
        complete_tool_names,
    )

    parser = argparse.ArgumentParser(
        prog="asky",
        description="Tool-calling CLI with model selection.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--help-all",
        action="help",
        help="Show full option reference including advanced/internal routing flags.",
    )
    
    # Note: persona subcommand is handled separately in main() before parse_args()
    # to avoid conflicts with query positional argument
    
    model_action = parser.add_argument(
        "-m",
        "--model",
        default=DEFAULT_MODEL,
        choices=MODELS.keys(),
        help="Select the model alias",
    )
    CONTINUE_LAST_SENTINEL = "__last__"
    continue_chat_action = parser.add_argument(
        "-c",
        "--continue-chat",
        dest="continue_ids",
        nargs="?",
        const=CONTINUE_LAST_SENTINEL,
        metavar="HISTORY_IDS",
        help="Continue conversation from specific history IDs (comma-separated). Omit value to continue from the last message.",
    )
    parser.add_argument(
        "-s",
        "--summarize",
        action="store_true",
        help="Enable summarize mode (summarizes URL content and uses summaries for chat context)",
    )
    parser.add_argument(
        "-t",
        "--turns",
        type=int,
        metavar="MAX_TURNS",
        help="Override the configured maximum turn count for this session.",
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
        action="count",
        default=0,
        dest="verbose_level",
        help="Enable verbose output. Use -vv for double-verbose request payload tracing.",
    )
    from asky.plugins.base import CATEGORY_LABELS, CapabilityCategory

    output_delivery_group = parser.add_argument_group(
        *CATEGORY_LABELS[CapabilityCategory.OUTPUT_DELIVERY]
    )
    output_delivery_group.add_argument(
        "-o",
        "--open",
        action="store_true",
        help="Open the final answer in a browser using a markdown template.",
    )

    parser.add_argument(
        "-ss",
        "--sticky-session",
        nargs="+",
        metavar="SESSION_NAME",
        help="Create and activate a new named session (then exits). Usage: -ss My Session Name",
    )

    parser.add_argument(
        "--config",
        nargs=2,
        metavar=("DOMAIN", "ACTION"),
        help="Configuration entrypoint. Examples: --config model add, --config model edit, --config daemon edit.",
    )
    parser.add_argument(
        "--session",
        nargs=argparse.REMAINDER,
        metavar="QUERY",
        help="Create a new session named from query text and run the query.",
    )
    parser.add_argument(
        "--tools",
        nargs="*",
        metavar="MODE",
        help="Tool controls: --tools (list), --tools off [a,b], --tools reset.",
    )

    parser.add_argument(
        "--add-model",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    parser.add_argument(
        "-me",
        "--edit-model",
        nargs="?",
        const="",
        metavar="MODEL_ALIAS",
        help=argparse.SUPPRESS,
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
        "-es",
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
        nargs="?",
        const=True,
        default=False,
        metavar="CORPUS_POINTER",
        help="Enable deep research mode with optional local corpus pointer (file, directory, or comma-separated names).\n"
        "If pointer provided, it is resolved against local_document_roots. The rest of arguments are the query.\n"
        "Special tools available in this mode:\n"
        "  - extract_links: Discover links (content cached, only links returned)\n"
        "  - get_link_summaries: Get AI summaries of cached pages\n"
        "  - get_relevant_content: RAG-based retrieval of relevant sections\n"
        "  - get_full_content: Get complete cached content",
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
        help=(
            "Lean mode: disable all tool calls, skip shortlist/memory recall "
            "preload, and skip memory extraction/context compaction side effects."
        ),
    )
    parser.add_argument(
        "--shortlist",
        choices=["on", "off", "reset"],
        default=None,
        help=(
            "Control source shortlisting. 'on'/'off' writes the preference to the "
            "session so it persists for all future turns. 'reset' erases any stored "
            "session preference (future turns fall back to config). "
            "Omit to read the session-stored preference without modifying it, "
            "falling back to config defaults if nothing is stored."
        ),
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
        "--query-corpus",
        metavar="QUERY",
        help="Query cached/ingested research corpus directly without invoking any model.",
    )
    parser.add_argument(
        "--query-corpus-max-sources",
        type=int,
        default=DEFAULT_MANUAL_QUERY_MAX_SOURCES,
        metavar="COUNT",
        help=(
            "Maximum corpus sources to scan for --query-corpus "
            f"(default {DEFAULT_MANUAL_QUERY_MAX_SOURCES})."
        ),
    )
    parser.add_argument(
        "--query-corpus-max-chunks",
        type=int,
        default=DEFAULT_MANUAL_QUERY_MAX_CHUNKS,
        metavar="COUNT",
        help=(
            "Maximum chunks per source for --query-corpus "
            f"(default {DEFAULT_MANUAL_QUERY_MAX_CHUNKS})."
        ),
    )
    parser.add_argument(
        "--summarize-section",
        nargs="?",
        const="",
        metavar="SECTION_QUERY",
        help=(
            "Summarize a section from local corpus without calling the main model. "
            "If used without value, lists detected sections."
        ),
    )
    parser.add_argument(
        "--section-source",
        metavar="SOURCE",
        help=(
            "Choose local corpus source for --summarize-section "
            "(corpus://cache/<id>, cache id, or title/url match)."
        ),
    )
    parser.add_argument(
        "--section-id",
        metavar="SECTION_ID",
        help=(
            "Exact section ID for deterministic --summarize-section selection. "
            "Overrides title-query matching."
        ),
    )
    parser.add_argument(
        "--section-include-toc",
        action="store_true",
        help=(
            "Include TOC/micro heading rows when listing sections with "
            "--summarize-section and no section query."
        ),
    )
    parser.add_argument(
        "--section-detail",
        choices=["balanced", "max", "compact"],
        default=DEFAULT_SECTION_DETAIL,
        help=(
            "Detail profile for --summarize-section "
            f"(default {DEFAULT_SECTION_DETAIL})."
        ),
    )
    parser.add_argument(
        "--section-max-chunks",
        type=int,
        metavar="COUNT",
        help=(
            "Optional chunk limit for --summarize-section input slicing before "
            "hierarchical summarization."
        ),
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
    parser.add_argument(
        "--tools-reset",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    # Internal process-spawning flags: always registered regardless of plugin state.
    parser.add_argument("--xmpp-daemon", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--edit-daemon", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--xmpp-menubar-child", action="store_true", help=argparse.SUPPRESS)
    if plugin_manager is not None:
        _add_plugin_contributions_to_parser(
            parser,
            plugin_manager,
            pre_created_groups={CapabilityCategory.OUTPUT_DELIVERY: output_delivery_group},
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
    
    parsed_args = parser.parse_args(normalized_tokens)
    parsed_args._raw_tokens = raw_tokens
    parsed_args._normalized_tokens = normalized_tokens
    parsed_args._provided_model = _flag_present(raw_tokens, "-m", "--model")
    parsed_args._provided_summarize = _flag_present(raw_tokens, "-s", "--summarize")
    parsed_args._provided_turns = _flag_present(raw_tokens, "-t", "--turns")
    parsed_args._provided_research = _flag_present(raw_tokens, "-r", "--research")
    parsed_args._provided_shortlist = _flag_present(raw_tokens, "--shortlist")
    parsed_args._provided_tools = _flag_present(
        raw_tokens, "--tools", "-off", "-tool-off", "--tool-off"
    )
    parsed_args._provided_lean = _flag_present(raw_tokens, "-L", "--lean")
    parsed_args._provided_system_prompt = _flag_present(
        raw_tokens, "-sp", "--system-prompt"
    )
    parsed_args._provided_elephant_mode = _flag_present(
        raw_tokens, "-em", "--elephant-mode"
    )
    parsed_args._provided_terminal_lines = _flag_present(
        raw_tokens, "-tl", "--terminal-lines"
    )
    parsed_args._provided_session_query = _flag_present(raw_tokens, "--session")

    if bool(getattr(parsed_args, "daemon", False)) and not bool(
        getattr(parsed_args, "xmpp_daemon", False)
    ):
        parsed_args.xmpp_daemon = True

    parsed_args.verbose_level = int(getattr(parsed_args, "verbose_level", 0) or 0)
    parsed_args.verbose = parsed_args.verbose_level >= 1
    parsed_args.double_verbose = parsed_args.verbose_level >= 2
    return parsed_args


def show_banner(args) -> None:
    """Display the application banner."""
    model_alias = args.model
    model_id = MODELS[model_alias]["id"]
    sum_alias = SUMMARIZATION_MODEL
    sum_id = MODELS[sum_alias]["id"]

    model_ctx = MODELS[model_alias].get("context_size", DEFAULT_CONTEXT_SIZE)
    sum_ctx = MODELS[sum_alias].get("context_size", DEFAULT_CONTEXT_SIZE)
    db_count = get_db_record_count()

    try:
        total_sessions = get_total_session_count()
    except Exception:
        total_sessions = 0

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
        total_sessions=total_sessions,
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
        )
        return True
    return False


def _is_valid_history_selector(value: str) -> bool:
    """Validate history selector syntax used by print-answer paths."""
    normalized = str(value or "").strip()
    if not normalized:
        return False
    token_pattern = r"(?:[sS]?\d+|~\d+|__hid_\d+|\d+-\d+)"
    return re.fullmatch(rf"{token_pattern}(?:,{token_pattern})*", normalized) is not None


def _recover_history_show_as_query(args: argparse.Namespace) -> bool:
    """Recover grouped `history show ...` misuse as query when selector is invalid."""
    raw_tokens = list(getattr(args, "_raw_tokens", []) or [])
    if len(raw_tokens) < 3:
        return False
    if str(raw_tokens[0]).lower() != "history" or str(raw_tokens[1]).lower() != "show":
        return False

    selector = " ".join(str(t) for t in raw_tokens[2:]).strip()
    if _is_valid_history_selector(selector):
        return False
    args.print_ids = None
    args.query = [selector]
    return True


def ResearchCache(*args, **kwargs):
    """Lazy constructor proxy used for startup cleanup and tests."""
    from asky.research.cache import ResearchCache as research_cache_cls

    return research_cache_cls(*args, **kwargs)


def _run_research_cache_cleanup() -> None:
    """Best-effort cleanup of expired research cache entries."""
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


def _research_roots() -> list[Path]:
    """Return normalized configured research corpus roots."""
    roots: list[Path] = []
    for raw_root in RESEARCH_LOCAL_DOCUMENT_ROOTS:
        try:
            roots.append(Path(str(raw_root)).expanduser().resolve())
        except Exception:
            continue
    return roots


def _path_within_roots(path: Path, roots: list[Path]) -> bool:
    """Return True when path is under one of configured corpus roots."""
    for root in roots:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _looks_like_pointer_token(token: str) -> bool:
    """Heuristic to disambiguate pointer tokens from plain query text."""
    if token.lower() == "web":
        return True
    if token.startswith(("/", "./", "../", "~")):
        return True
    if len(token) > 2 and token[1] == ":":
        return True
    if "/" in token or "\\" in token:
        return True
    return False


def _manual_corpus_query_arg(args: argparse.Namespace) -> Optional[str]:
    """Return normalized manual corpus query text when explicitly provided."""
    value = getattr(args, "query_corpus", None)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _manual_section_query_arg(args: argparse.Namespace) -> Optional[str]:
    """Return normalized section query value for --summarize-section."""
    value = getattr(args, "summarize_section", None)
    if value is None:
        return None
    if not isinstance(value, str):
        return ""
    return value.strip()


def _resolve_research_corpus(
    research_arg: str | bool,
) -> tuple[bool, list[str] | None, str | None, str | None, bool]:
    """Resolve research flag to mode/corpus tuple.

    Returns:
      (research_enabled, local_paths, leftover_query_token, source_mode, replace_corpus)
    """
    if research_arg is False or research_arg is None:
        return False, None, None, None, False

    if research_arg is True:
        # Flag used without value (-r -- "query")
        return True, None, None, None, False

    # Flag used with optional corpus pointer (-r "token" "query")
    raw_pointer = str(research_arg).strip()
    if not raw_pointer:
        return True, None, None, None, False

    tokens = [t.strip() for t in raw_pointer.split(",") if t.strip()]
    if not tokens:
        return True, None, None, None, False

    is_explicit_list = "," in raw_pointer
    resolved_paths: list[str] = []
    has_web_token = False
    roots = _research_roots()

    for token in tokens:
        if token.lower() == "web":
            has_web_token = True
            continue

        expanded_token = os.path.expanduser(token)
        absolute_candidate = (
            Path(expanded_token).resolve() if os.path.isabs(expanded_token) else None
        )

        if absolute_candidate is not None and (
            absolute_candidate.is_file() or absolute_candidate.is_dir()
        ):
            if not roots:
                raise ValueError(
                    "local_document_roots is empty; configure research.local_document_roots to allow local corpus paths."
                )
            if not _path_within_roots(absolute_candidate, roots):
                raise ValueError(
                    f"Corpus pointer '{token}' is outside configured local_document_roots."
                )
            resolved_paths.append(str(absolute_candidate))
            continue

        found = False
        for root in roots:
            full_path = (root / expanded_token.lstrip("/")).resolve()
            if not _path_within_roots(full_path, [root]):
                continue
            if full_path.is_file() or full_path.is_dir():
                resolved_paths.append(str(full_path))
                found = True
                break

        if not found:
            # If it was a list (a,b) or looked like a path (/...), we fail fast.
            # If it's a single token that doesn't exist, we treat it as query start.
            if is_explicit_list or _looks_like_pointer_token(token):
                raise ValueError(
                    f"Corpus pointer '{token}' could not be resolved. "
                    f"Check your local_document_roots in research.toml."
                )
            else:
                # Treat as query start
                return True, None, raw_pointer, None, False

    if has_web_token and resolved_paths:
        return True, resolved_paths, None, "mixed", True
    if has_web_token:
        return True, [], None, "web_only", True
    return True, resolved_paths, None, "local_only", True



def _parse_tool_off_values(raw_values: list[str]) -> list[str]:
    """Normalize repeated/comma-separated tool names."""
    parsed: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        for token in str(raw_value).split(","):
            normalized = token.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            parsed.append(normalized)
    return parsed


def _apply_shell_session_defaults(args: argparse.Namespace) -> None:
    """Apply persisted defaults from current shell-bound session when flags are omitted."""
    shell_session_id = get_shell_session_id()
    if not shell_session_id:
        return
    init_db()
    repo = SQLiteHistoryRepository()
    session = repo.get_session_by_id(int(shell_session_id))
    if not session:
        return

    defaults = dict(getattr(session, "query_defaults", None) or {})

    if not getattr(args, "_provided_model", False):
        model_alias = str(defaults.get(QUERY_DEFAULT_MODEL_KEY, "")).strip()
        if model_alias and model_alias in MODELS:
            args.model = model_alias

    if not getattr(args, "_provided_summarize", False):
        if bool(defaults.get(QUERY_DEFAULT_SUMMARIZE_KEY, False)):
            args.summarize = True

    if not getattr(args, "_provided_research", False):
        if bool(defaults.get(QUERY_DEFAULT_RESEARCH_KEY, False)):
            args.research = True

    if not getattr(args, "_provided_lean", False):
        if bool(defaults.get(QUERY_DEFAULT_LEAN_KEY, False)):
            args.lean = True

    if not getattr(args, "_provided_system_prompt", False):
        persisted_prompt = str(defaults.get(QUERY_DEFAULT_SYSTEM_PROMPT_KEY, "")).strip()
        if persisted_prompt:
            args.system_prompt = persisted_prompt

    if not getattr(args, "_provided_tools", False):
        persisted_tools = defaults.get(QUERY_DEFAULT_TOOL_OFF_KEY, [])
        if isinstance(persisted_tools, list) and persisted_tools:
            args.tool_off = [",".join(str(item) for item in persisted_tools)]
    if not getattr(args, "_provided_terminal_lines", False):
        persisted_terminal_lines = defaults.get(QUERY_DEFAULT_TERMINAL_LINES_KEY, None)
        if isinstance(persisted_terminal_lines, int) and persisted_terminal_lines > 0:
            args.terminal_lines = persisted_terminal_lines


def _build_session_default_updates(args: argparse.Namespace) -> dict[str, Any]:
    """Extract explicit query-behavior defaults from current invocation."""
    updates: dict[str, Any] = {}
    if getattr(args, "_provided_model", False):
        updates[QUERY_DEFAULT_MODEL_KEY] = str(getattr(args, "model", "")).strip()
    if getattr(args, "_provided_summarize", False) and bool(getattr(args, "summarize", False)):
        updates[QUERY_DEFAULT_SUMMARIZE_KEY] = True
    if getattr(args, "_provided_research", False) and bool(getattr(args, "research", False)):
        updates[QUERY_DEFAULT_RESEARCH_KEY] = True
    if getattr(args, "_provided_lean", False) and bool(getattr(args, "lean", False)):
        updates[QUERY_DEFAULT_LEAN_KEY] = True
    if getattr(args, "_provided_system_prompt", False):
        updates[QUERY_DEFAULT_SYSTEM_PROMPT_KEY] = str(
            getattr(args, "system_prompt", "") or ""
        ).strip()
    if getattr(args, "_provided_terminal_lines", False):
        terminal_value = getattr(args, "terminal_lines", None)
        if isinstance(terminal_value, int) and terminal_value > 0:
            updates[QUERY_DEFAULT_TERMINAL_LINES_KEY] = terminal_value
    if getattr(args, "_provided_tools", False):
        if bool(getattr(args, "tools_reset", False)):
            updates[QUERY_DEFAULT_TOOL_OFF_KEY] = []
        else:
            updates[QUERY_DEFAULT_TOOL_OFF_KEY] = _parse_tool_off_values(
                list(getattr(args, "tool_off", []) or [])
            )
    return updates


def _persist_session_defaults(
    *,
    session_id: int,
    args: argparse.Namespace,
    mark_pending_auto_name: bool = False,
) -> None:
    """Persist invocation-provided session default settings."""
    repo = SQLiteHistoryRepository()
    session = repo.get_session_by_id(int(session_id))
    if not session:
        return

    merged_defaults = dict(getattr(session, "query_defaults", None) or {})
    for key, value in _build_session_default_updates(args).items():
        if key == QUERY_DEFAULT_TOOL_OFF_KEY and value == []:
            merged_defaults.pop(key, None)
            continue
        if key == QUERY_DEFAULT_SYSTEM_PROMPT_KEY and not value:
            merged_defaults.pop(key, None)
            continue
        merged_defaults[key] = value

    if mark_pending_auto_name:
        merged_defaults[QUERY_DEFAULT_PENDING_AUTO_NAME_KEY] = True

    repo.update_session_query_defaults(int(session_id), merged_defaults)

    if getattr(args, "_provided_turns", False) and getattr(args, "turns", None) is not None:
        repo.update_session_max_turns(int(session_id), int(args.turns))
    if getattr(args, "_provided_elephant_mode", False) and bool(
        getattr(args, "elephant_mode", False)
    ):
        repo.set_session_memory_auto_extract(int(session_id), True)
    if getattr(args, "_provided_shortlist", False):
        shortlist_value = getattr(args, "shortlist", None)
        if shortlist_value in {"on", "off"}:
            repo.update_session_shortlist_override(int(session_id), shortlist_value)
        elif shortlist_value == "reset":
            repo.update_session_shortlist_override(int(session_id), None)


def _needs_defaults_only_session(args: argparse.Namespace) -> bool:
    """Return True when invocation should only persist defaults and exit."""
    if bool(getattr(args, "query", [])):
        return False
    if bool(getattr(args, "playwright_login", None)):
        return False
    if bool(getattr(args, "xmpp_daemon", False)):
        return False
    if bool(getattr(args, "edit_daemon", False)):
        return False
    if bool(getattr(args, "completion_script", None)):
        return False

    return any(
        [
            bool(getattr(args, "_provided_model", False)),
            bool(getattr(args, "_provided_summarize", False)),
            bool(getattr(args, "_provided_turns", False)),
            bool(getattr(args, "_provided_research", False)),
            bool(getattr(args, "_provided_shortlist", False)),
            bool(getattr(args, "_provided_tools", False)),
            bool(getattr(args, "_provided_lean", False)),
            bool(getattr(args, "_provided_system_prompt", False)),
            bool(getattr(args, "_provided_elephant_mode", False)),
            bool(getattr(args, "_provided_terminal_lines", False)),
        ]
    )


def _ensure_defaults_session(args: argparse.Namespace) -> tuple[int, bool]:
    """Resolve or create a target session for defaults-only invocations."""
    init_db()
    repo = SQLiteHistoryRepository()

    if getattr(args, "sticky_session", None):
        session_name = " ".join(str(t) for t in args.sticky_session).strip()
        session_id = repo.create_session(
            model=str(getattr(args, "model", DEFAULT_MODEL)),
            name=session_name or UNNAMED_SESSION_SENTINEL,
            memory_auto_extract=bool(getattr(args, "elephant_mode", False)),
            max_turns=getattr(args, "turns", None),
            research_mode=bool(getattr(args, "research", False)),
            research_source_mode=getattr(args, "research_source_mode", None),
            research_local_corpus_paths=getattr(args, "local_corpus", None),
        )
        set_shell_session_id(int(session_id))
        return int(session_id), False

    if getattr(args, "resume_session", None):
        selector = " ".join(str(t) for t in args.resume_session).strip()
        if selector:
            parsed_session_id = parse_session_selector_token(selector)
            if parsed_session_id is not None:
                session = repo.get_session_by_id(int(parsed_session_id))
                if session:
                    set_shell_session_id(int(session.id))
                    return int(session.id), False
            session_by_name = repo.get_session_by_name(selector)
            if session_by_name:
                set_shell_session_id(int(session_by_name.id))
                return int(session_by_name.id), False

    shell_session_id = get_shell_session_id()
    if shell_session_id and repo.get_session_by_id(int(shell_session_id)):
        return int(shell_session_id), False

    timestamped_name = f"{UNNAMED_SESSION_SENTINEL}_{int(time.time())}"
    session_id = repo.create_session(
        model=str(getattr(args, "model", DEFAULT_MODEL)),
        name=timestamped_name,
        memory_auto_extract=bool(getattr(args, "elephant_mode", False)),
        max_turns=getattr(args, "turns", None),
        research_mode=bool(getattr(args, "research", False)),
        research_source_mode=getattr(args, "research_source_mode", None),
        research_local_corpus_paths=getattr(args, "local_corpus", None),
    )
    set_shell_session_id(int(session_id))
    return int(session_id), True


def main() -> None:
    """Main entry point."""
    # Solution 1: Check for "persona" subcommand before parse_args()
    # This maintains clean UX without breaking existing functionality
    if len(sys.argv) > 1 and sys.argv[1] == "persona":
        from asky.cli import persona_commands
        
        # Parse persona subcommands separately
        parser = argparse.ArgumentParser(description="Persona management commands")
        subparsers = parser.add_subparsers(dest='persona_command', required=True)
        
        create_parser = subparsers.add_parser('create', help='Create a new persona')
        create_parser.add_argument('name', help='Persona name')
        create_parser.add_argument('--prompt', required=True, help='Path to behavior prompt file')
        create_parser.add_argument('--description', default='', help='Persona description')
        
        add_sources_parser = subparsers.add_parser('add-sources', help='Add knowledge sources to a persona')
        add_sources_parser.add_argument('name', help='Persona name')
        add_sources_parser.add_argument('sources', nargs='+', help='Source URLs or paths')
        
        import_parser = subparsers.add_parser('import', help='Import a persona package')
        import_parser.add_argument('path', help='Path to persona ZIP file')
        
        export_parser = subparsers.add_parser('export', help='Export a persona package')
        export_parser.add_argument('name', help='Persona name')
        export_parser.add_argument('--output', help='Output path for exported ZIP file')
        
        load_parser = subparsers.add_parser('load', help='Load a persona into the current session')
        load_parser.add_argument('name', help='Persona name or alias')
        
        unload_parser = subparsers.add_parser('unload', help='Unload the current persona')
        
        current_parser = subparsers.add_parser('current', help='Show the currently loaded persona')
        
        list_parser = subparsers.add_parser('list', help='List all available personas')
        
        alias_parser = subparsers.add_parser('alias', help='Create a persona alias')
        alias_parser.add_argument('alias', help='Alias name')
        alias_parser.add_argument('persona_name', help='Target persona name')
        
        unalias_parser = subparsers.add_parser('unalias', help='Remove a persona alias')
        unalias_parser.add_argument('alias', help='Alias to remove')
        
        aliases_parser = subparsers.add_parser('aliases', help='List persona aliases')
        aliases_parser.add_argument('persona_name', nargs='?', help='Show aliases for specific persona')
        
        # Parse persona args (skip "persona" token)
        persona_args = parser.parse_args(sys.argv[2:])
        
        # Dispatch to appropriate handler
        persona_cmd = persona_args.persona_command
        if persona_cmd == 'create':
            persona_commands.handle_persona_create(persona_args)
        elif persona_cmd == 'add-sources':
            persona_commands.handle_persona_add_sources(persona_args)
        elif persona_cmd == 'import':
            persona_commands.handle_persona_import(persona_args)
        elif persona_cmd == 'export':
            persona_commands.handle_persona_export(persona_args)
        elif persona_cmd == 'load':
            persona_commands.handle_persona_load(persona_args)
        elif persona_cmd == 'unload':
            persona_commands.handle_persona_unload(persona_args)
        elif persona_cmd == 'current':
            persona_commands.handle_persona_current(persona_args)
        elif persona_cmd == 'list':
            persona_commands.handle_persona_list(persona_args)
        elif persona_cmd == 'alias':
            persona_commands.handle_persona_alias(persona_args)
        elif persona_cmd == 'unalias':
            persona_commands.handle_persona_unalias(persona_args)
        elif persona_cmd == 'aliases':
            persona_commands.handle_persona_aliases(persona_args)
        return
    
    # Normal query parsing flow
    _cli_plugin_manager = _bootstrap_plugin_manager_for_cli()
    args = parse_args(plugin_manager=_cli_plugin_manager)
    raw_initial_query = " ".join(getattr(args, "query", []) or [])
    if raw_initial_query.startswith("\\"):
        from asky.cli.presets import expand_preset_invocation, list_presets_text

        preset_expansion = expand_preset_invocation(raw_initial_query)
        if preset_expansion.matched:
            if preset_expansion.command_text == "\\presets":
                print(list_presets_text())
                return
            if preset_expansion.error:
                print(f"Error: {preset_expansion.error}")
                return
            expanded_tokens = list(preset_expansion.command_tokens or [])
            if not expanded_tokens:
                print("Error: Preset expansion produced an empty command.")
                return
            args = parse_args(expanded_tokens, plugin_manager=_cli_plugin_manager)

    _apply_shell_session_defaults(args)

    manual_corpus_query = _manual_corpus_query_arg(args)
    manual_section_query = _manual_section_query_arg(args)

    # Resolve research flag and local corpus paths
    try:
        # Use getattr to safely handle partially-mocked args in legacy tests
        research_arg = getattr(args, "research", False)
        (
            research_enabled,
            corpus_paths,
            leftover,
            source_mode,
            replace_corpus,
        ) = _resolve_research_corpus(research_arg)
        args.research = research_enabled
        args.local_corpus = corpus_paths
        args.research_flag_provided = (
            research_arg is not False and research_arg is not None
        )
        args.research_source_mode = source_mode
        args.replace_research_corpus = replace_corpus
        if leftover:
            # Re-insert the token into query list if argparse consumed it but it wasn't a pointer
            if not getattr(args, "query", None):
                args.query = [leftover]
            else:
                args.query.insert(0, leftover)
    except ValueError as e:
        print(f"Error: {e}")
        return

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

    # Resolve continue sentinel
    if getattr(args, "continue_ids", None) == "__last__":
        args.continue_ids = "~1"

    # Guard: if continue_ids was given a plaintext value instead of a valid selector
    # (e.g. `asky -c Tell me more` gives continue_ids="Tell"), recover gracefully.
    # A valid value is a digit, a ~N relative selector, or a __hid_N token.
    _cids = getattr(args, "continue_ids", None)
    if _cids and not re.match(r"^(\d+|~\d+|__hid_\d+)(,(\d+|~\d+|__hid_\d+))*$", _cids):
        args.query = [_cids] + (args.query or [])
        args.continue_ids = "~1"

    # Automatically convert history-continuation to a session if no session is active.
    # This makes the continuation part of a resumable conversation.
    if getattr(args, "continue_ids", None) and not any(
        [
            getattr(args, "sticky_session", None),
            getattr(args, "resume_session", None),
            getattr(args, "session_from_message", None),
            get_shell_session_id(),
        ]
    ):
        init_db()
        repo = SQLiteHistoryRepository()
        try:
            from asky.api.context import load_context_from_history
            from asky.storage import get_history, get_interaction_context

            # Resolve the selector (direct ID or ~N) to actual interaction IDs
            res = load_context_from_history(
                args.continue_ids,
                summarize=False,
                get_history_fn=get_history,
                get_interaction_context_fn=get_interaction_context,
            )
            if res.resolved_ids:
                # Pick the most recent ID as the pivot for session conversion
                target_id = max(res.resolved_ids)
                new_sid = repo.convert_history_to_session(target_id)
                args.resume_session = [str(new_sid)]
                # Note: args.continue_ids is PRESERVED so AskyClient.run_turn still
                # uses it for context injection if needed (though session resumption
                # will also bring in the converted messages).
        except Exception as e:
            logging.getLogger(__name__).debug(
                f"Failed to auto-convert continue to session: {e}"
            )

    # Configure logging based on verbose flag
    if args.verbose:
        # Verbose: Timestamped file, DEBUG level
        session_log_file = generate_timestamped_log_path(LOG_FILE)
        setup_logging("DEBUG", session_log_file)
        logging.debug("Verbose mode enabled. Log level set to DEBUG.")
    else:
        # Default: Standard file, Configured level
        setup_logging(LOG_LEVEL, LOG_FILE)

    if args.completion_script:
        from asky.cli.completion import build_completion_script

        print(build_completion_script(args.completion_script))
        return

    if getattr(args, "edit_daemon", False) is True:
        logger.info("dispatching interactive daemon editor")
        from asky.cli.daemon_config import edit_daemon_command

        edit_daemon_command()
        return

    if getattr(args, "xmpp_menubar_child", False) is True:
        from asky.daemon.errors import DaemonUserError
        from asky.daemon.launch_context import LaunchContext, set_launch_context

        set_launch_context(LaunchContext.MACOS_APP)
        logger.info("dispatching xmpp menubar child mode")
        from asky.daemon.menubar import run_menubar_app

        try:
            run_menubar_app()
        except DaemonUserError as exc:
            logger.error("menubar child failed: %s", exc.user_message)
            print(f"Error: {exc.user_message}")
            raise SystemExit(1)
        except Exception as exc:
            logger.exception("menubar child crashed")
            print(f"Error: menubar daemon failed to start: {exc}")
            raise SystemExit(1)
        return

    if getattr(args, "xmpp_daemon", False) is True:
        from asky.daemon.errors import DaemonUserError

        logger.info("dispatching xmpp daemon mode")
        is_macos = platform.system().lower() == "darwin"
        logger.debug("xmpp daemon platform gate is_macos=%s", is_macos)
        if is_macos:
            try:
                from asky.daemon.menubar import (
                    MENUBAR_ALREADY_RUNNING_MESSAGE,
                    has_rumps,
                    is_menubar_instance_running,
                    run_menubar_app,
                )

                # In double-verbose mode, skip menubar and stay in foreground
                if has_rumps() and not getattr(args, "double_verbose", False):
                    logger.info("rumps detected; using menubar bootstrap flow")

                    # Auto-create the .app bundle so users can launch from Spotlight
                    try:
                        _slixmpp_available = True
                        import slixmpp  # noqa: F401
                    except ImportError:
                        _slixmpp_available = False

                    if _slixmpp_available:
                        try:
                            from asky.daemon.app_bundle_macos import (
                                ensure_bundle_exists,
                            )

                            ensure_bundle_exists()
                        except Exception:
                            logger.debug("app bundle creation skipped", exc_info=True)

                    if is_menubar_instance_running():
                        logger.warning(
                            "menubar daemon launch rejected: already running"
                        )
                        print(f"Error: {MENUBAR_ALREADY_RUNNING_MESSAGE}")
                        raise SystemExit(1)
                    if getattr(args, "xmpp_menubar_child", False):
                        logger.info("running menubar app inline (child invocation)")
                        run_menubar_app()
                    else:
                        log_path = Path(MENUBAR_BOOTSTRAP_LOG_FILE).expanduser()
                        log_path.parent.mkdir(parents=True, exist_ok=True)
                        log_file = log_path.open("a")
                        command = [
                            sys.executable,
                            "-m",
                            "asky",
                            "--xmpp-daemon",
                            "--xmpp-menubar-child",
                        ]
                        if getattr(args, "double_verbose", False):
                            command.append("-vv")
                        elif getattr(args, "verbose", False):
                            command.append("-v")

                        logger.debug(
                            "spawning menubar child command=%s log_path=%s",
                            command,
                            log_path,
                        )
                        subprocess.Popen(
                            command,
                            stdout=log_file,
                            stderr=log_file,
                            start_new_session=True,
                        )
                        logger.info("xmpp menubar child spawned")
                    return
            except Exception:
                # Fallback to foreground daemon mode when menubar flow cannot start.
                logger.exception(
                    "menubar bootstrap failed; falling back to foreground daemon"
                )
        logger.info("running foreground xmpp daemon fallback")
        from asky.daemon.launch_context import LaunchContext, set_launch_context
        from asky.daemon.service import run_daemon_foreground
        from asky.plugins.runtime import get_or_create_plugin_runtime

        set_launch_context(LaunchContext.DAEMON_FOREGROUND)
        try:
            plugin_runtime = get_or_create_plugin_runtime()
            run_daemon_foreground(
                double_verbose=bool(getattr(args, "double_verbose", False)),
                plugin_runtime=plugin_runtime,
            )
        except DaemonUserError as exc:
            logger.error("foreground daemon failed: %s", exc.user_message)
            print(f"Error: {exc.user_message}")
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
            bool(manual_corpus_query),
            manual_section_query is not None,
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
        )
        return
    if args.print_ids:
        if not _recover_history_show_as_query(args):
            history.print_answers_command(
                args.print_ids,
                args.summarize,
                open_browser=args.open,
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
    if manual_corpus_query:
        research_commands.run_manual_corpus_query_command(
            query=manual_corpus_query,
            explicit_targets=getattr(args, "local_corpus", None),
            max_sources=int(
                getattr(
                    args,
                    "query_corpus_max_sources",
                    DEFAULT_MANUAL_QUERY_MAX_SOURCES,
                )
            ),
            max_chunks=int(
                getattr(
                    args,
                    "query_corpus_max_chunks",
                    DEFAULT_MANUAL_QUERY_MAX_CHUNKS,
                )
            ),
        )
        return
    if manual_section_query is not None:
        section_commands.run_summarize_section_command(
            section_query=manual_section_query or None,
            section_source=getattr(args, "section_source", None),
            section_id=getattr(args, "section_id", None),
            section_include_toc=bool(getattr(args, "section_include_toc", False)),
            section_detail=str(getattr(args, "section_detail", DEFAULT_SECTION_DETAIL)),
            section_max_chunks=getattr(args, "section_max_chunks", None),
            explicit_targets=getattr(args, "local_corpus", None),
        )
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

    if _needs_defaults_only_session(args):
        session_id, created_unnamed = _ensure_defaults_session(args)
        _persist_session_defaults(
            session_id=session_id,
            args=args,
            mark_pending_auto_name=created_unnamed,
        )
        print(f"Session {session_id} updated with query defaults.")
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
            getattr(args, "playwright_login", None),
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
    from asky.plugins.runtime import get_or_create_plugin_runtime

    plugin_runtime = get_or_create_plugin_runtime()

    if getattr(args, "playwright_login", None) and isinstance(args.playwright_login, str):
        url = args.playwright_login
        plugin = plugin_runtime.manager.get_plugin("playwright_browser") if plugin_runtime else None
        if plugin and hasattr(plugin, "run_login_session"):
            plugin.run_login_session(url)
        else:
            status_list = plugin_runtime.manager.list_status() if plugin_runtime else []
            pw_status = next((s for s in status_list if s.name == "playwright_browser"), None)
            if pw_status and not pw_status.active:
                print(
                    f"playwright_browser plugin is not active (state: {pw_status.state}).",
                    file=sys.stderr,
                )
            else:
                print("playwright_browser plugin is not enabled.", file=sys.stderr)
            sys.exit(1)
        return

    chat.run_chat(args, query_text, plugin_runtime=plugin_runtime)


if __name__ == "__main__":
    main()
