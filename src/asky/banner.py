#!/usr/bin/env python3
"""
Cute Terminal Icon - ASCII Art
"""

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


def display(lines):
    """Display lines with markup"""
    console = Console()
    console.print()
    for line in lines:
        console.print(Text.from_markup(line))
    console.print()


def mini():
    """Mini version"""
    display(
        [
            f"[{D}] ╭[{G}]∩[/{G}]─────[{G}]∩[/{G}]╮[/{D}] [{M1}]a[/{M1}]",
            f"[{D}] │[/{D}] [{G}]▷[/{G}] [{D}][{N}]ω[/{N}][/{D}] [{G}]_[/{G}] [{D}]│[/{D}] [{M2}]s[/{M2}]",
            f"[{D}] │[/{D}] [{P}]◠[/{P}]   [{P}]◠[/{P}] [{D}]│[/{D}] [{M3}]k[/{M3}]",
            f"[{D}] ╰───────╯[/{D}] [{M4}]y[/{M4}]",
        ]
    )


def get_banner(
    model_alias: str,
    model_id: str,
    sum_alias: str,
    sum_id: str,
    default_model: str,
    search_provider: str,
    model_ctx: int,
    sum_ctx: int,
    max_turns: int,
    db_count: int,
) -> Panel:
    """Create a side-by-side banner with an icon and configuration info in two columns."""
    icon_lines = [
        f"[{D}] ╭[{G}]∩[/{G}]─────[{G}]∩[/{G}]╮[/{D}] [{M1}]a[/{M1}]",
        f"[{D}] │[/{D}] [{G}]▷[/{G}] [{D}][{N}]ω[/{N}][/{D}] [{G}]_[/{G}] [{D}]│[/{D}] [{M2}]s[/{M2}]",
        f"[{D}] │[/{D}] [{P}]◠[/{P}]   [{P}]◠[/{P}] [{D}]│[/{D}] [{M3}]k[/{M3}]",
        f"[{D}] ╰───────╯[/{D}] [{M4}]y[/{M4}]",
    ]
    icon_text = Text.from_markup("\n".join(icon_lines))

    # --- Configuration Columns ---
    col1 = Table.grid(padding=(0, 1))
    col1.add_column(justify="left", style="bold cyan")
    col1.add_column(justify="left")
    col1.add_row(
        " Main Model :", f" [white]{model_alias}[/white] ([dim]{model_id}[/dim])"
    )
    col1.add_row(" Summarizer :", f" [white]{sum_alias}[/white] ([dim]{sum_id}[/dim])")
    col1.add_row(" Default    :", f" [white]{default_model}[/white]")

    col2 = Table.grid(padding=(0, 1))
    col2.add_column(justify="left", style="bold cyan")
    col2.add_column(justify="left")
    col2.add_row(" Search     :", f" [white]{search_provider}[/white]")
    col2.add_row(
        " Context    :",
        f" [white]{model_ctx:,}[/white]/[white]{sum_ctx:,}[/white] [dim]tokens[/dim]",
    )
    col2.add_row(
        " System     :",
        f" [white]{max_turns}[/white] [dim]turns[/dim] | [white]{db_count}[/white] [dim]records[/dim]",
    )

    info_layout = Table.grid(padding=(0, 3))
    info_layout.add_column()
    info_layout.add_column()
    info_layout.add_row(col1, col2)

    # --- Main Layout ---
    layout_table = Table.grid(padding=(0, 2))
    layout_table.add_column()
    layout_table.add_column(ratio=1)
    layout_table.add_row(icon_text, info_layout)

    return Panel(layout_table, box=box.ROUNDED, border_style="dim", padding=(0, 1))


if __name__ == "__main__":
    mini()
    # Test get_banner
    console = Console()
    console.print(
        get_banner(
            "gf",
            "gemini-flash-latest",
            "lfm",
            "llama3",
            "gf",
            "searxng",
            1000000,
            4096,
            20,
            123,
        )
    )
