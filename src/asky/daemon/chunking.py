"""Outbound response chunking helpers for daemon transports."""

from __future__ import annotations

from typing import List

MIN_CHUNK_SIZE = 64


def chunk_text(text: str, max_chars: int) -> List[str]:
    """Split long text into ordered chunks capped by max_chars."""
    content = str(text or "")
    if not content:
        return [""]

    limit = max(int(max_chars), MIN_CHUNK_SIZE)
    if len(content) <= limit:
        return [content]

    chunks: List[str] = []
    start = 0
    while start < len(content):
        end = min(start + limit, len(content))
        if end < len(content):
            split_at = content.rfind("\n", start, end)
            if split_at > start:
                end = split_at + 1
        chunk = content[start:end]
        if not chunk:
            break
        chunks.append(chunk)
        start = end

    return chunks or [content]
