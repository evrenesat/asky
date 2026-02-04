"""Display utilities for the CLI - banner and interface rendering."""

from typing import Dict, List, Optional, Any

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel

from asky.banner import get_banner, BannerState
from asky.config import (
    DEFAULT_CONTEXT_SIZE,
    MAX_TURNS,
    MODELS,
    SUMMARIZATION_MODEL,
)
from asky.storage import get_db_record_count


class InterfaceRenderer:
    """Handles rendering of the CLI interface with in-place banner updates using rich.Live."""

    def __init__(
        self,
        model_config: Dict[str, Any],
        model_alias: str,
        usage_tracker: Any,
        summarization_tracker: Optional[Any] = None,
        session_manager: Optional[Any] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
    ):
        self.model_config = model_config
        self.model_alias = model_alias
        self.usage_tracker = usage_tracker
        self.summarization_tracker = summarization_tracker
        self.session_manager = session_manager
        self.messages = messages or []
        self.console = Console()
        self.live: Optional[Live] = None

    def start_live(self) -> None:
        """Start the Live context for in-place banner updates."""
        initial_banner = self._build_banner(current_turn=0)
        self.live = Live(
            initial_banner,
            console=self.console,
            refresh_per_second=4,
            transient=False,  # Keep the final banner visible after stopping
        )
        self.live.start()

    def update_banner(
        self, current_turn: int, status_message: Optional[str] = None
    ) -> None:
        """Update the banner in-place without screen clearing."""
        if self.live:
            banner = self._build_banner(current_turn, status_message)
            self.live.update(banner)

    def stop_live(self) -> None:
        """Stop the Live context (call before printing final output)."""
        if self.live:
            self.live.stop()
            self.live = None

    def print_final_answer(self, answer: str) -> None:
        """Print the final answer normally (after stopping Live)."""
        if answer:
            self.console.print(f"\n[bold blue]Assistant[/]:")
            self.console.print(Markdown(answer))

    def _get_combined_token_usage(self) -> Dict[str, Dict[str, int]]:
        """Combine token usage from main and summarization trackers."""
        combined = dict(self.usage_tracker.usage)
        if self.summarization_tracker:
            for alias, usage in self.summarization_tracker.usage.items():
                if alias in combined:
                    combined[alias]["input"] += usage["input"]
                    combined[alias]["output"] += usage["output"]
                else:
                    combined[alias] = dict(usage)
        return combined

    def _build_banner(
        self, current_turn: int, status_message: Optional[str] = None
    ) -> Panel:
        """Build and return the banner Panel (for use with Live)."""
        model_id = self.model_config["id"]

        sum_alias = SUMMARIZATION_MODEL
        sum_id = MODELS[sum_alias]["id"]

        model_ctx = self.model_config.get("context_size", DEFAULT_CONTEXT_SIZE)
        sum_ctx = MODELS[sum_alias].get("context_size", DEFAULT_CONTEXT_SIZE)

        db_count = get_db_record_count()

        # Session info
        s_name = None
        s_msg_count = 0
        total_sessions = 0

        if self.session_manager and self.session_manager.current_session:
            s_name = self.session_manager.current_session.name
            s_msg_count = len(
                self.session_manager.repo.get_session_messages(
                    self.session_manager.current_session.id
                )
            )
            total_sessions = self.session_manager.repo.count_sessions()

        state = BannerState(
            model_alias=self.model_alias,
            model_id=model_id,
            sum_alias=sum_alias,
            sum_id=sum_id,
            model_ctx=model_ctx,
            sum_ctx=sum_ctx,
            max_turns=MAX_TURNS,
            current_turn=current_turn,
            db_count=db_count,
            session_name=s_name,
            session_msg_count=s_msg_count,
            total_sessions=total_sessions,
            token_usage=self._get_combined_token_usage(),
            tool_usage=self.usage_tracker.get_tool_usage(),
            status_message=status_message,
        )

        return get_banner(state)
