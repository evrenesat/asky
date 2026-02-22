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
    COMPACT_BANNER,
)
from asky.storage import get_db_record_count, get_total_session_count


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
        research_mode: bool = False,
        max_turns: Optional[int] = None,
    ):
        self.model_config = model_config
        self.model_alias = model_alias
        self.usage_tracker = usage_tracker
        self.summarization_tracker = summarization_tracker
        self.session_manager = session_manager
        self.messages = messages or []
        self.research_mode = research_mode
        self.max_turns_override = max_turns
        self.console = Console()
        self.live: Optional[Live] = None
        self.shortlist_stats: Dict[str, Any] = {}
        self.current_turn: int = 0
        self.current_status_message: Optional[str] = None

    def __rich__(self) -> Panel:
        """Rich protocol to render the banner dynamically based on current tracking state."""
        return self._build_banner(self.current_turn, self.current_status_message)

    def start_live(self) -> None:
        """Start the Live context for in-place banner updates."""
        self.live = Live(
            self,  # Render self using __rich__ method
            console=self.console,
            refresh_per_second=4,
            transient=False,  # Keep the final banner visible after stopping
        )
        self.live.start()

    def update_banner(
        self, current_turn: int, status_message: Optional[str] = None
    ) -> None:
        """Update the banner in-place without screen clearing."""
        self.current_turn = current_turn
        self.current_status_message = status_message
        if self.live:
            self.live.refresh()

    def stop_live(self) -> None:
        """Stop the Live context (call before printing final output)."""
        if self.live:
            self.live.stop()
            self.live = None

    def set_shortlist_stats(self, stats: Optional[Dict[str, Any]]) -> None:
        """Store shortlist stats for banner rendering."""
        self.shortlist_stats = stats or {}

    def print_final_answer(self, answer: str) -> None:
        """Print the final answer normally (after stopping Live)."""
        if answer:
            self.console.print(f"\n[bold blue]Assistant[/]:")
            self.console.print(Markdown(answer))

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
        try:
            total_sessions = get_total_session_count()
        except Exception:
            total_sessions = 0

        if self.session_manager and self.session_manager.current_session:
            s_name = self.session_manager.current_session.name
            s_msg_count = len(
                self.session_manager.repo.get_session_messages(
                    self.session_manager.current_session.id
                )
            )

        # Embedding stats (research mode only)
        embedding_model = None
        embedding_texts = 0
        embedding_api_calls = 0
        embedding_prompt_tokens = 0

        if self.research_mode:
            from asky.research.embeddings import get_embedding_client

            client = get_embedding_client()
            embedding_model = client.model
            stats = client.get_usage_stats()
            embedding_texts = stats["texts_embedded"]
            embedding_api_calls = stats["api_calls"]
            embedding_prompt_tokens = stats["prompt_tokens"]

        shortlist_enabled = bool(self.shortlist_stats.get("enabled"))
        shortlist_collected = int(self.shortlist_stats.get("collected", 0) or 0)
        shortlist_processed = int(self.shortlist_stats.get("processed", 0) or 0)
        shortlist_selected = int(self.shortlist_stats.get("selected", 0) or 0)
        shortlist_warnings = int(self.shortlist_stats.get("warnings", 0) or 0)
        shortlist_elapsed_ms = float(self.shortlist_stats.get("elapsed_ms", 0.0) or 0.0)

        effective_max_turns = self.max_turns_override
        if (
            effective_max_turns is None
            and self.session_manager
            and self.session_manager.current_session
        ):
            effective_max_turns = self.session_manager.current_session.max_turns
        if effective_max_turns is None:
            effective_max_turns = self.model_config.get("max_turns", MAX_TURNS)

        state = BannerState(
            model_alias=self.model_alias,
            model_id=model_id,
            sum_alias=sum_alias,
            sum_id=sum_id,
            model_ctx=model_ctx,
            sum_ctx=sum_ctx,
            max_turns=effective_max_turns,
            current_turn=current_turn,
            db_count=db_count,
            session_name=s_name,
            session_msg_count=s_msg_count,
            total_sessions=total_sessions,
            main_token_usage=dict(self.usage_tracker.usage),
            sum_token_usage=dict(self.summarization_tracker.usage)
            if self.summarization_tracker
            else {},
            tool_usage=self.usage_tracker.get_tool_usage(),
            status_message=status_message,
            research_mode=self.research_mode,
            embedding_model=embedding_model,
            embedding_texts=embedding_texts,
            embedding_api_calls=embedding_api_calls,
            embedding_prompt_tokens=embedding_prompt_tokens,
            compact_banner=COMPACT_BANNER,
            shortlist_enabled=shortlist_enabled,
            shortlist_collected=shortlist_collected,
            shortlist_processed=shortlist_processed,
            shortlist_selected=shortlist_selected,
            shortlist_warnings=shortlist_warnings,
            shortlist_elapsed_ms=shortlist_elapsed_ms,
        )

        return get_banner(state)
