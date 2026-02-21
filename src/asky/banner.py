from dataclasses import dataclass, field
from typing import Dict, Optional

from rich.console import Console
from rich.text import Text
from rich.panel import Panel
from rich.table import Table
from rich import box

# Color shortcuts for templates
G = "bold #39ff14"  # neon green (eyes)
P = "#ff8fa3"  # pink (blush)
D = "dim"  # dim (border)
N = "#39ff14"  # nose (not bold = dimmer)

# Metallic shiny effect colors
M1 = "bold #ffffff"  # bright highlight
M2 = "bold #c0c0c0"  # silver
M3 = "#a0a0a0"  # medium gray
M4 = "#707070"  # shadow


@dataclass
class BannerState:
    """State object for the banner display."""

    # Model Config
    model_alias: str
    model_id: str
    sum_alias: str
    sum_id: str
    model_ctx: int
    sum_ctx: int
    max_turns: int

    # Session / Sys
    current_turn: int
    db_count: int
    session_name: Optional[str] = None
    session_msg_count: int = 0
    total_sessions: int = 0
    status_message: Optional[str] = None

    # Stats
    main_token_usage: Dict[str, Dict[str, int]] = field(default_factory=dict)
    sum_token_usage: Dict[str, Dict[str, int]] = field(default_factory=dict)
    tool_usage: Dict[str, int] = field(default_factory=dict)

    # Embedding (Research Mode)
    research_mode: bool = False
    embedding_model: Optional[str] = None
    embedding_texts: int = 0
    embedding_api_calls: int = 0
    embedding_prompt_tokens: int = 0

    # Compact Mode
    compact_banner: bool = False

    # Pre-LLM Shortlist
    shortlist_enabled: bool = False
    shortlist_collected: int = 0
    shortlist_processed: int = 0
    shortlist_selected: int = 0
    shortlist_warnings: int = 0
    shortlist_elapsed_ms: float = 0.0

    def get_token_str(self, alias: str, is_summary: bool = False) -> str:
        usage_dict = self.sum_token_usage if is_summary else self.main_token_usage
        usage = usage_dict.get(alias, {"input": 0, "output": 0})
        total = usage["input"] + usage["output"]
        # Escape brackets for Rich markup
        return f"\\[in: {usage['input']:,}, out: {usage['output']:,}, total: {total:,} tokens]"


def display(lines):
    """Display lines with markup"""
    console = Console()
    console.print()
    for line in lines:
        console.print(Text.from_markup(line))
    console.print()


def get_compact_banner(state: BannerState) -> Panel:
    """Create a compact two-line banner using emojis and minimal text."""
    grid = Table.grid(padding=(0, 2))
    grid.add_column(justify="left")

    # Line 1: Models & Tokens
    # 🤖 main_model (id) [in: X, out: Y] | 📝 sum_model [in: X, out: Y]

    main_usage = state.main_token_usage.get(
        state.model_alias, {"input": 0, "output": 0}
    )
    sum_usage = state.sum_token_usage.get(state.sum_alias, {"input": 0, "output": 0})

    line1_parts = []

    # Main Model
    line1_parts.append(
        f"🤖 [bold white]{state.model_alias}[/] [dim]({state.model_id})[/]"
        f" [dim]\\[⬇️ {main_usage['input']:,} ⬆️ {main_usage['output']:,}][/]"
    )

    # Summarizer
    line1_parts.append(
        f"📝 [bold white]{state.sum_alias}[/] [dim]({state.sum_id})[/]"
        f" [dim]\\[⬇️ {sum_usage['input']:,} ⬆️ {sum_usage['output']:,}][/]"
    )

    grid.add_row(" | ".join(line1_parts))

    # Line 2: Status, Session, Tools
    #  1/20 | 🧠 embed_stats | 💾 db_count | 🗂️ session_name | 🛠️ tools...

    line2_parts = []

    # Turns
    line2_parts.append(f"🔄 {state.current_turn}/{state.max_turns}")

    # Embedding (Research Mode)
    if state.research_mode:
        embed_stats = (
            f"🧠 {state.embedding_texts} txt / {state.embedding_api_calls} call"
        )
        if state.embedding_prompt_tokens > 0:
            embed_stats += f" / {state.embedding_prompt_tokens:,} tok"
        line2_parts.append(embed_stats)

    # DB Count
    line2_parts.append(f"💾 {state.db_count}")

    # Session
    if state.session_name:
        sess_name = state.session_name
        if len(sess_name) > 20:
            sess_name = sess_name[:17] + "..."
        line2_parts.append(f"🗂️  {sess_name} ({state.session_msg_count})")
    else:
        line2_parts.append(f"🗂️  {state.total_sessions}")

    # Tools
    if state.tool_usage:
        tools_str = " ".join([f"{k}:{v}" for k, v in state.tool_usage.items()])
        line2_parts.append(f"🛠️  {tools_str}")
    else:
        line2_parts.append("🛠️  0")

    if state.shortlist_enabled:
        shortlist_stats = (
            f"🔎 C:{state.shortlist_collected}"
            f" F:{state.shortlist_processed}"
            f" S:{state.shortlist_selected}"
        )
        if state.shortlist_warnings > 0:
            shortlist_stats += f" W:{state.shortlist_warnings}"
        line2_parts.append(shortlist_stats)

    grid.add_row(" | ".join(line2_parts))

    return Panel(
        grid,
        box=box.ROUNDED,
        border_style="dim",
        padding=(0, 1),
        subtitle=state.status_message,
        subtitle_align="right",
    )


