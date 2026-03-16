"""Help catalog for CLI discoverability.

Provides structured help content and rendering functions for:
- Top-level curated short help
- Grouped command help pages
- Secondary help entrypoints
- Discoverability contract definitions
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from asky.plugins.base import CapabilityCategory, CLIContribution


@dataclass(frozen=True)
class HelpItem:
    """A single help line or entry."""

    name: str
    description: str
    flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class HelpSection:
    """A section of grouped help content."""

    title: str
    items: tuple[HelpItem, ...]
    description: str = ""


@dataclass(frozen=True)
class HelpPage:
    """A complete help page with sections."""

    title: str
    sections: tuple[HelpSection, ...]
    description: str = ""


def format_help_item(item: HelpItem, indent: int = 2) -> str:
    """Format a help item as a single line."""
    flags_str = " ".join(item.flags)
    if flags_str:
        flags_str += " "
    return f"{' ' * indent}{flags_str}{item.name}"


def format_help_section(section: HelpSection) -> list[str]:
    """Format a help section as multiple lines."""
    lines: list[str] = []
    if section.title:
        lines.append(f"{section.title}:")
    for item in section.items:
        line = format_help_item(item)
        if item.description:
            if item.flags:
                line = f"  {line}"
            lines.append(f"{line}")
            lines.append(f"      {item.description}")
        else:
            lines.append(line)
    return lines


def format_help_page(page: HelpPage) -> str:
    """Format a complete help page."""
    lines: list[str] = []
    if page.title:
        lines.append(page.title)
    if page.description:
        lines.append(page.description)
    lines.append("")
    for section in page.sections:
        lines.extend(format_help_section(section))
        lines.append("")
    return "\n".join(lines).strip()


# Top-level curated help content
TOP_LEVEL_GROUPED_COMMANDS = (
    HelpItem("history list [count]", "List recent history entries."),
    HelpItem("history show <id_selector>", "Show full answer(s) for selected history item(s)."),
    HelpItem("history delete <id_selector|--all>", "Delete history entries."),
    HelpItem("session list [count]", "List recent sessions."),
    HelpItem("session show <session_selector>", "Print session transcript."),
    HelpItem("session create <name>", "Create and activate a named session."),
    HelpItem("session use <session_selector>", "Resume a session by id/name."),
    HelpItem("session end", "End active shell-bound session."),
    HelpItem("session delete <session_selector|--all>", "Delete sessions, messages, and associated research data."),
    HelpItem("session clean-research <session_selector>", "Remove session research findings/vectors and session corpus links/paths."),
    HelpItem("session from-message <history_id|last>", "Convert history message into a session."),
    HelpItem("memory list", "List user memories."),
    HelpItem("memory delete <id>", "Delete one memory."),
    HelpItem("memory clear", "Delete all memories."),
    HelpItem("corpus query <text>", "Deterministic corpus query (no main model call)."),
    HelpItem("corpus summarize [query]", "Deterministic section summary flow."),
    HelpItem("prompts list", "List configured user prompts."),
)

TOP_LEVEL_CONFIG_COMMANDS = (
    HelpItem("--config model add", ""),
    HelpItem("--config model edit [alias]", ""),
    HelpItem("--config daemon edit", ""),
)

TOP_LEVEL_CONVERSATION_MEMORY_SECTION = "Conversation & Memory"

TOP_LEVEL_CONVERSATION_MEMORY_ITEMS = (
    HelpItem("-c, --continue-chat [HISTORY_IDS]", "Continue conversation from specific history IDs (comma-separated). Omit value to continue from the last message.", ("-c", "--continue-chat")),
    HelpItem("--reply", "Resume the last conversation (converting history to session if needed).", ("--reply",)),
    HelpItem("-em, --elephant-mode", "Enable automatic memory extraction for this session.", ("-em", "--elephant-mode")),
)

TOP_LEVEL_QUERY_OPTIONS = (
    HelpItem("-m, --model ALIAS", "Select model alias for this run.", ("-m", "--model")),
    HelpItem("-r, --research [CORPUS_POINTER]", "Enable deep research mode; optionally bind local/web corpus source(s).", ("-r", "--research")),
    HelpItem("-s, --summarize", "Summarize URL content before main answer generation.", ("-s", "--summarize")),
    HelpItem("-L, --lean", "Lean mode: disable all tool calls, skip shortlist/memory recall preload, and skip memory extraction/context compaction side effects.", ("-L", "--lean")),
    HelpItem("-t, --turns MAX_TURNS", "Set per-session max turns.", ("-t", "--turns")),
    HelpItem("-sp, --system-prompt TEXT", "Override system prompt.", ("-sp", "--system-prompt")),
    HelpItem("-tl, --terminal-lines [LINE_COUNT]", "Include recent terminal context in query.", ("-tl", "--terminal-lines")),
    HelpItem("--shortlist {on,off,reset}", "Persist shortlist preference to current session (or clear with reset).", ("--shortlist",)),
    HelpItem("--tools [off [a,b,c]|reset]", "List tools, disable all/some tools, or clear tool override.", ("--tools",)),
    HelpItem("--session <query...>", "Create a new session named from query text and run the query.", ("--session",)),
    HelpItem("-v, --verbose", "Verbose output (-vv for double-verbose).", ("-v", "--verbose")),
)

TOP_LEVEL_PROCESS_OPTIONS = (
    HelpItem("--completion-script {bash,zsh}", ""),
)

TOP_LEVEL_MORE_HELP_ITEMS = (
    HelpItem("asky --help-all", ""),
    HelpItem("asky persona --help", ""),
    HelpItem("asky corpus --help", ""),
    HelpItem("asky corpus query --help", ""),
    HelpItem("asky corpus summarize --help", ""),
    HelpItem("asky history --help", ""),
    HelpItem("asky session --help", ""),
    HelpItem("asky memory --help", ""),
)


def render_top_level_help(plugin_manager=None) -> str:
    """Render top-level curated help."""
    from asky.plugins.base import CapabilityCategory, CATEGORY_LABELS

    lines = [
        "usage: asky [query ...]",
        "       asky --config <domain> <action>",
        "       asky <group> <action> [args]",
        "",
        "Tool-calling CLI with grouped operational commands.",
        "",
        "Grouped commands:",
    ]

    for item in TOP_LEVEL_GROUPED_COMMANDS:
        lines.append(f"  {item.name}")

    lines.extend([
        "",
        "Configuration:",
    ])
    for item in TOP_LEVEL_CONFIG_COMMANDS:
        lines.append(f"  {item.name}")

    lines.extend([
        "",
        TOP_LEVEL_CONVERSATION_MEMORY_SECTION + ":",
    ])
    for item in TOP_LEVEL_CONVERSATION_MEMORY_ITEMS:
        if item.flags:
            flags_str = ", ".join(item.flags)
            lines.append(f"  {flags_str}")
            lines.append(f"      {item.description}")
        else:
            lines.append(f"  {item.name}")
            lines.append(f"      {item.description}")

    lines.extend([
        "",
        "Query options:",
    ])
    for item in TOP_LEVEL_QUERY_OPTIONS:
        if item.flags:
            flags_str = ", ".join(item.flags)
            lines.append(f"  {flags_str}")
            lines.append(f"      {item.description}")
        else:
            lines.append(f"  {item.name}")
            lines.append(f"      {item.description}")

    # Collect plugin contributions grouped by category
    contributions_by_category: dict[str, list[CLIContribution]] = {}
    if plugin_manager is not None:
        for _, contrib in plugin_manager.collect_cli_contributions():
            contributions_by_category.setdefault(contrib.category, []).append(contrib)

    # Output Delivery: core --open is always present; plugins may add more
    output_title, _ = CATEGORY_LABELS[CapabilityCategory.OUTPUT_DELIVERY]
    lines.extend([
        "",
        f"{output_title}:",
        "  -o, --open",
        "      Open final answer in browser.",
        "  -cc, --copy-clipboard",
        "      Copy final answer to system clipboard.",
    ])

    for contrib in contributions_by_category.get(CapabilityCategory.OUTPUT_DELIVERY, []):
        flags_str = ", ".join(contrib.flags)
        if flags_str:
            lines.append(f"  {flags_str}")
        if contrib.kwargs.get("help"):
            lines.append(f"      {contrib.kwargs['help']}")

    # Other categories appear only when a plugin contributes to them
    for category in (
        CapabilityCategory.BROWSER_SETUP,
        CapabilityCategory.BACKGROUND_SERVICE,
        CapabilityCategory.SESSION_CONTROL,
    ):
        contribs = contributions_by_category.get(category, [])
        if contribs or category == CapabilityCategory.BACKGROUND_SERVICE:
            cat_title, _ = CATEGORY_LABELS[category]
            lines.extend(["", f"{cat_title}:"])
            for contrib in contribs:
                flags_str = ", ".join(contrib.flags)
                if flags_str:
                    lines.append(f"  {flags_str}")
                if contrib.kwargs.get("help"):
                    lines.append(f"      {contrib.kwargs['help']}")
            if category == CapabilityCategory.BACKGROUND_SERVICE:
                lines.append("  --foreground")
                lines.append("      Keep the daemon attached to the terminal instead of backgrounding.")
                lines.append("  --no-tray")
                lines.append("      Bypass the tray/menubar when starting the background daemon.")

    lines.extend([
        "",
        "Process options:",
    ])
    for item in TOP_LEVEL_PROCESS_OPTIONS:
        lines.append(f"  {item.name}")

    lines.extend([
        "",
        "More help:",
    ])
    for item in TOP_LEVEL_MORE_HELP_ITEMS:
        lines.append(f"  {item.name}")

    return "\n".join(lines)


# Grouped command help pages
GROUPED_HISTORY_ITEMS = (
    HelpItem("asky history list [count]", ""),
    HelpItem("asky history show <id_selector>", ""),
    HelpItem("asky history delete <id_selector|--all>", ""),
)

GROUPED_SESSION_ITEMS = (
    HelpItem("asky session list [count]", ""),
    HelpItem("asky session show <session_selector>", ""),
    HelpItem("asky session create <name>", ""),
    HelpItem("asky session use <session_selector>", ""),
    HelpItem("asky session end", ""),
    HelpItem("asky session clean-research <session_selector>", ""),
    HelpItem("asky session from-message <history_id|last>", ""),
    HelpItem("asky session delete <session_selector|--all>", "'session delete' also performs implicit research cleanup for the deleted sessions."),
)

GROUPED_MEMORY_ITEMS = (
    HelpItem("asky memory list", ""),
    HelpItem("asky memory delete <id>", ""),
    HelpItem("asky memory clear", ""),
)

GROUPED_CORPUS_ITEMS = (
    HelpItem("asky corpus query <text>", ""),
    HelpItem("asky corpus summarize [query]", ""),
)

GROUPED_PROMPTS_ITEMS = (
    HelpItem("asky prompts list", ""),
)


def render_history_help() -> str:
    """Render grouped help for history operations."""
    lines = [
        "usage: asky history <list|show|delete> [args]",
        "",
        "Commands:",
    ]
    for item in GROUPED_HISTORY_ITEMS:
        lines.append(f"  {item.name}")
    return "\n".join(lines)


def render_session_help() -> str:
    """Render grouped help for session operations."""
    lines = [
        "usage: asky session <action> [args]",
        "",
        "Commands:",
    ]
    for item in GROUPED_SESSION_ITEMS:
        lines.append(f"  {item.name}")
        if item.description:
            lines.append(f"  {item.description}")
    return "\n".join(lines)


def render_memory_help() -> str:
    """Render grouped help for memory operations."""
    lines = [
        "usage: asky memory <list|delete|clear> [args]",
        "",
        "Commands:",
    ]
    for item in GROUPED_MEMORY_ITEMS:
        lines.append(f"  {item.name}")
    return "\n".join(lines)


def render_corpus_help() -> str:
    """Render grouped help for corpus operations."""
    lines = [
        "usage: asky corpus <query|summarize> ...",
        "",
        "Corpus commands:",
        "  asky corpus query <text>",
        "  asky corpus summarize [query]",
        "",
        "Run:",
        "  asky corpus query --help",
        "  asky corpus summarize --help",
    ]
    return "\n".join(lines)


def render_corpus_query_help() -> str:
    """Render help for corpus query subcommand."""
    return """usage: asky corpus query <text> [options]

Deterministically query cached/ingested corpus without invoking the main model.

Options:
  --query-corpus-max-sources COUNT
      Maximum corpus sources to scan (default 20).
  --query-corpus-max-chunks COUNT
      Maximum chunks per source (default 3).
  --section-include-toc
      Include TOC/micro heading rows in corpus section output."""


def render_corpus_summarize_help() -> str:
    """Render help for corpus summarize subcommand."""
    return """usage: asky corpus summarize [query] [options]

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


def render_prompts_help() -> str:
    """Render grouped help for prompts operations."""
    lines = [
        "usage: asky prompts list",
        "",
        "Commands:",
        "  asky prompts list",
    ]
    return "\n".join(lines)


# Discoverability contract - items that must appear in specific help surfaces
# These are validated by tests in test_help_discoverability.py

# Top-level short help must include these
TOP_LEVEL_SHORT_HELP_REQUIRED = {
    "asky persona --help",
    "--continue-chat",
    "--reply",
    "--elephant-mode",
    "session delete",
}

# Session grouped help must include these
SESSION_GROUPED_HELP_REQUIRED = {
    "session delete",
}
