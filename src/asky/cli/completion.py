"""Argcomplete wiring and completion providers for asky CLI."""

from __future__ import annotations

import argparse
import logging
import os
import re
import sqlite3
from functools import lru_cache
from typing import Iterable, List, Mapping

HISTORY_HINT_LIMIT = 30
SESSION_HINT_LIMIT = 50
COMPLETION_SHELLS = ("bash", "zsh")
HISTORY_HINT_PREVIEW_CHARS = 72
SESSION_HINT_PREVIEW_CHARS = 72
ANSWER_SELECTOR_ID_MARKER = "__id_"
ANSWER_SELECTOR_SLUG_WORD_LIMIT = 6
HISTORY_SELECTOR_ID_MARKER = "__hid_"
HISTORY_SELECTOR_SLUG_WORD_LIMIT = 6
SESSION_SELECTOR_ID_MARKER = "__sid_"
SESSION_SELECTOR_SLUG_WORD_LIMIT = 6

logger = logging.getLogger(__name__)


def enable_argcomplete(parser: argparse.ArgumentParser) -> None:
    """Enable argcomplete only for completion invocations."""
    if "_ARGCOMPLETE" not in os.environ:
        return
    try:
        import argcomplete  # type: ignore

        argcomplete.autocomplete(parser)
    except Exception as exc:
        logger.debug("argcomplete autocomplete setup skipped: %s", exc)


def build_completion_script(shell: str) -> str:
    """Return shell snippet for enabling asky completion."""
    if shell not in COMPLETION_SHELLS:
        raise ValueError(
            f"Unsupported shell '{shell}'. Supported values: {', '.join(COMPLETION_SHELLS)}"
        )

    import argcomplete  # type: ignore

    header = "\n".join(
        [
            "# asky argcomplete setup",
            "# Append this to your shell rc file.",
        ]
    )
    shell_code = argcomplete.shellcode(["asky", "ask"], shell=shell)
    return f"{header}\n{shell_code}"


def complete_model_aliases(
    prefix: str, parsed_args: argparse.Namespace, **kwargs: object
) -> List[str]:
    """Complete model alias values."""
    del parsed_args, kwargs
    return _prefix_filter(_get_model_aliases(), prefix)


def complete_history_ids(
    prefix: str, parsed_args: argparse.Namespace, **kwargs: object
) -> Mapping[str, str]:
    """Complete comma-separated history IDs."""
    del parsed_args, kwargs
    return _complete_csv_values(prefix, _get_recent_history_hints())


def complete_answer_ids(
    prefix: str, parsed_args: argparse.Namespace, **kwargs: object
) -> Mapping[str, str]:
    """Complete assistant-only history IDs for --print-answer."""
    del parsed_args, kwargs
    return _complete_csv_values(prefix, _get_recent_answer_hints())


def complete_single_history_id(
    prefix: str, parsed_args: argparse.Namespace, **kwargs: object
) -> Mapping[str, str]:
    """Complete a single history ID."""
    del parsed_args, kwargs
    return _prefix_filter_with_descriptions(_get_recent_history_hints(), prefix)


def complete_single_answer_id(
    prefix: str, parsed_args: argparse.Namespace, **kwargs: object
) -> Mapping[str, str]:
    """Complete a single assistant-only history ID."""
    del parsed_args, kwargs
    return _prefix_filter_with_descriptions(_get_recent_answer_hints(), prefix)


def parse_answer_selector_token(token: str) -> int | None:
    """Parse answer selector token and extract assistant message ID."""
    cleaned = token.strip()
    if not cleaned:
        return None
    if cleaned.isdigit():
        return int(cleaned)

    match = re.search(rf"{re.escape(ANSWER_SELECTOR_ID_MARKER)}(\d+)$", cleaned)
    if match:
        return int(match.group(1))
    return None


def parse_history_selector_token(token: str) -> int | None:
    """Parse history selector token and extract interaction ID."""
    cleaned = token.strip()
    if not cleaned:
        return None
    if cleaned.isdigit():
        return int(cleaned)

    match = re.search(rf"{re.escape(HISTORY_SELECTOR_ID_MARKER)}(\d+)$", cleaned)
    if match:
        return int(match.group(1))
    return None


