"""Summarization logic and helpers for the LLM."""

import logging
from typing import Any, Dict, Optional

from asky.config import (
    ANSWER_SUMMARY_MAX_CHARS,
    CONTINUE_QUERY_THRESHOLD,
    MODELS,
    QUERY_SUMMARY_MAX_CHARS,
    SUMMARIZATION_INPUT_LIMIT,
    SUMMARIZATION_MODEL,
    SUMMARIZE_ANSWER_PROMPT_TEMPLATE,
    SUMMARIZE_QUERY_PROMPT_TEMPLATE,
)
from asky.html import strip_think_tags
from asky.core import get_llm_msg, UsageTracker

logger = logging.getLogger(__name__)


def _summarize_content(
    content: str,
    prompt_template: str,
    max_output_chars: int,
    get_llm_msg_func: Optional[Any] = None,  # Keep for backward compat for now
    usage_tracker: Optional[UsageTracker] = None,
) -> str:
    """Helper function to summarize content using the summarization model.
    requires get_llm_msg_func to avoid circular imports.
    """
    try:
        msgs = [
            {
                "role": "system",
                "content": prompt_template,
            },
            {"role": "user", "content": content[:SUMMARIZATION_INPUT_LIMIT]},
        ]
        model_id = MODELS[SUMMARIZATION_MODEL]["id"]
        model_alias = MODELS[SUMMARIZATION_MODEL].get("alias", SUMMARIZATION_MODEL)
        llm_func = get_llm_msg_func or get_llm_msg
        msg = llm_func(
            model_id,
            msgs,
            use_tools=False,
            model_alias=model_alias,
            usage_tracker=usage_tracker,
        )
        summary = strip_think_tags(msg.get("content", "")).strip()

        if len(summary) > max_output_chars:
            summary = summary[: max_output_chars - 3] + "..."

        return summary
    except Exception as e:
        logger.error(f"Error during summarization: {e}")
        return content[:max_output_chars]


def generate_summaries(
    query: str,
    answer: str,
    get_llm_msg_func: Any,
    usage_tracker: Optional[Any] = None,
) -> tuple[str, str]:
    """Generate summaries for query and answer using the summarization model."""
    query_summary = ""
    answer_summary = ""
    logger.debug(f"Query: {query}")
    logger.debug(f"Answer: {answer}")

    # Generate Query Summary (if needed)
    # Generate Query Summary (if needed)
    if len(query) > QUERY_SUMMARY_MAX_CHARS:
        query_summary = _summarize_content(
            content=query,
            prompt_template=SUMMARIZE_QUERY_PROMPT_TEMPLATE,
            max_output_chars=QUERY_SUMMARY_MAX_CHARS,
            get_llm_msg_func=get_llm_msg_func,
            usage_tracker=usage_tracker,
        )
        logger.debug(f"Query Summary: {query_summary}")
    else:
        query_summary = query

    # Generate Answer Summary
    if len(answer) > ANSWER_SUMMARY_MAX_CHARS:
        answer_summary = _summarize_content(
            content=answer,
            prompt_template=SUMMARIZE_ANSWER_PROMPT_TEMPLATE,
            max_output_chars=ANSWER_SUMMARY_MAX_CHARS,
            get_llm_msg_func=get_llm_msg_func,
            usage_tracker=usage_tracker,
        )
    else:
        answer_summary = answer
    logger.debug(f"Answer Summary: {answer_summary}")

    return query_summary, answer_summary
