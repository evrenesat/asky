"""Chat implementation for asky CLI."""

from __future__ import annotations
import argparse
import json
import logging
import time
from datetime import datetime
from typing import Any, List, Dict, Optional, Set, TYPE_CHECKING

from rich.console import Console

if TYPE_CHECKING:
    from asky.api.types import PreloadResolution
from rich.panel import Panel
from rich.table import Table

from asky.config import (
    MODELS,
    LIVE_BANNER,
    SESSION_IDLE_TIMEOUT_MINUTES,
)
from asky.api import AskyClient, AskyConfig, AskyTurnRequest, ContextOverflowError
from asky.api.context import load_context_from_history
from asky.api.preload import (
    build_shortlist_stats as api_build_shortlist_stats,
    combine_preloaded_source_context as api_combine_preloaded_source_context,
    shortlist_enabled_for_request as api_shortlist_enabled_for_request,
)
from asky.core import (
    ConversationEngine,
    UsageTracker,
    construct_system_prompt,
    construct_research_system_prompt,
    generate_summaries,
    SessionManager,
    get_shell_session_id,
    set_shell_session_id,
    append_research_guidance,
)
from asky.storage import (
    get_history,
    get_interaction_context,
    save_interaction,
)
from asky.cli.display import InterfaceRenderer
from asky.lazy_imports import call_attr
from asky.core.session_manager import generate_session_name

logger = logging.getLogger(__name__)
BACKGROUND_SUMMARY_DRAIN_STATUS = "Finalizing background page summaries..."
VERBOSE_BORDER_STYLE_BY_ROLE = {
    "system": "blue",
    "user": "green",
    "assistant": "cyan",
    "tool": "magenta",
}


