"""Summarization logic and helpers for the LLM."""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional

from asky.config import (
    ANSWER_SUMMARY_MAX_CHARS,
    MODELS,
    QUERY_SUMMARY_MAX_CHARS,
    SUMMARIZATION_INPUT_LIMIT,
    SUMMARIZATION_MODEL,
    SUMMARIZE_ANSWER_PROMPT_TEMPLATE,
    SUMMARIZE_QUERY_PROMPT_TEMPLATE,
)
from asky.core import UsageTracker, get_llm_msg
from asky.html import strip_think_tags

logger = logging.getLogger(__name__)

# Long inputs are summarized hierarchically to improve small-model quality.
# Long inputs are summarized hierarchically to improve small-model quality.
HIERARCHICAL_TRIGGER_CHARS = (
    3200  # Minimum content length to trigger hierarchical strategy
)
HIERARCHICAL_MAX_INPUT_CHARS = (
    32000  # Hard cap on input length; content beyond this is truncated
)
HIERARCHICAL_CHUNK_TARGET_CHARS = (
    2800  # Target size for semantic chunks in splitting phase
)
HIERARCHICAL_CHUNK_OVERLAP_CHARS = (
    220  # Overlap between chunks to preserve context at boundaries
)
HIERARCHICAL_MAX_CHUNKS = (
    12  # Maximum number of map-stage calls (merges groups if exceeded)
)
HIERARCHICAL_MAP_MAX_OUTPUT_CHARS = (
    750  # Max chars for initial chunk summaries (bullets focus)
)
HIERARCHICAL_MERGE_MAX_OUTPUT_CHARS = 950  # Max chars for intermediate merge outputs
HIERARCHICAL_MAX_REDUCTION_ROUNDS = 8  # Safety limit for recursive reduction depth

PARAGRAPH_SPLIT_PATTERN = re.compile(r"\n\s*\n+")
SummarizationProgressCallback = Callable[[Dict[str, Any]], None]
SummarizationStatusCallback = Callable[[Optional[str]], None]

MAP_STAGE_PROMPT_TEMPLATE = """You are summarizing section {index} of {total} from a larger document.

Focus requirement:
{focus_requirement}

Extract concise bullet points and preserve:
- Key facts, claims, numbers, dates, and names
- Critical caveats or limitations
- Causal or comparative statements

Output only bullet points."""

MERGE_STAGE_PROMPT_TEMPLATE = """Merge the partial summaries below into one coherent draft summary.

Focus requirement:
{focus_requirement}

Rules:
- Keep concrete facts (numbers, dates, names)
- Remove duplicates and contradictions
- Keep important caveats
- Prefer precise wording over broad generalization

Output only the merged summary."""


def _summarize_single_pass(
    content: str,
    prompt_template: str,
    max_output_chars: int,
    llm_func: Any,
    usage_tracker: Optional[UsageTracker],
    stage: str,
    call_index: int,
    call_total: int,
    hierarchical: bool,
    status_callback: Optional[SummarizationStatusCallback],
    progress_callback: Optional[SummarizationProgressCallback],
) -> str:
    """Execute a single summarization call against the configured model."""
    truncated_content = content[:SUMMARIZATION_INPUT_LIMIT]
    input_chars = len(truncated_content)
    started = time.perf_counter()
    if status_callback:
        status_callback(
            f"Summarizer: {stage} {call_index}/{call_total} (input {input_chars:,} chars)"
        )

    msgs = [
        {"role": "system", "content": prompt_template},
        {"role": "user", "content": truncated_content},
    ]
    model_id = MODELS[SUMMARIZATION_MODEL]["id"]
    model_alias = MODELS[SUMMARIZATION_MODEL].get("alias", SUMMARIZATION_MODEL)
    msg = llm_func(
        model_id,
        msgs,
        use_tools=False,
        model_alias=model_alias,
        usage_tracker=usage_tracker,
        status_callback=None,
    )
    summary = strip_think_tags(msg.get("content", "")).strip()
    output = _truncate_text(summary, max_output_chars)
    elapsed_ms = (time.perf_counter() - started) * 1000

    _emit_progress(
        progress_callback=progress_callback,
        payload={
            "stage": stage,
            "call_index": call_index,
            "call_total": call_total,
            "hierarchical": hierarchical,
            "input_chars": input_chars,
            "output_chars": len(output),
            "elapsed_ms": elapsed_ms,
        },
    )
    if status_callback:
        status_callback(
            f"Summarizer: {stage} {call_index}/{call_total} "
            f"(input {input_chars:,}, output {len(output):,}, {elapsed_ms:.0f}ms)"
        )
    return output


