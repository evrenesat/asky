"""Pre-retrieval query expansion for research pipeline."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Sequence

from asky.config import QUERY_EXPANSION_MAX_SUB_QUERIES
from asky.lazy_imports import call_attr

logger = logging.getLogger(__name__)

# Upper bound on generated sub-queries to keep search bounded.
MAX_SUB_QUERIES = QUERY_EXPANSION_MAX_SUB_QUERIES

# Minimum query length (chars) before expansion is attempted.
MIN_QUERY_LENGTH_FOR_EXPANSION = 30

_YAKE_MODULE: Optional[Any] = None
_YAKE_MODULE_LOADED = False


def _get_yake_module() -> Optional[Any]:
    """Import YAKE lazily on first use."""
    global _YAKE_MODULE, _YAKE_MODULE_LOADED
    if _YAKE_MODULE_LOADED:
        return _YAKE_MODULE

    try:
        import yake as yake_module  # type: ignore

        _YAKE_MODULE = yake_module
    except ImportError:
        _YAKE_MODULE = None
    _YAKE_MODULE_LOADED = True
    return _YAKE_MODULE


def expand_query_deterministic(query: str) -> List[str]:
    """Extract sub-queries using keyword extraction (YAKE).

    Returns a list of 1-4 query strings. Always includes the original query
    as the first element.
    """
    if not query or len(query) < MIN_QUERY_LENGTH_FOR_EXPANSION:
        return [query]

    yake_module = _get_yake_module()
    if yake_module is None:
        return [query]

    try:
        # Extract more keyphrases than we need sub-queries for grouping
        extractor = yake_module.KeywordExtractor(n=3, top=12)
        keywords = extractor.extract_keywords(query)
        phrases = [kw for kw, score in keywords if kw]

        if not phrases:
            return [query]

        # Simple grouping: take up to 3 phrases per sub-query
        # This forms 1-3 additional sub-queries
        sub_queries = [query]
        phrase_group_size = 3
        for i in range(0, len(phrases), phrase_group_size):
            group = phrases[i : i + phrase_group_size]
            sub_query = " ".join(group)
            if sub_query.lower() != query.lower():
                sub_queries.append(sub_query)

            if len(sub_queries) >= MAX_SUB_QUERIES:
                break

        return sub_queries[:MAX_SUB_QUERIES]
    except Exception as exc:
        logger.debug("Deterministic query expansion failed: %s", exc)
        return [query]


def expand_query_with_llm(
    query: str,
    llm_client: Any,
    model: str,
    max_sub_queries: int = MAX_SUB_QUERIES,
) -> List[str]:
    """Decompose query into sub-queries using a single LLM call.

    Uses structured prompt asking the model to output a JSON list of sub-questions.
    Falls back to deterministic expansion on failure.

    Returns a list of 1-4 query strings. Always includes the original query
    as the first element.
    """
    if not query or len(query) < MIN_QUERY_LENGTH_FOR_EXPANSION:
        return [query]

    prompt = (
        "Given this research question, generate 2-4 focused sub-questions that "
        "together cover the full scope. Output ONLY as a JSON array of strings "
        "containing the sub-questions. Do not include the original question in the list. "
        f"Limit to maximum {max_sub_queries - 1} sub-questions.\n"
        f"Question: {query}"
    )

    try:
        # Using a very small max_tokens since we only need a few strings
        # and capping at ~500 context tokens as per spec.
        response = llm_client.get_completion(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            max_tokens=200,
        )

        content = response.get("content", "").strip()
        # Basic JSON extraction in case the model adds chatter
        if "[" in content and "]" in content:
            content = content[content.find("[") : content.rfind("]") + 1]

        sub_questions = json.loads(content)
        if isinstance(sub_questions, list):
            # Clean up and include original
            results = [query]
            for q in sub_questions:
                if isinstance(q, str) and q.strip():
                    results.append(q.strip())
                if len(results) >= max_sub_queries:
                    break
            return results

    except Exception as exc:
        logger.debug("LLM query expansion failed, falling back: %s", exc)

    return expand_query_deterministic(query)
