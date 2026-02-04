"""Display utilities for the CLI - banner and interface rendering."""

from typing import Dict, List, Optional, Any

from rich.console import Console
from rich.markdown import Markdown

from asky.banner import get_banner, BannerState
from asky.config import (
    DEFAULT_CONTEXT_SIZE,
    MAX_TURNS,
    MODELS,
    SUMMARIZATION_MODEL,
)
from asky.storage import get_db_record_count


class InterfaceRenderer:
    """Handles rendering of the CLI interface including banner and conversation history."""

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

    def clear_screen(self):
        """Clear the terminal screen."""
        import os

        os.system("cls" if os.name == "nt" else "clear")

    def render(self, current_turn: int, status_message: Optional[str] = None) -> None:
        """Render the full interface: clear screen, show banner, show conversation."""
        self.clear_screen()
        self._render_banner(current_turn, status_message)
        self._render_conversation()

    def render_banner_only(
        self, current_turn: int, status_message: Optional[str] = None
    ) -> None:
        """Render just the banner without clearing screen or showing conversation."""
        self._render_banner(current_turn, status_message)

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

    def _render_banner(
        self, current_turn: int, status_message: Optional[str] = None
    ) -> None:
        """Build and print the banner."""
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

        banner = get_banner(state)
        self.console.print(banner)

    def _render_conversation(self) -> None:
        """Print conversation history (skipping system messages)."""
        for m in self.messages:
            role = m.get("role")
            content = m.get("content", "")

            if role == "system":
                continue

            if role == "user":
                self.console.print(f"\n[bold green]User[/]: {content}")
            elif role == "assistant":
                if content:
                    self.console.print(f"\n[bold blue]Assistant[/]:")
                    self.console.print(Markdown(content))
            # Tool outputs are shown in banner statistics, no need to print