def _summarize_content(
    content: str,
    prompt_template: str,
    max_output_chars: int,
    get_llm_msg_func: Optional[Any] = None,  # Keep for backward compatibility.
    usage_tracker: Optional[UsageTracker] = None,
    status_callback: Optional[SummarizationStatusCallback] = None,
    progress_callback: Optional[SummarizationProgressCallback] = None,
) -> str:
    """Summarize content with hierarchical fallback for long documents."""
    if not content:
        return ""

    llm_func = get_llm_msg_func or get_llm_msg
    started = time.perf_counter()

    try:
        content_for_summary = content[:HIERARCHICAL_MAX_INPUT_CHARS]
        if len(content_for_summary) < HIERARCHICAL_TRIGGER_CHARS:
            return _summarize_single_pass(
                content=content_for_summary,
                prompt_template=prompt_template,
                max_output_chars=max_output_chars,
                llm_func=llm_func,
                usage_tracker=usage_tracker,
                stage="single",
                call_index=1,
                call_total=1,
                hierarchical=False,
                status_callback=status_callback,
                progress_callback=progress_callback,
            )

        chunks = _semantic_chunk_text(
            content_for_summary,
            target_chars=HIERARCHICAL_CHUNK_TARGET_CHARS,
            overlap_chars=HIERARCHICAL_CHUNK_OVERLAP_CHARS,
            max_chunks=HIERARCHICAL_MAX_CHUNKS,
        )
        if len(chunks) <= 1:
            return _summarize_single_pass(
                content=content_for_summary,
                prompt_template=prompt_template,
                max_output_chars=max_output_chars,
                llm_func=llm_func,
                usage_tracker=usage_tracker,
                stage="single",
                call_index=1,
                call_total=1,
                hierarchical=False,
                status_callback=status_callback,
                progress_callback=progress_callback,
            )

        logger.debug(
            "summarization hierarchical start input_len=%d chunks=%d target_chunk=%d",
            len(content_for_summary),
            len(chunks),
            HIERARCHICAL_CHUNK_TARGET_CHARS,
        )

        map_summaries: List[str] = []
        total_calls = len(chunks) + _estimate_merge_calls(len(chunks)) + 1
        call_index = 0
        for index, chunk in enumerate(chunks, start=1):
            map_prompt = MAP_STAGE_PROMPT_TEMPLATE.format(
                index=index,
                total=len(chunks),
                focus_requirement=prompt_template,
            )
            call_index += 1
            map_summary = _summarize_single_pass(
                content=chunk,
                prompt_template=map_prompt,
                max_output_chars=HIERARCHICAL_MAP_MAX_OUTPUT_CHARS,
                llm_func=llm_func,
                usage_tracker=usage_tracker,
                stage=f"map[{index}/{len(chunks)}]",
                call_index=call_index,
                call_total=total_calls,
                hierarchical=True,
                status_callback=status_callback,
                progress_callback=progress_callback,
            )
            map_summaries.append(map_summary)

        merged_summaries = map_summaries
        reduction_round = 0
        while (
            len(merged_summaries) > 1
            and reduction_round < HIERARCHICAL_MAX_REDUCTION_ROUNDS
        ):
            reduction_round += 1
            next_round: List[str] = []
            for pair_start in range(0, len(merged_summaries), 2):
                pair = merged_summaries[pair_start : pair_start + 2]
                if len(pair) == 1:
                    next_round.append(pair[0])
                    continue

                merge_prompt = MERGE_STAGE_PROMPT_TEMPLATE.format(
                    focus_requirement=prompt_template,
                )
                pair_input = (
                    "Partial summary A:\n"
                    + pair[0]
                    + "\n\nPartial summary B:\n"
                    + pair[1]
                )
                call_index += 1
                merged = _summarize_single_pass(
                    content=pair_input,
                    prompt_template=merge_prompt,
                    max_output_chars=HIERARCHICAL_MERGE_MAX_OUTPUT_CHARS,
                    llm_func=llm_func,
                    usage_tracker=usage_tracker,
                    stage=f"merge[r{reduction_round}]",
                    call_index=call_index,
                    call_total=total_calls,
                    hierarchical=True,
                    status_callback=status_callback,
                    progress_callback=progress_callback,
                )
                next_round.append(merged)
            merged_summaries = next_round

        final_input = merged_summaries[0] if merged_summaries else ""
        call_index += 1
        final_summary = _summarize_single_pass(
            content=final_input,
            prompt_template=prompt_template,
            max_output_chars=max_output_chars,
            llm_func=llm_func,
            usage_tracker=usage_tracker,
            stage="final",
            call_index=call_index,
            call_total=total_calls,
            hierarchical=True,
            status_callback=status_callback,
            progress_callback=progress_callback,
        )

        logger.debug(
            "summarization hierarchical complete chunks=%d rounds=%d elapsed=%.2fms",
            len(chunks),
            reduction_round,
            (time.perf_counter() - started) * 1000,
        )
        return final_summary
    except Exception as e:
        logger.error("Error during summarization: %s", e)
        return _truncate_text(content, max_output_chars)


