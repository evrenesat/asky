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
    token_usage: Dict[str, Dict[str, int]] = field(default_factory=dict)
    tool_usage: Dict[str, int] = field(default_factory=dict)

    def get_token_str(self, alias: str) -> str:
        usage = self.token_usage.get(alias, {"input": 0, "output": 0})
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


# def mini():
#     """Mini version"""
#     display(
#         [
#             f"[{D}] ╭[{G}]∩[/{G}]─────[{G}]∩[/{G}]╮[/{D}] [{M1}]a[/{M1}]",
#             f"[{D}] │[/{D}] [{G}]▷[/{G}] [{D}][{N}]ω[/{N}][/{D}] [{G}]_[/{G}] [{D}]│[/{D}] [{M2}]s[/{M2}]",
#             f"[{D}] │[/{D}] [{P}]◠[/{P}]   [{P}]◠[/{P}] [{D}]│[/{D}] [{M3}]k[/{M3}]",
#             f"[{D}] ╰───────╯[/{D}] [{M4}]y[/{M4}]",
#         ]
#     )


def get_banner(state: BannerState) -> Panel:
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
        f"[white]{state.sum_alias}[/] ([dim]{state.sum_id}[/]) ({state.sum_ctx // 1000}k) {state.get_token_str(state.sum_alias)}",
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

    # 4. Session Info
    session_details_parts = [
        f"Messages: {state.session_msg_count}",
        f"Sessions: {state.total_sessions}",
    ]

    if state.session_name:
        sess_name = state.session_name
        # Truncate long session names
        if len(sess_name) > 30:
            sess_name = sess_name[:27] + "..."
        session_details_parts.append(f'Current: "{sess_name}"')

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
