"""History/context selector orchestration for API callers."""

from __future__ import annotations

import re
from typing import Callable, List

from asky.storage import get_history, get_interaction_context

from .types import ContextResolution

HISTORY_SELECTOR_PATTERN = re.compile(r"__hid_(\d+)$")


def parse_history_selector_token(token: str) -> int | None:
    """Parse direct IDs or completion-style history tokens."""
    cleaned = token.strip()
    if not cleaned:
        return None
    if cleaned.isdigit():
        return int(cleaned)

    match = HISTORY_SELECTOR_PATTERN.search(cleaned)
    if match:
        return int(match.group(1))
    return None


def _extract_interaction_id(row: object) -> int:
    row_id = getattr(row, "id", None)
    if isinstance(row_id, int):
        return row_id
    if isinstance(row, (tuple, list)) and row:
        return int(row[0])
    raise ValueError("History row does not contain an interaction ID")


def load_context_from_history(
    continue_ids: str,
    summarize: bool,
    *,
    get_history_fn: Callable[..., List[object]] = get_history,
    get_interaction_context_fn: Callable[..., str] = get_interaction_context,
) -> ContextResolution:
    """Resolve context selectors and fetch the context text."""
    raw_ids = [token.strip() for token in continue_ids.split(",")]
    resolved_ids: List[int] = []
    relative_indices: List[int] = []

    for raw_id in raw_ids:
        if raw_id.startswith("~"):
            try:
                rel_val = int(raw_id[1:])
            except ValueError as exc:
                raise ValueError(f"Invalid relative ID format: {raw_id}") from exc
            if rel_val < 1:
                raise ValueError(f"Relative ID must be >= 1 (got {raw_id})")
            relative_indices.append(rel_val)
            continue

        parsed_id = parse_history_selector_token(raw_id)
        if parsed_id is None:
            raise ValueError(
                "Invalid continue IDs format. Use comma-separated IDs, "
                "completion selector tokens, or ~N for relative."
            )
        resolved_ids.append(parsed_id)

    if relative_indices:
        max_depth = max(relative_indices)
        history_rows = get_history_fn(limit=max_depth)
        for rel_val in relative_indices:
            list_index = rel_val - 1
            if list_index >= len(history_rows):
                raise ValueError(
                    f"Relative ID {rel_val} is out of range "
                    f"(only {len(history_rows)} records available)."
                )
            resolved_ids.append(_extract_interaction_id(history_rows[list_index]))

    deduped_ids = sorted(set(resolved_ids))
    context_str = get_interaction_context_fn(deduped_ids, full=not summarize)
    return ContextResolution(
        context_str=context_str or "",
        resolved_ids=deduped_ids,
    )
