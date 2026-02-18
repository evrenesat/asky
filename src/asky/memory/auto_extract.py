"""Session-scoped automatic memory extraction from conversation turns."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List

from asky.html import strip_think_tags

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = (
    "You are a memory extraction assistant. Given a user query and an assistant reply, "
    "identify any persistent facts, preferences, or personal information about the user "
    "that are worth remembering for future conversations. "
    "Return ONLY a JSON array of concise fact strings. "
    "If there are no persistent facts to extract, return an empty array: []. "
    "Do not include ephemeral task details, only long-term user attributes.\n\n"
    "Examples of facts to extract:\n"
    '- "User prefers Python over JavaScript"\n'
    '- "User\'s name is Alice"\n'
    '- "User works at Acme Corp"\n\n'
    "Examples of things NOT to extract:\n"
    "- Specific code snippets requested in this session\n"
    "- Temporary instructions like 'explain it briefly'\n"
    "- Questions about external topics unrelated to the user"
)


def extract_and_save_memories_from_turn(
    query: str,
    answer: str,
    llm_client: Callable[..., Dict[str, Any]],
    model: str,
    db_path: Path,
    chroma_dir: Path,
) -> List[int]:
    """Extract persistent user facts from a conversation turn and save them to memory.

    Calls the LLM to identify facts, then delegates to execute_save_memory for
    deduplication and storage.

    Returns a list of saved/updated memory IDs (may be empty).
    """
    from asky.memory.tools import execute_save_memory

    messages = [
        {"role": "system", "content": EXTRACTION_PROMPT},
        {
            "role": "user",
            "content": f"User query: {query}\n\nAssistant reply: {answer}",
        },
    ]

    try:
        response = llm_client(model, messages, use_tools=False)
    except Exception as exc:
        logger.error("Auto-extraction LLM call failed: %s", exc)
        return []

    raw_content = strip_think_tags(response.get("content", "")).strip()
    if not raw_content:
        return []

    try:
        facts = json.loads(raw_content)
    except json.JSONDecodeError:
        # Try to find a JSON array in the response
        start = raw_content.find("[")
        end = raw_content.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                facts = json.loads(raw_content[start : end + 1])
            except json.JSONDecodeError:
                logger.debug("Auto-extraction: could not parse JSON from response")
                return []
        else:
            logger.debug("Auto-extraction: no JSON array found in response")
            return []

    if not isinstance(facts, list):
        return []

    saved_ids: List[int] = []
    for fact in facts:
        if not isinstance(fact, str) or not fact.strip():
            continue
        result = execute_save_memory({"memory": fact.strip()})
        if result.get("status") in ("saved", "updated"):
            mid = result.get("memory_id")
            if mid is not None:
                saved_ids.append(int(mid))

    return saved_ids