def shortlist_prompt_sources(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Lazy-import shortlist pipeline so startup cost is paid only when enabled."""
    return call_attr(
        "asky.research.source_shortlist", "shortlist_prompt_sources", *args, **kwargs
    )


def preload_local_research_sources(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Lazy-import local ingestion flow to keep startup fast for non-research chats."""
    return call_attr(
        "asky.cli.local_ingestion_flow",
        "preload_local_research_sources",
        *args,
        **kwargs,
    )


def format_shortlist_context(shortlist_payload: Dict[str, Any]) -> str:
    """Lazy-import shortlist formatter for same startup behavior as shortlist collection."""
    return call_attr(
        "asky.research.source_shortlist",
        "format_shortlist_context",
        shortlist_payload,
    )


def format_local_ingestion_context(local_payload: Dict[str, Any]) -> Optional[str]:
    """Lazy-import local-ingestion context formatter."""
    return call_attr(
        "asky.cli.local_ingestion_flow",
        "format_local_ingestion_context",
        local_payload,
    )


def load_context(continue_ids: str, summarize: bool) -> Optional[str]:
    """Load context from previous interactions."""
    console = Console()

    try:
        resolution = load_context_from_history(
            continue_ids,
            summarize,
            get_history_fn=get_history,
            get_interaction_context_fn=get_interaction_context,
        )
        if resolution.context_str:
            console.print(
                f"\n[Loaded context from IDs: {', '.join(map(str, resolution.resolved_ids))}]"
            )
        return resolution.context_str
    except ValueError as exc:
        message = str(exc)
        if message.startswith("Invalid continue IDs format"):
            console.print(
                "[bold red]Error:[/] Invalid format for -c/--continue-chat. "
                "Use comma-separated IDs, completion selector tokens, or ~N for relative."
            )
        else:
            console.print(f"[bold red]Error:[/] {message}")
        return None


def build_messages(
    args: argparse.Namespace,
    context_str: str,
    query_text: str,
    session_manager: Optional[SessionManager] = None,
    research_mode: bool = False,
    preload: Optional[PreloadResolution] = None,
    local_kb_hint_enabled: bool = False,
    system_prompt_override: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Build the initial message list for the conversation."""
    # Use research prompt if in research mode
    if system_prompt_override:
        system_prompt = system_prompt_override
    elif research_mode:
        system_prompt = construct_research_system_prompt()
        system_prompt = append_research_guidance(
            system_prompt,
            corpus_preloaded=preload.is_corpus_preloaded if preload else False,
            local_kb_hint_enabled=local_kb_hint_enabled,
        )
    else:
        system_prompt = construct_system_prompt()

    messages = [
        {
            "role": "system",
            "content": system_prompt,
        },
    ]

    if session_manager:
        messages.extend(session_manager.build_context_messages())
    elif context_str:
        messages.append(
            {
                "role": "user",
                "content": f"Context from previous queries:\n{context_str}\n\nMy new query is below.",
            }
        )

    user_content = query_text
    if preload and preload.combined_context:
        user_content = (
            f"{query_text}\n\n"
            f"Preloaded sources gathered before tool calls:\n"
            f"{preload.combined_context}\n\n"
            "Use this preloaded corpus as a starting point, then verify with tools before citing."
        )

    messages.append({"role": "user", "content": user_content})
    return messages


def _build_shortlist_banner_stats(
    shortlist_payload: Dict[str, Any], shortlist_elapsed_ms: float
) -> Dict[str, Any]:
    """Extract compact shortlist stats for banner rendering."""
    return api_build_shortlist_stats(shortlist_payload, shortlist_elapsed_ms)


def _shortlist_enabled_for_request(
    args: argparse.Namespace,
    model_config: Dict[str, Any],
    research_mode: bool,
) -> tuple[bool, str]:
    """Resolve shortlist enablement with precedence: lean > model > global flags."""
    return api_shortlist_enabled_for_request(
        lean=bool(getattr(args, "lean", False)),
        model_config=model_config,
        research_mode=research_mode,
        shortlist_override=str(getattr(args, "shortlist", "auto")),
    )


def _parse_disabled_tools(raw_values: Optional[List[str]]) -> Set[str]:
    """Parse repeated/comma-separated --tool-off values into unique tool names."""
    disabled_tools: Set[str] = set()
    for raw_value in raw_values or []:
        for token in str(raw_value).split(","):
            tool_name = token.strip()
            if tool_name:
                disabled_tools.add(tool_name)

    if "all" in disabled_tools:
        from asky.core.tool_registry_factory import get_all_available_tool_names

        return set(get_all_available_tool_names())

    return disabled_tools


def _append_enabled_tool_guidelines(
    messages: List[Dict[str, str]], tool_guidelines: List[str]
) -> None:
    """Append enabled-tool guidance block to the system prompt."""
    if not tool_guidelines:
        return
    if not messages or messages[0].get("role") != "system":
        return

    guideline_lines = [
        "",
        "Enabled Tool Guidelines:",
        *[f"- {guideline}" for guideline in tool_guidelines],
    ]
    messages[0]["content"] = f"{messages[0].get('content', '')}\n" + "\n".join(
        guideline_lines
    )


def _ensure_research_session(
    session_manager: Optional[SessionManager],
    model_config: Dict[str, Any],
    usage_tracker: UsageTracker,
    summarization_tracker: UsageTracker,
    query_text: str,
    console: Console,
) -> SessionManager:
    """Ensure research mode always has an active session for memory isolation."""
    if session_manager and session_manager.current_session:
        return session_manager

    active_manager = session_manager or SessionManager(
        model_config,
        usage_tracker,
        summarization_tracker=summarization_tracker,
    )
    session_name = generate_session_name(query_text or "research")
    session = active_manager.create_session(session_name)
    set_shell_session_id(session.id)
    console.print(
        f"\n[Research mode: started session {session.id} ('{session.name or 'auto'}')]"
    )
    return active_manager


def _print_shortlist_verbose(
    console: Console, shortlist_payload: Dict[str, Any]
) -> None:
    """Render shortlist processing/selection trace for verbose terminal output."""
    if not shortlist_payload.get("enabled"):
        console.print(
            Panel(
                "Shortlist disabled for current mode.",
                title="Pre-LLM Shortlist",
                border_style="yellow",
            )
        )
        return

    trace = shortlist_payload.get("trace", {}) or {}
    processed = trace.get("processed_candidates", []) or []
    selected = shortlist_payload.get("candidates", []) or []

    processed_table = Table(
        title="Shortlist Processed Links",
        show_header=True,
        header_style="bold cyan",
    )
    processed_table.add_column("#", justify="right", style="dim", width=4)
    processed_table.add_column("Source", style="magenta", width=10)
    processed_table.add_column("URL", style="white")

    if processed:
        for idx, item in enumerate(processed, start=1):
            processed_table.add_row(
                str(idx),
                str(item.get("source_type", "")),
                str(item.get("url", "")),
            )
    else:
        processed_table.add_row("-", "-", "No links were processed.")

    selected_table = Table(
        title="Shortlist Selected Links Passed To Model Context",
        show_header=True,
        header_style="bold green",
    )
    selected_table.add_column("Rank", justify="right", width=5)
    selected_table.add_column("Score", justify="right", width=8)
    selected_table.add_column("Source", style="magenta", width=10)
    selected_table.add_column("URL", style="white")

    if selected:
        for item in selected:
            selected_table.add_row(
                str(item.get("rank", "")),
                f"{float(item.get('final_score', 0.0)):.3f}",
                str(item.get("source_type", "")),
                str(item.get("url", "")),
            )
    else:
        selected_table.add_row("-", "-", "-", "No links selected.")

    console.print(processed_table)
    console.print(selected_table)

    warnings = shortlist_payload.get("warnings", []) or []
    if warnings:
        warning_text = "\n".join(f"- {warning}" for warning in warnings[:8])
        console.print(
            Panel(
                warning_text,
                title=f"Shortlist Warnings ({len(warnings)})",
                border_style="yellow",
            )
        )


def _combine_preloaded_source_context(
    *context_blocks: Optional[str],
) -> Optional[str]:
    """Merge multiple preloaded-source context blocks into one message section."""
    return api_combine_preloaded_source_context(*context_blocks)


def _drain_research_background_summaries() -> None:
    """Wait for pending research cache background summaries."""
    try:
        from asky.research.cache import ResearchCache

        ResearchCache().wait_for_background_summaries()
    except Exception as exc:
        logger.debug("Skipping background summary drain: %s", exc)


def _to_pretty_json(value: Any) -> str:
    """Render arbitrary payload values as indented JSON when possible."""
    try:
        return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def _estimate_message_content_chars(message: Dict[str, Any]) -> int:
    """Estimate readable content size for main-model payload summaries."""
    content = message.get("content")
    if content is None:
        return 0
    if isinstance(content, str):
        return len(content)
    return len(_to_pretty_json(content))


def _origin_direction_for_role(role: str) -> str:
    """Classify a role by where it originally came from."""
    return "inbound-origin" if role == "assistant" else "outbound-origin"


def _format_message_payload(message: Dict[str, Any]) -> str:
    """Build a readable multiline representation of one message payload."""
    blocks: List[str] = []

    content = message.get("content")
    if content is None:
        blocks.append("content:\n(none)")
    elif isinstance(content, str):
        blocks.append(f"content:\n{content}" if content else "content:\n(empty string)")
    else:
        blocks.append(f"content:\n{_to_pretty_json(content)}")

    tool_calls = message.get("tool_calls")
    if tool_calls:
        blocks.append(f"tool_calls:\n{_to_pretty_json(tool_calls)}")

    tool_call_id = message.get("tool_call_id")
    if tool_call_id:
        blocks.append(f"tool_call_id:\n{tool_call_id}")

    extra_keys = sorted(
        key
        for key in message.keys()
        if key not in {"role", "content", "tool_calls", "tool_call_id"}
    )
    if extra_keys:
        extra_fields = {key: message.get(key) for key in extra_keys}
        blocks.append(f"extra_fields:\n{_to_pretty_json(extra_fields)}")

    return "\n\n".join(blocks) if blocks else "(empty message payload)"


def _render_tool_schema_table(tool_schemas: List[Dict[str, Any]]) -> Optional[Table]:
    """Render enabled tool schema metadata as a compact table."""
    if not tool_schemas:
        return None
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Tool", style="bold")
    table.add_column("Required Params")
    table.add_column("Optional Params")
    table.add_column("Description")

    for schema in tool_schemas:
        function_schema = schema.get("function", {}) if isinstance(schema, dict) else {}
        name = str(function_schema.get("name", "unknown"))
        description = str(function_schema.get("description", "") or "")
        parameters = function_schema.get("parameters", {}) or {}
        if not isinstance(parameters, dict):
            parameters = {}
        properties = parameters.get("properties", {}) or {}
        if not isinstance(properties, dict):
            properties = {}
        required = parameters.get("required", []) or []
        required_set = {str(item) for item in required if isinstance(item, str)}
        required_params = ", ".join(sorted(required_set)) if required_set else "-"
        optional_params = sorted(
            [
                str(param)
                for param in properties.keys()
                if str(param) not in required_set
            ]
        )
        optional_summary = ", ".join(optional_params) if optional_params else "-"
        table.add_row(name, required_params, optional_summary, description)
    return table


def _print_main_model_request_payload(
    console: Console, payload: Dict[str, Any]
) -> None:
    """Print one outbound main-model request block with payload and transport metadata."""
    messages = payload.get("messages") or []
    if not isinstance(messages, list):
        messages = []

    tool_schemas = payload.get("tool_schemas") or []
    if not isinstance(tool_schemas, list):
        tool_schemas = []
    tool_guidelines = payload.get("tool_guidelines") or []
    if not isinstance(tool_guidelines, list):
        tool_guidelines = []

    transport_request = payload.get("transport_request") or {}
    if not isinstance(transport_request, dict):
        transport_request = {}

    turn = int(payload.get("turn", 0) or 0)
    phase = str(payload.get("phase", "main_loop"))
    model_alias = payload.get("model_alias")
    model_id = str(payload.get("model_id", "unknown"))
    model_display = str(model_alias) if model_alias else model_id
    use_tools = bool(payload.get("use_tools", False))

    metadata_lines = [
        f"Model: {model_display}",
        f"Turn: {turn}",
        f"Phase: {phase}",
        f"Tools enabled: {'yes' if use_tools else 'no'}",
        f"Direction: Outbound Request",
        f"Messages: {len(messages)}",
    ]
    if transport_request.get("url"):
        metadata_lines.append(f"Target: {transport_request.get('url')}")
    if transport_request.get("method"):
        metadata_lines.append(f"Method: {transport_request.get('method')}")
    attempt = transport_request.get("attempt")
    if attempt is not None:
        metadata_lines.append(f"Attempt: {attempt}")

    console.print(
        Panel(
            "\n".join(metadata_lines),
            title="Main Model Outbound Request",
            border_style="bright_blue",
            expand=False,
        )
    )

    summary_table = Table(show_header=True, header_style="bold blue")
    summary_table.add_column("#", justify="right", style="dim")
    summary_table.add_column("Role", style="bold")
    summary_table.add_column("Origin")
    summary_table.add_column("Chars", justify="right")
    summary_table.add_column("Fields")

    for index, message in enumerate(messages, start=1):
        message_dict = message if isinstance(message, dict) else {"content": message}
        role = str(message_dict.get("role", "unknown"))
        extra_fields = sorted(
            key
            for key in message_dict.keys()
            if key not in {"role", "content", "tool_calls", "tool_call_id"}
        )
        fields_summary = ", ".join(extra_fields) if extra_fields else "-"
        summary_table.add_row(
            str(index),
            role,
            _origin_direction_for_role(role),
            str(_estimate_message_content_chars(message_dict)),
            fields_summary,
        )
    console.print(summary_table)

    tool_table = _render_tool_schema_table(tool_schemas)
    if tool_table is not None:
        console.print(tool_table)
    if tool_guidelines:
        guidelines_text = "\n".join(f"- {str(item)}" for item in tool_guidelines)
        console.print(
            Panel(
                guidelines_text,
                title=f"Tool Guidelines ({len(tool_guidelines)})",
                border_style="magenta",
                expand=False,
            )
        )

    for index, message in enumerate(messages, start=1):
        message_dict = message if isinstance(message, dict) else {"content": message}
        role = str(message_dict.get("role", "unknown"))
        panel_title = (
            f"Request Message {index}/{len(messages)} | role={role} "
            f"| origin={_origin_direction_for_role(role)}"
        )
        border_style = VERBOSE_BORDER_STYLE_BY_ROLE.get(role, "white")
        console.print(
            Panel(
                _format_message_payload(message_dict),
                title=panel_title,
                border_style=border_style,
                expand=False,
            )
        )


def _print_main_model_response_payload(
    console: Console, payload: Dict[str, Any]
) -> None:
    """Print one inbound main-model response block with merged transport metadata."""
    turn = int(payload.get("turn", 0) or 0)
    phase = str(payload.get("phase", "main_loop"))
    model_alias = payload.get("model_alias")
    model_id = str(payload.get("model_id", "unknown"))
    model_display = str(model_alias) if model_alias else model_id
    message = payload.get("message")
    if not isinstance(message, dict):
        message = {"content": message}

    transport_response = payload.get("transport_response") or {}
    if not isinstance(transport_response, dict):
        transport_response = {}
    transport_errors = payload.get("transport_errors") or []
    if not isinstance(transport_errors, list):
        transport_errors = []

    role = str(message.get("role", "assistant"))
    metadata_lines = [
        f"Model: {model_display}",
        f"Turn: {turn}",
        f"Phase: {phase}",
        "Direction: Inbound Response",
        f"Role: {role}",
    ]
    if transport_response:
        if transport_response.get("status_code") is not None:
            metadata_lines.append(f"Status: {transport_response.get('status_code')}")
        if transport_response.get("response_type"):
            metadata_lines.append(
                f"Response type: {transport_response.get('response_type')}"
            )
        if transport_response.get("content_type"):
            metadata_lines.append(
                f"Content-Type: {transport_response.get('content_type')}"
            )
        if transport_response.get("response_bytes") is not None:
            metadata_lines.append(
                f"Response bytes: {transport_response.get('response_bytes')}"
            )
        if transport_response.get("elapsed_ms") is not None:
            metadata_lines.append(
                f"Elapsed ms: {float(transport_response.get('elapsed_ms')):.1f}"
            )
    if transport_errors:
        metadata_lines.append(
            f"Transport errors before success: {len(transport_errors)}"
        )

    console.print(
        Panel(
            "\n".join(metadata_lines),
            title="Main Model Inbound Response",
            border_style="bright_cyan",
            expand=False,
        )
    )
    if transport_errors:
        error_lines = []
        for index, item in enumerate(transport_errors, start=1):
            if not isinstance(item, dict):
                continue
            status = item.get("status_code")
            error = item.get("error")
            elapsed_ms = item.get("elapsed_ms")
            details = [f"{index}."]
            if status is not None:
                details.append(f"status={status}")
            if elapsed_ms is not None:
                details.append(f"elapsed_ms={float(elapsed_ms):.1f}")
            if error:
                details.append(f"error={error}")
            error_lines.append(" ".join(details))
        if error_lines:
            console.print(
                Panel(
                    "\n".join(error_lines),
                    title="Main Model Transport Errors",
                    border_style="yellow",
                    expand=False,
                )
            )
    console.print(
        Panel(
            _format_message_payload(message),
            title=f"Inbound Response Message | role={role}",
            border_style=VERBOSE_BORDER_STYLE_BY_ROLE.get(role, "cyan"),
            expand=False,
        )
    )


def _print_preload_provenance(console: Console, payload: Dict[str, Any]) -> None:
    """Print structured preloaded-source provenance before main model call."""
    seed_documents = payload.get("seed_documents") or []
    if not isinstance(seed_documents, list):
        seed_documents = []
    shortlist_selected = payload.get("shortlist_selected") or []
    if not isinstance(shortlist_selected, list):
        shortlist_selected = []
    warnings = payload.get("shortlist_warnings") or []
    if not isinstance(warnings, list):
        warnings = []

    lines = [
        f"Query: {payload.get('query_text', '')}",
        f"Seed direct-answer ready: {bool(payload.get('seed_url_direct_answer_ready', False))}",
        f"Seed context chars: {int(payload.get('seed_url_context_chars', 0) or 0)}",
        f"Shortlist context chars: {int(payload.get('shortlist_context_chars', 0) or 0)}",
        f"Combined context chars: {int(payload.get('combined_context_chars', 0) or 0)}",
        f"Selected shortlist sources: {len(shortlist_selected)}",
        f"Shortlist warnings: {len(warnings)}",
    ]
    console.print(
        Panel(
            "\n".join(lines),
            title="Preloaded Context Sent To Main Model",
            border_style="green",
            expand=False,
        )
    )

    if seed_documents:
        seed_table = Table(show_header=True, header_style="bold green")
        seed_table.add_column("Seed URL")
        seed_table.add_column("Chars", justify="right")
        seed_table.add_column("Status")
        seed_table.add_column("Error")
        for item in seed_documents:
            if not isinstance(item, dict):
                continue
            chars = int(item.get("content_chars", 0) or 0)
            error = str(item.get("error", "") or "")
            warning = str(item.get("warning", "") or "")
            status = "ok"
            if error:
                status = "fetch_error"
            elif warning:
                status = "warning"
            seed_table.add_row(
                str(item.get("url", "")),
                str(chars),
                status,
                error[:120],
            )
        console.print(seed_table)

    if shortlist_selected:
        shortlist_table = Table(show_header=True, header_style="bold green")
        shortlist_table.add_column("Rank", justify="right")
        shortlist_table.add_column("Score", justify="right")
        shortlist_table.add_column("Source")
        shortlist_table.add_column("Snippet chars", justify="right")
        shortlist_table.add_column("URL")
        for item in shortlist_selected[:15]:
            if not isinstance(item, dict):
                continue
            shortlist_table.add_row(
                str(int(item.get("rank", 0) or 0)),
                f"{float(item.get('score', 0.0) or 0.0):.3f}",
                str(item.get("source_type", "")),
                str(int(item.get("snippet_chars", 0) or 0)),
                str(item.get("url", "")),
            )
        console.print(shortlist_table)

    if warnings:
        warning_text = "\n".join(f"- {str(item)}" for item in warnings[:10])
        console.print(
            Panel(
                warning_text,
                title=f"Preload Warnings ({len(warnings)})",
                border_style="yellow",
                expand=False,
            )
        )


def _print_transport_metadata(console: Console, payload: Dict[str, Any]) -> None:
    """Print request/response transport metadata for tool/summarizer internals."""
    kind = str(payload.get("kind", "transport"))
    source = str(payload.get("source", payload.get("transport", "unknown")))
    tool_name = str(payload.get("tool_name", "") or "")
    provider = str(payload.get("provider", "") or "")
    model_alias = str(payload.get("model_alias", "") or "")

    lines: List[str] = []
    phase = str(payload.get("phase", "") or "")
    if phase:
        lines.append(f"Phase: {phase}")
    url = payload.get("url")
    if url:
        lines.append(f"Target: {url}")
    method = payload.get("method")
    if method:
        lines.append(f"Method: {method}")
    status_code = payload.get("status_code")
    if status_code is not None:
        lines.append(f"Status: {status_code}")
    response_type = payload.get("response_type")
    if response_type:
        lines.append(f"Response type: {response_type}")
    content_type = payload.get("content_type")
    if content_type:
        lines.append(f"Content-Type: {content_type}")
    response_bytes = payload.get("response_bytes")
    if response_bytes is not None:
        lines.append(f"Response bytes: {response_bytes}")
    response_chars = payload.get("response_chars")
    if response_chars is not None:
        lines.append(f"Response chars: {response_chars}")
    elapsed_ms = payload.get("elapsed_ms")
    if elapsed_ms is not None:
        lines.append(f"Elapsed ms: {float(elapsed_ms):.1f}")
    error = payload.get("error")
    if error:
        lines.append(f"Error: {error}")

    title_parts = ["Transport"]
    if kind == "transport_request":
        title_parts.append("Request")
    elif kind == "transport_response":
        title_parts.append("Response")
    elif kind == "transport_error":
        title_parts.append("Error")
    if source:
        title_parts.append(f"source={source}")
    if model_alias:
        title_parts.append(f"model={model_alias}")
    if tool_name:
        title_parts.append(f"tool={tool_name}")
    if provider:
        title_parts.append(f"provider={provider}")

    border_style = "cyan"
    if kind == "transport_error":
        border_style = "red"
    elif kind == "transport_request":
        border_style = "yellow"

    console.print(
        Panel(
            "\n".join(lines) if lines else "(no metadata)",
            title=" | ".join(title_parts),
            border_style=border_style,
            expand=False,
        )
    )


def _check_idle_session_timeout(session_id: int, console: Console) -> str:
    """Check if session is idle and prompt user if threshold exceeded."""
    from asky.storage.sqlite import SQLiteHistoryRepository

    if SESSION_IDLE_TIMEOUT_MINUTES <= 0:
        return "continue"

    repo = SQLiteHistoryRepository()
    session = repo.get_session_by_id(session_id)
    if not session or not session.last_used_at:
        return "continue"

    try:
        last_used = datetime.fromisoformat(session.last_used_at)
        elapsed = (datetime.now() - last_used).total_seconds() / 60
    except ValueError:
        return "continue"

    if elapsed < SESSION_IDLE_TIMEOUT_MINUTES:
        return "continue"

    console.print(
        f"\n[yellow]Session '{session.name or session.id}' has been idle for {int(elapsed)} minutes.[/]"
    )
    from rich.prompt import Prompt

    choice = Prompt.ask(
        "[white]Choose action:[/] [bold cyan]\\[c][/][white]ontinue, [bold cyan]\\[n][/][white]ew session, [bold cyan]\\[o][/][white]ne-off query",
        choices=["c", "n", "o"],
        default="c",
        console=console,
        show_choices=False,
    ).lower()

    if choice == "n":
        console.print("[bold cyan]Action: New session[/]")
        return "new"
    elif choice == "o":
        console.print("[bold cyan]Action: One-off query[/]")
        return "oneoff"
    else:
        console.print("[bold cyan]Action: Continue[/]")
        return "continue"


def run_chat(args: argparse.Namespace, query_text: str) -> None:
    """Run the chat conversation flow."""
    from asky.core import clear_shell_session
    from asky.storage.sqlite import SQLiteHistoryRepository

    console = Console()

    usage_tracker = UsageTracker()
    summarization_tracker = UsageTracker()
    model_config = MODELS[args.model]
    research_mode = bool(getattr(args, "research", False))
    local_corpus = getattr(args, "local_corpus", None)
    if local_corpus:
        research_mode = True

    disabled_tools = _parse_disabled_tools(getattr(args, "tool_off", []))

    is_lean = bool(getattr(args, "lean", False))
    if is_lean:
        from asky.core.tool_registry_factory import get_all_available_tool_names

        # In lean mode, disable ALL tools
        all_tools = get_all_available_tool_names()
        disabled_tools.update(all_tools)

    # Setup display renderer early so pre-LLM shortlist work is visible in banner
    renderer = InterfaceRenderer(
        model_config=model_config,
        model_alias=args.model,
        usage_tracker=usage_tracker,
        summarization_tracker=summarization_tracker,
        session_manager=None,
        messages=[],
        research_mode=research_mode,
        max_turns=getattr(args, "turns", None),
    )

    use_banner = False
    main_model_traces: Dict[str, Dict[str, Any]] = {}

    def _trace_key(payload: Dict[str, Any]) -> str:
        turn = int(payload.get("turn", 0) or 0)
        phase = str(payload.get("phase", "main_loop"))
        return f"{turn}:{phase}"

    # Create display callback for live banner mode
    def display_callback(
        current_turn: int,
        status_message: Optional[str] = None,
        is_final: bool = False,
        final_answer: Optional[str] = None,
    ):
        if is_final:
            # Stop the Live display before printing final answer
            renderer.stop_live()
            if final_answer:
                if is_lean:
                    # Render raw markdown without "Assistant:" label
                    from rich.markdown import Markdown

                    renderer.console.print(Markdown(final_answer))
                else:
                    renderer.print_final_answer(final_answer)
        else:
            # Update banner in-place
            if use_banner:
                renderer.update_banner(current_turn, status_message)

    def verbose_output_callback(renderable: Any) -> None:
        """Route verbose output through the active live console when present."""
        output_console = (
            renderer.live.console if use_banner and renderer.live else renderer.console
        )
        if isinstance(renderable, dict):
            kind = str(renderable.get("kind", ""))
            source = str(renderable.get("source", "") or "")
            trace_key = _trace_key(renderable)

            if kind == "preload_provenance":
                _print_preload_provenance(output_console, renderable)
                return
            if kind == "llm_request_messages":
                trace_state = main_model_traces.setdefault(trace_key, {})
                trace_state["request_payload"] = renderable
                trace_state.setdefault("transport_errors", [])
                return
            if kind == "llm_response_message":
                trace_state = main_model_traces.setdefault(trace_key, {})
                request_payload = trace_state.get("request_payload")
                if isinstance(request_payload, dict) and not trace_state.get(
                    "request_printed"
                ):
                    request_for_print = dict(request_payload)
                    request_transport = trace_state.get("transport_request")
                    if isinstance(request_transport, dict):
                        request_for_print["transport_request"] = request_transport
                    _print_main_model_request_payload(output_console, request_for_print)
                    trace_state["request_printed"] = True

                response_for_print = dict(renderable)
                response_transport = trace_state.get("transport_response")
                if isinstance(response_transport, dict):
                    response_for_print["transport_response"] = response_transport
                response_errors = trace_state.get("transport_errors", [])
                if isinstance(response_errors, list):
                    response_for_print["transport_errors"] = response_errors
                _print_main_model_response_payload(output_console, response_for_print)
                main_model_traces.pop(trace_key, None)
                return
            if kind in {"transport_request", "transport_response", "transport_error"}:
                if source == "main_model":
                    trace_state = main_model_traces.setdefault(trace_key, {})
                    if kind == "transport_request":
                        trace_state["transport_request"] = renderable
                        request_payload = trace_state.get("request_payload")
                        if isinstance(request_payload, dict) and not trace_state.get(
                            "request_printed"
                        ):
                            request_for_print = dict(request_payload)
                            request_for_print["transport_request"] = renderable
                            _print_main_model_request_payload(
                                output_console, request_for_print
                            )
                            trace_state["request_printed"] = True
                    elif kind == "transport_response":
                        trace_state["transport_response"] = renderable
                    else:
                        transport_errors = trace_state.setdefault(
                            "transport_errors", []
                        )
                        if isinstance(transport_errors, list):
                            transport_errors.append(renderable)
                    return
                _print_transport_metadata(output_console, renderable)
                return
            if kind == "tool_call" or "tool_name" in renderable:
                tool_name = str(renderable.get("tool_name", "unknown_tool"))
                call_index = int(renderable.get("call_index", 0) or 0)
                total_calls = int(renderable.get("total_calls", 0) or 0)
                turn = int(renderable.get("turn", 0) or 0)
                args_value = renderable.get("arguments", {})
                renderable = Panel(
                    _to_pretty_json(args_value),
                    title=f"Tool {call_index}/{total_calls} | Turn {turn} | {tool_name}",
                    border_style="cyan",
                    expand=False,
                )
        if use_banner and renderer.live:
            renderer.live.console.print(renderable)
            return
        renderer.console.print(renderable)

    def summarization_status_callback(message: Optional[str]) -> None:
        """Refresh banner during internal summarization calls."""
        if not use_banner:
            return
        renderer.update_banner(renderer.current_turn, status_message=message)

    # Resolve session and handle idle timeout BEFORE starting the live banner
    sticky_session_name = (
        " ".join(args.sticky_session) if getattr(args, "sticky_session", None) else None
    )
    resume_session_term = (
        " ".join(args.resume_session) if getattr(args, "resume_session", None) else None
    )
    shell_session_id = get_shell_session_id()

    elephant_mode = bool(getattr(args, "elephant_mode", False))

    if not sticky_session_name and not resume_session_term and shell_session_id:
        action = _check_idle_session_timeout(shell_session_id, console)
        if action == "new":
            from asky.core import clear_shell_session

            clear_shell_session()
            shell_session_id = None
            sticky_session_name = generate_session_name(query_text)
        elif action == "oneoff":
            from asky.core import clear_shell_session

            clear_shell_session()
            shell_session_id = None

    if elephant_mode and not bool(
        sticky_session_name or resume_session_term or shell_session_id
    ):
        console.print(
            "[yellow]Warning:[/] --elephant-mode requires an active session "
            "(-ss or -rs). Flag ignored."
        )
        elephant_mode = False

    # Wrap in try/finally to ensure renderer.stop_live() is called.
    try:
        effective_query_text = query_text
        use_banner = LIVE_BANNER and not is_lean
        if use_banner:
            renderer.start_live()

        # Handle Terminal Context
        lines_count = args.terminal_lines if args.terminal_lines is not None else 0

        if lines_count > 0:
            from asky.cli.terminal import inject_terminal_context

            working_messages = [{"role": "user", "content": effective_query_text}]
            warn_on_error = args.terminal_lines is not None

            status_cb = lambda msg: (
                renderer.update_banner(0, status_message=msg) if use_banner else None
            )

            inject_terminal_context(
                working_messages,
                lines_count,
                verbose=args.verbose,
                warn_on_error=warn_on_error,
                status_callback=status_cb,
            )
            if working_messages and working_messages[-1]["role"] == "user":
                effective_query_text = working_messages[-1]["content"]

            if use_banner:
                renderer.update_banner(0, status_message=None)

        asky_client = AskyClient(
            AskyConfig(
                model_alias=args.model,
                summarize=args.summarize,
                verbose=args.verbose,
                double_verbose=bool(getattr(args, "double_verbose", False)),
                open_browser=args.open,
                research_mode=research_mode,
                disabled_tools=disabled_tools,
                system_prompt_override=getattr(args, "system_prompt", None),
            ),
            usage_tracker=usage_tracker,
            summarization_tracker=summarization_tracker,
        )

        has_session = bool(
            sticky_session_name or resume_session_term or shell_session_id
        )
        if elephant_mode and not has_session:
            console.print(
                "[yellow]Warning:[/] --elephant-mode requires an active session "
                "(-ss or -rs). Flag ignored."
            )
            elephant_mode = False

        turn_request = AskyTurnRequest(
            query_text=effective_query_text,
            continue_ids=args.continue_ids,
            summarize_context=args.summarize,
            sticky_session_name=sticky_session_name,
            resume_session_term=resume_session_term,
            shell_session_id=shell_session_id,
            lean=bool(getattr(args, "lean", False)),
            preload_local_sources=True,
            preload_shortlist=True,
            additional_source_context=None,
            local_corpus_paths=local_corpus,
            save_history=False,  # We handle saving manually after rendering
            elephant_mode=elephant_mode,
            max_turns=getattr(args, "turns", None),
            research_flag_provided=bool(getattr(args, "research_flag_provided", False)),
            research_source_mode=getattr(args, "research_source_mode", None),
            replace_research_corpus=bool(
                getattr(args, "replace_research_corpus", False)
            ),
            shortlist_override=str(getattr(args, "shortlist", "auto")),
        )

        display_cb = display_callback
        turn_result = asky_client.run_turn(
            turn_request,
            display_callback=display_cb,
            verbose_output_callback=verbose_output_callback,
            summarization_status_callback=summarization_status_callback,
            preload_status_callback=(
                (lambda message: renderer.update_banner(0, status_message=message))
                if use_banner
                else None
            ),
            messages_prepared_callback=lambda msgs: setattr(renderer, "messages", msgs),
            session_resolved_callback=lambda sm: setattr(
                renderer, "session_manager", sm
            ),
            set_shell_session_id_fn=set_shell_session_id,
            clear_shell_session_fn=clear_shell_session,
            shortlist_executor=shortlist_prompt_sources,
            shortlist_formatter=format_shortlist_context,
            shortlist_stats_builder=_build_shortlist_banner_stats,
            local_ingestion_executor=preload_local_research_sources,
            local_ingestion_formatter=format_local_ingestion_context,
            initial_notice_callback=lambda notice: console.print(
                f"[bold red]Error:[/] {notice}"
                if notice.startswith("No sessions")
                else f"\n[{notice}]"
            ),
        )
        final_answer = turn_result.final_answer
        session_research_value = getattr(turn_result.session, "research_mode", None)
        if session_research_value in (True, False):
            effective_research_mode = session_research_value
        else:
            effective_research_mode = research_mode

        renderer.set_shortlist_stats(turn_result.preload.shortlist_stats)

        if args.verbose and turn_result.preload.shortlist_payload:
            verbose_console = (
                renderer.live.console
                if use_banner and renderer.live
                else renderer.console
            )
            _print_shortlist_verbose(
                verbose_console, turn_result.preload.shortlist_payload
            )

        for notice in turn_result.notices:
            if notice.startswith("No sessions found matching"):
                console.print(f"[bold red]Error:[/] {notice}")
                continue
            if notice.startswith("Multiple sessions found for"):
                console.print(notice + ":")
                for session in turn_result.session.matched_sessions:
                    console.print(
                        f"  {session['id']}: {session['name'] or '(no name)'} ({session['created_at']})"
                    )
                continue
            console.print(f"\n[{notice}]")

        if turn_result.halted:
            return

        # Auto-generate HTML Report FIRST, before saving history (so the CLI responds faster)
        pre_reserved_ids = None
        saved_message_id_for_archive = None

        if final_answer and not is_lean:
            from asky.rendering import save_html_report, extract_markdown_title

            html_source = ""
            if turn_result.session_id:
                # Generate full session transcript
                try:
                    repo = SQLiteHistoryRepository()
                    msgs = repo.get_session_messages(int(turn_result.session_id))
                    transcript_parts = []
                    for m in msgs:
                        role_title = "User" if m.role == "user" else "Assistant"
                        transcript_parts.append(f"## {role_title}\n\n{m.content}")

                    # Append the current turn that isn't saved yet
                    transcript_parts.append(f"## User\n\n{effective_query_text}")
                    transcript_parts.append(f"## Assistant\n\n{final_answer}")

                    html_source = "\n\n---\n\n".join(transcript_parts)
                except Exception as e:
                    console.print(
                        f"[bold red]Error:[/] fetching session messages for HTML report: {e}"
                    )
                    html_source = f"## Query\n{effective_query_text}\n\n## Assistant\n{final_answer}"
            else:
                # Single turn report
                html_source = (
                    f"## Query\n{effective_query_text}\n\n## Assistant\n{final_answer}"
                )
                # Pre-reserve interaction IDs so we have a message ID for the archive immediately
                try:
                    from asky.storage import reserve_interaction

                    pre_reserved_ids = reserve_interaction(args.model)
                    saved_message_id_for_archive = pre_reserved_ids[1]  # assistant_id
                except Exception as e:
                    logger.debug(f"Failed to pre-reserve history IDs: {e}")

            # Extract title explicitly from the new answer to fix "untitled" archives
            filename_hint = extract_markdown_title(final_answer)

            session_name = ""
            session_id_int = None
            if turn_result.session_id:
                session_id_int = int(turn_result.session_id)
                if renderer.session_manager:
                    session = renderer.session_manager.current_session
                    if session:
                        session_name = session.name or ""

            report_path, sidebar_url = save_html_report(
                html_source,
                filename_hint=filename_hint,
                session_name=session_name,
                message_id=saved_message_id_for_archive,
                session_id=session_id_int,
            )
            if report_path:
                console.print(f"Open in browser: [bold cyan]file://{report_path}[/]")
                console.print(f"Open with index: [bold cyan]{sidebar_url}[/]")

        # NOW save history synchronously with a live status banner
        if final_answer and not is_lean:
            try:
                if use_banner:
                    renderer.start_live()

                def on_history_status(msg: str) -> None:
                    if use_banner:
                        renderer.update_banner(0, status_message=msg)

                finalize_result = asky_client.finalize_turn_history(
                    turn_request,
                    turn_result,
                    summarization_status_callback=on_history_status,
                    pre_reserved_message_ids=pre_reserved_ids,
                )
                for notice in finalize_result.notices:
                    console.print(f"\n[{notice}]")
                if use_banner and effective_research_mode:
                    renderer.update_banner(
                        renderer.current_turn,
                        status_message=BACKGROUND_SUMMARY_DRAIN_STATUS,
                    )
                    _drain_research_background_summaries()
            finally:
                if use_banner:
                    renderer.update_banner(renderer.current_turn, status_message=None)
                    renderer.stop_live()

        # Send Email if requested
        if final_answer and getattr(args, "mail_recipients", None):
            from asky.email_sender import send_email

            recipients = [x.strip() for x in args.mail_recipients.split(",")]
            email_subject = args.subject or f"asky Result: {effective_query_text[:50]}"
            send_email(recipients, email_subject, final_answer)

        # Push data to configured endpoint if requested
        if final_answer and getattr(args, "push_data_endpoint", None):
            from asky.push_data import execute_push_data

            dynamic_args = dict(args.push_params) if args.push_params else {}
            result = execute_push_data(
                args.push_data_endpoint,
                dynamic_args=dynamic_args,
                query=effective_query_text,
                answer=final_answer,
                model=args.model,
            )
            if result["success"]:
                if not is_lean:
                    console.print(
                        f"[Push data successful: {result['endpoint']} - {result['status_code']}]"
                    )
            else:
                # Always print errors
                console.print(
                    f"[Push data failed: {result['endpoint']} - {result['error']}]"
                )

    except KeyboardInterrupt:
        console.print("\nAborted by user.")
    except ContextOverflowError as e:
        console.print(
            "\n[bold red]Context overflow:[/] "
            f"{e}. Try a larger-context model or narrower query."
        )
    except Exception as e:
        console.print(f"\n[bold red]An error occurred:[/] {e}")
        if args.verbose:
            import traceback

            traceback.print_exc()
    finally:
        if main_model_traces:
            flush_console = (
                renderer.live.console
                if use_banner and renderer.live
                else renderer.console
            )
            for trace_state in main_model_traces.values():
                request_payload = trace_state.get("request_payload")
                if isinstance(request_payload, dict) and not trace_state.get(
                    "request_printed"
                ):
                    request_for_print = dict(request_payload)
                    request_transport = trace_state.get("transport_request")
                    if isinstance(request_transport, dict):
                        request_for_print["transport_request"] = request_transport
                    _print_main_model_request_payload(flush_console, request_for_print)

                transport_errors = trace_state.get("transport_errors", [])
                if transport_errors:
                    for item in transport_errors:
                        if isinstance(item, dict):
                            _print_transport_metadata(flush_console, item)
        # Ensure Live is stopped on any exit path
        renderer.stop_live()