def get_banner(state: BannerState) -> Panel:
    """Create the banner panel, dispatching to compact or full version."""
    if state.compact_banner:
        return get_compact_banner(state)

    """Create a side-by-side banner with an icon and configuration info using BannerState."""
    icon_lines = [
        f"[{D}] ╭[{G}]∩[/{G}]─────[{G}]∩[/{G}]╮[/{D}] [{M1}]a[/{M1}]",
        f"[{D}] │[/{D}] [{G}]>[/{G}] [{D}][{N}]ω[/{N}][/{D}] [{G}]_[/{G}] [{D}]│[/{D}] [{M2}]s[/{M2}]",
        f"[{D}] │[/{D}] [{P}]◠[/{P}]   [{P}]❞[/{P}] [{D}]│[/{D}] [{M3}]k[/{M3}]",
        f"[{D}] ╰───────╯[/{D}] [{M4}]y[/{M4}]",
    ]
    icon_text = Text.from_markup("\n".join(icon_lines))

    # --- Configuration Columns ---
    grid = Table.grid(padding=(0, 2))
    grid.add_column(justify="left")  # Label
    grid.add_column(justify="left")  # Value

    # 1. Main Model
    grid.add_row(
        "[bold cyan]Main Model :[/]",
        f"[white]{state.model_alias}[/] ([dim]{state.model_id}[/]) ({state.model_ctx // 1000}k) {state.get_token_str(state.model_alias)}",
    )

    # 2. Summarizer
    grid.add_row(
        "[bold cyan]Summarizer :[/]",
        f"[white]{state.sum_alias}[/] ([dim]{state.sum_id}[/]) ({state.sum_ctx // 1000}k) {state.get_token_str(state.sum_alias, is_summary=True)}",
    )

    # 3. Tools Status
    tools_str = (
        " | ".join([f"{k}: {v}" for k, v in state.tool_usage.items()])
        if state.tool_usage
        else "None"
    )
    grid.add_row(
        "[bold cyan]Tools      :[/]",
        f"{tools_str} | [bold]Turns:[/] {state.current_turn}/{state.max_turns}",
    )

    # 3.5 Embedding (only when research_mode is True)
    if state.research_mode:
        embedding_parts = [
            f"[white]{state.embedding_model}[/]",
            f"Texts: {state.embedding_texts}",
            f"API Calls: {state.embedding_api_calls}",
        ]
        if state.embedding_prompt_tokens > 0:
            embedding_parts.append(f"Tokens: {state.embedding_prompt_tokens:,}")
        embedding_str = " | ".join(embedding_parts)
        grid.add_row(
            "[bold cyan]Embedding  :[/]",
            embedding_str,
        )

    if state.shortlist_enabled:
        shortlist_parts = [
            f"Collected: {state.shortlist_collected}",
            f"Fetched: {state.shortlist_processed}",
            f"Selected: {state.shortlist_selected}",
            f"Elapsed: {state.shortlist_elapsed_ms:.0f}ms",
        ]
        if state.shortlist_warnings > 0:
            shortlist_parts.append(f"Warnings: {state.shortlist_warnings}")
        grid.add_row(
            "[bold cyan]Shortlist  :[/]",
            " | ".join(shortlist_parts),
        )

    # 4. Session Info
    session_details_parts = [
        f"Messages: {state.db_count}",
        f"Sessions: {state.total_sessions}",
    ]

    if state.session_name:
        sess_name = state.session_name
        # Truncate long session names
        if len(sess_name) > 30:
            sess_name = sess_name[:27] + "..."
        session_details_parts.append(
            f'Current: "{sess_name}" ({state.session_msg_count} msgs)'
        )

    session_details = " | ".join(session_details_parts)
    # Add session-wide token usage if available in the tracker for the current session alias?
    # For now, just show the context message count

    grid.add_row("[bold cyan]Session    :[/]", session_details)

    # --- Main Layout ---
    layout_table = Table.grid(padding=(0, 2))
    layout_table.add_column()
    layout_table.add_column(ratio=1)
    layout_table.add_row(icon_text, grid)

    return Panel(
        layout_table,
        box=box.ROUNDED,
        border_style="dim",
        padding=(0, 1),
        subtitle=state.status_message,
        subtitle_align="right",
    )