def parse_session_selector_token(token: str) -> int | None:
    """Parse session selector token and extract session ID."""
    cleaned = token.strip()
    if not cleaned:
        return None
    if cleaned.isdigit():
        return int(cleaned)

    match = re.search(rf"{re.escape(SESSION_SELECTOR_ID_MARKER)}(\d+)$", cleaned)
    if match:
        return int(match.group(1))
    return None


def complete_session_tokens(
    prefix: str, parsed_args: argparse.Namespace, **kwargs: object
) -> Mapping[str, str]:
    """Complete session identifiers and session names."""
    del parsed_args, kwargs
    return _prefix_filter_with_descriptions(
        _get_recent_session_hints(),
        prefix,
        case_sensitive=False,
    )


def _complete_csv_values(
    prefix: str,
    candidates: Mapping[str, str],
) -> Mapping[str, str]:
    """Complete values in a comma-separated token list."""
    if "," not in prefix:
        return _prefix_filter_with_descriptions(candidates, prefix)

    tokens = [token.strip() for token in prefix.split(",")]
    selected_tokens = [token for token in tokens[:-1] if token]
    selected_ids = {
        parsed
        for parsed in (parse_answer_selector_token(token) for token in selected_tokens)
        if parsed is not None
    }
    current_token = tokens[-1]
    available = {}
    for item, description in candidates.items():
        if item in selected_tokens:
            continue
        item_id = parse_answer_selector_token(item)
        if item_id is not None and item_id in selected_ids:
            continue
        available[item] = description
    matches = _prefix_filter_with_descriptions(available, current_token)
    selected_prefix = ",".join(selected_tokens)
    if not selected_prefix:
        return matches

    return {
        f"{selected_prefix},{match}": description
        for match, description in matches.items()
    }


def _prefix_filter(
    values: Iterable[str],
    prefix: str,
    *,
    case_sensitive: bool = True,
) -> List[str]:
    """Filter values by prefix."""
    unique_values = list(dict.fromkeys(values))
    if not prefix:
        return unique_values

    if case_sensitive:
        return [value for value in unique_values if value.startswith(prefix)]

    lowered_prefix = prefix.lower()
    return [
        value for value in unique_values if value.lower().startswith(lowered_prefix)
    ]


def _prefix_filter_with_descriptions(
    values: Mapping[str, str],
    prefix: str,
    *,
    case_sensitive: bool = True,
) -> Mapping[str, str]:
    """Filter completion mapping by token prefix."""
    if not prefix:
        return dict(values)

    if case_sensitive:
        return {
            token: description
            for token, description in values.items()
            if token.startswith(prefix)
        }

    lowered_prefix = prefix.lower()
    return {
        token: description
        for token, description in values.items()
        if token.lower().startswith(lowered_prefix)
    }


def _truncate_preview(text: str, limit: int) -> str:
    """Truncate preview text to keep completion hints compact."""
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _build_answer_selector_token(message_id: int, preview: str) -> str:
    """Create a completion token that is searchable by words and decodes to ID."""
    slug = re.sub(r"[^a-z0-9]+", "_", preview.lower()).strip("_")
    if slug:
        words = [word for word in slug.split("_") if word]
        slug = "_".join(words[:ANSWER_SELECTOR_SLUG_WORD_LIMIT]).strip("_")
    if not slug:
        return str(message_id)
    return f"{slug}{ANSWER_SELECTOR_ID_MARKER}{message_id}"


def _build_history_selector_token(interaction_id: int, preview: str) -> str:
    """Create a unique history completion token searchable by query words."""
    slug = re.sub(r"[^a-z0-9]+", "_", preview.lower()).strip("_")
    if slug:
        words = [word for word in slug.split("_") if word]
        slug = "_".join(words[:HISTORY_SELECTOR_SLUG_WORD_LIMIT]).strip("_")
    if not slug:
        return str(interaction_id)
    return f"{slug}{HISTORY_SELECTOR_ID_MARKER}{interaction_id}"


