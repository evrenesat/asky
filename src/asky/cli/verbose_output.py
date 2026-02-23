"""Shared verbose output rendering for CLI and daemon double-verbose mode.

Provides rich-panel renderers for structured payloads emitted by AskyClient.run_turn()
when double_verbose=True, and a factory that builds a verbose_output_callback from them.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    pass

VERBOSE_BORDER_STYLE_BY_ROLE = {
    "system": "blue",
    "user": "green",
    "assistant": "cyan",
    "tool": "magenta",
}


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


def print_main_model_request_payload(console: Console, payload: Dict[str, Any]) -> None:
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
        "Direction: Outbound Request",
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


def print_main_model_response_payload(
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


def print_preload_provenance(console: Console, payload: Dict[str, Any]) -> None:
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


def print_transport_metadata(console: Console, payload: Dict[str, Any]) -> None:
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


def build_verbose_output_callback(console: Console) -> Callable[[Any], None]:
    """Build a verbose_output_callback using the shared rich panel renderers.

    Routes structured payload dicts emitted by AskyClient.run_turn() in
    double-verbose mode to the appropriate rich panel printer. This is the
    same logic used by the CLI chat flow, but without any live-banner awareness.
    """
    main_model_traces: Dict[str, Dict[str, Any]] = {}

    def _trace_key(payload: Dict[str, Any]) -> str:
        turn = int(payload.get("turn", 0) or 0)
        phase = str(payload.get("phase", "main_loop"))
        return f"{turn}:{phase}"

    def callback(renderable: Any) -> None:
        if not isinstance(renderable, dict):
            console.print(renderable)
            return

        kind = str(renderable.get("kind", ""))
        source = str(renderable.get("source", "") or "")
        trace_key = _trace_key(renderable)

        if kind == "preload_provenance":
            print_preload_provenance(console, renderable)
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
                print_main_model_request_payload(console, request_for_print)
                trace_state["request_printed"] = True

            response_for_print = dict(renderable)
            response_transport = trace_state.get("transport_response")
            if isinstance(response_transport, dict):
                response_for_print["transport_response"] = response_transport
            response_errors = trace_state.get("transport_errors", [])
            if isinstance(response_errors, list):
                response_for_print["transport_errors"] = response_errors
            print_main_model_response_payload(console, response_for_print)
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
                        print_main_model_request_payload(console, request_for_print)
                        trace_state["request_printed"] = True
                elif kind == "transport_response":
                    trace_state["transport_response"] = renderable
                else:
                    trace_state.setdefault("transport_errors", []).append(renderable)
                return
            print_transport_metadata(console, renderable)
            return

        if kind == "tool_call" or "tool_name" in renderable:
            tool_name = str(renderable.get("tool_name", "unknown_tool"))
            call_index = int(renderable.get("call_index", 0) or 0)
            total_calls = int(renderable.get("total_calls", 0) or 0)
            turn = int(renderable.get("turn", 0) or 0)
            args_value = renderable.get("arguments", {})
            console.print(
                Panel(
                    _to_pretty_json(args_value),
                    title=f"Tool {call_index}/{total_calls} | Turn {turn} | {tool_name}",
                    border_style="cyan",
                    expand=False,
                )
            )

    return callback