def _semantic_chunk_text(
    text: str,
    target_chars: int,
    overlap_chars: int,
    max_chunks: int,
) -> List[str]:
    """Chunk text on paragraph boundaries, with overlap for context continuity."""
    paragraphs = [
        part.strip()
        for part in PARAGRAPH_SPLIT_PATTERN.split(text)
        if part and part.strip()
    ]
    if not paragraphs:
        normalized = text.strip()
        return [normalized] if normalized else []

    base_chunks: List[str] = []
    current_parts: List[str] = []
    current_size = 0

    for paragraph in paragraphs:
        paragraph_size = len(paragraph)
        separator_size = 2 if current_parts else 0
        next_size = current_size + separator_size + paragraph_size
        if current_parts and next_size > target_chars:
            base_chunks.append("\n\n".join(current_parts))
            current_parts = [paragraph]
            current_size = paragraph_size
        else:
            current_parts.append(paragraph)
            current_size = next_size

    if current_parts:
        base_chunks.append("\n\n".join(current_parts))

    if len(base_chunks) > max_chunks:
        base_chunks = _merge_chunk_groups(base_chunks, max_chunks)

    overlapped_chunks: List[str] = []
    previous_tail = ""
    for chunk in base_chunks:
        if previous_tail:
            overlapped_chunks.append(f"{previous_tail}\n\n{chunk}")
        else:
            overlapped_chunks.append(chunk)
        previous_tail = chunk[-overlap_chars:] if overlap_chars > 0 else ""

    return overlapped_chunks


def _merge_chunk_groups(chunks: List[str], max_chunks: int) -> List[str]:
    """Merge chunk groups to respect a hard upper bound on map calls."""
    if len(chunks) <= max_chunks:
        return chunks

    merged: List[str] = []
    group_size = max(1, (len(chunks) + max_chunks - 1) // max_chunks)
    for start in range(0, len(chunks), group_size):
        merged.append("\n\n".join(chunks[start : start + group_size]))
    return merged[:max_chunks]


def _truncate_text(text: str, max_output_chars: int) -> str:
    """Clamp summary text to configured output size."""
    if len(text) <= max_output_chars:
        return text
    return text[: max_output_chars - 3] + "..."


def _estimate_merge_calls(chunk_count: int) -> int:
    """Estimate number of pairwise merge calls needed for map-reduce reduction."""
    merges = 0
    current = chunk_count
    while current > 1:
        merges += current // 2
        current = (current + 1) // 2
    return merges


def _emit_progress(
    progress_callback: Optional[SummarizationProgressCallback],
    payload: Dict[str, Any],
) -> None:
    """Emit summarization progress events without interrupting summarization flow."""
    if not progress_callback:
        return
    try:
        progress_callback(payload)
    except Exception:
        logger.debug("summarization progress callback failed")


def generate_summaries(
    query: str,
    answer: str,
    get_llm_msg_func: Any,
    usage_tracker: Optional[Any] = None,
) -> tuple[str, str]:
    """Generate summaries for query and answer using the summarization model."""
    query_summary = ""
    answer_summary = ""
    logger.debug("Query: %s", query)
    logger.debug("Answer length: %d", len(answer))

    if len(query) > QUERY_SUMMARY_MAX_CHARS:
        query_summary = _summarize_content(
            content=query,
            prompt_template=SUMMARIZE_QUERY_PROMPT_TEMPLATE,
            max_output_chars=QUERY_SUMMARY_MAX_CHARS,
            get_llm_msg_func=get_llm_msg_func,
            usage_tracker=usage_tracker,
        )
        logger.debug("Query Summary: %s", query_summary)
    else:
        query_summary = query

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
    logger.debug("Answer Summary length: %d", len(answer_summary))

    return query_summary, answer_summary