def _build_session_selector_token(session_id: int, session_name: str) -> str:
    """Create a unique session completion token searchable by session words."""
    slug = re.sub(r"[^a-z0-9]+", "_", session_name.lower()).strip("_")
    if slug:
        words = [word for word in slug.split("_") if word]
        slug = "_".join(words[:SESSION_SELECTOR_SLUG_WORD_LIMIT]).strip("_")
    if not slug:
        return str(session_id)
    return f"{slug}{SESSION_SELECTOR_ID_MARKER}{session_id}"


@lru_cache(maxsize=1)
def _get_model_aliases() -> List[str]:
    """Return model aliases from shared model listing helper."""
    try:
        from asky.cli.models import list_model_aliases

        return list_model_aliases()
    except Exception as exc:
        logger.debug("Failed to load model aliases for completion: %s", exc)
        return []


def _history_preview(row: object) -> str:
    """Build one-line preview text for a history interaction."""
    summary = getattr(row, "summary", None) or ""
    query = getattr(row, "query", None) or ""
    answer = getattr(row, "answer", None) or ""
    if summary:
        return _truncate_preview(summary, HISTORY_HINT_PREVIEW_CHARS)
    if query:
        return _truncate_preview(query, HISTORY_HINT_PREVIEW_CHARS)
    if answer:
        return _truncate_preview(answer, HISTORY_HINT_PREVIEW_CHARS)
    return "(no preview)"


def _answer_preview(summary: str, content: str) -> str:
    """Build one-line preview text for an assistant answer message."""
    if summary:
        return _truncate_preview(summary, HISTORY_HINT_PREVIEW_CHARS)
    if content:
        return _truncate_preview(content, HISTORY_HINT_PREVIEW_CHARS)
    return "(no answer preview)"


@lru_cache(maxsize=1)
def _get_recent_history_hints() -> Mapping[str, str]:
    """Return recent history IDs with preview descriptions."""
    try:
        from asky.storage.sqlite import SQLiteHistoryRepository

        repo = SQLiteHistoryRepository()
        rows = repo.get_history(HISTORY_HINT_LIMIT)
        hints = {}
        for row in rows:
            if row.id is None:
                continue
            preview = _history_preview(row)
            token = _build_history_selector_token(int(row.id), preview)
            hints[token] = f"message #{row.id} | {preview}"
        return hints
    except Exception as exc:
        logger.debug("Failed to load history IDs for completion: %s", exc)
        return {}


@lru_cache(maxsize=1)
def _get_recent_answer_hints() -> Mapping[str, str]:
    """Return assistant message IDs with answer previews for completion."""
    try:
        from asky.storage.sqlite import SQLiteHistoryRepository

        repo = SQLiteHistoryRepository()
        repo.init_db()
        conn = repo._get_conn()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, content, summary
            FROM messages
            WHERE session_id IS NULL AND role = 'assistant'
            ORDER BY timestamp DESC, id DESC
            LIMIT ?
            """,
            (HISTORY_HINT_LIMIT,),
        )
        rows = cursor.fetchall()
        conn.close()
    except Exception as exc:
        logger.debug("Failed to load answer IDs for completion: %s", exc)
        return {}

    hints = {}
    for row in rows:
        message_id = int(row["id"])
        preview = _answer_preview(row["summary"] or "", row["content"] or "")
        hints[str(message_id)] = preview
        selector_token = _build_answer_selector_token(message_id, preview)
        hints[selector_token] = preview
    return hints


@lru_cache(maxsize=1)
def _get_recent_session_hints() -> Mapping[str, str]:
    """Return session tokens with descriptions for completion."""
    try:
        from asky.storage.sqlite import SQLiteHistoryRepository

        repo = SQLiteHistoryRepository()
        sessions = repo.list_sessions(SESSION_HINT_LIMIT)
    except Exception as exc:
        logger.debug("Failed to load session completion candidates: %s", exc)
        return {}

    hints = {}
    for session in sessions:
        session_name = session.name or "(unnamed)"
        created = (session.created_at or "")[:16].replace("T", " ")
        session_label = _truncate_preview(session_name, SESSION_HINT_PREVIEW_CHARS)
        if created:
            session_label = f"{session_label} | {created}"

        session_token = _build_session_selector_token(session.id, session_name)
        hints[session_token] = f"session #{session.id} | {session_label}"
    return hints
