"""Shared math and constants for vector store operations."""

from __future__ import annotations

import math
import re
from typing import Any, List

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]{2,}")
DEFAULT_DENSE_WEIGHT = 0.75
CHUNK_FTS_TABLE_NAME = "content_chunks_fts"
HYBRID_LEXICAL_CANDIDATE_MULTIPLIER = 10
CHROMA_COLLECTION_SPACE = "cosine"
CHROMA_TO_SIMILARITY_BASE = 1.0


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def tokenize_text(text: str) -> set[str]:
    """Tokenize text into normalized lexical terms."""
    if not text:
        return set()
    return {token.lower() for token in TOKEN_PATTERN.findall(text)}


def lexical_overlap_score(query_tokens: set[str], text: str) -> float:
    """Compute simple lexical overlap ratio against query terms."""
    if not query_tokens:
        return 0.0
    chunk_tokens = tokenize_text(text)
    if not chunk_tokens:
        return 0.0
    return len(query_tokens & chunk_tokens) / len(query_tokens)


def distance_to_similarity(distance: Any) -> float:
    """Convert Chroma distance to a bounded similarity score."""
    try:
        score = CHROMA_TO_SIMILARITY_BASE - float(distance)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, score))


def first_query_result(items: Any) -> List[Any]:
    """Normalize Chroma query payload shape (nested list per query)."""
    if not isinstance(items, list):
        return []
    if items and isinstance(items[0], list):
        return items[0]
    return items
