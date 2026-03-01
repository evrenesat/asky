"""Prompt construction and parsing utilities."""

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional


def is_markdown(text: str) -> bool:
    """Check if the text likely contains markdown formatting."""
    # Basic detection: common markdown patterns
    patterns = [
        r"^#+\s",  # Headers
        r"\*\*.*\*\*",  # Bold
        r"__.*__",  # Bold
        r"\*.*\* ",  # Italic
        r"_.*_",  # Italic
        r"\[.*\]\(.*\)",  # Links
        r"```",  # Code blocks
        r"^\s*[-*+]\s",  # Lists
        r"^\s*\d+\.\s",  # Numbered lists
    ]
    return any(re.search(p, text, re.M) for p in patterns)


def parse_textual_tool_call(text: str) -> Optional[Dict[str, Any]]:
    """Parse tool calls from textual format (fallback for some models)."""
    if not text:
        return None
    m = re.search(r"to=functions\.([a-zA-Z0-9_]+)", text)
    if not m:
        return None
    name = m.group(1)
    j = re.search(r"(\{.*\})", text, re.S)
    if not j:
        return None
    try:
        json.loads(j.group(1))
        return {"name": name, "arguments": j.group(1)}
    except Exception:
        return None


def parse_xml_tool_calls(text: str) -> List[Dict[str, Any]]:
    """Parse tool calls from XML-like format used by some models.

    Format: <tool_call> <function=name> <parameter=key> value </tool_call>
    """
    if not text:
        return []

    calls = []
    # Pattern to find tool_call blocks
    tc_pattern = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)
    # Pattern to find function name
    func_pattern = re.compile(r"<function=([a-zA-Z0-9_]+)>")

    for match in tc_pattern.finditer(text):
        content = match.group(1).strip()

        func_match = func_pattern.search(content)
        if not func_match:
            continue

        function_name = func_match.group(1)
        params = {}

        # Remove the function part to process parameters
        remaining = content[func_match.end() :].strip()

        # Split by <parameter= taking advantage of capture group in split
        parts = re.split(r"(<parameter=[^>]+>)", remaining)

        current_param = None
        for part in parts:
            if not part.strip():
                continue

            p_match = re.match(r"<parameter=([^>]+)>", part)
            if p_match:
                current_param = p_match.group(1)
            elif current_param:
                # This part is the value for current_param
                params[current_param] = part.strip()
                current_param = None

        calls.append(
            {
                "id": f"xml_call_{len(calls)}",
                "type": "function",
                "function": {"name": function_name, "arguments": json.dumps(params)},
            }
        )

    return calls


def extract_calls(msg: Dict[str, Any], turn: int) -> List[Dict[str, Any]]:
    """Extract tool calls from an LLM message."""
    tc = msg.get("tool_calls")
    if tc:
        return tc

    content = msg.get("content", "")

    # Try XML parsing first as it's more structured
    xml_calls = parse_xml_tool_calls(content)
    if xml_calls:
        return xml_calls

    # Fallback to legacy textual format
    parsed = parse_textual_tool_call(content)
    if parsed:
        return [{"id": f"textual_call_{turn}", "function": parsed, "type": "function"}]
    return []


def construct_system_prompt() -> str:
    """Build the system prompt based on mode flags."""
    from asky.config import (
        SYSTEM_PROMPT,
        SEARCH_SUFFIX,
        SYSTEM_PROMPT_SUFFIX,
    )

    # Inject current date into the system prompt
    current_date = datetime.now().strftime("%A, %B %d, %Y at %H:%M")
    system_content = SYSTEM_PROMPT.format(CURRENT_DATE=current_date)

    system_content += SEARCH_SUFFIX
    system_content += SYSTEM_PROMPT_SUFFIX

    return system_content


def construct_research_system_prompt() -> str:
    """Build the system prompt for research mode."""
    from asky.config import (
        RESEARCH_SYSTEM_PROMPT,
        RESEARCH_SYSTEM_PREFIX,
        RESEARCH_SYSTEM_SUFFIX,
        RESEARCH_FORCE_SEARCH,
    )

    # Inject current date
    current_date = datetime.now().strftime("%A, %B %d, %Y at %H:%M")

    # If components are present in ch config, use them to build the prompt
    if RESEARCH_SYSTEM_PREFIX:
        parts = [RESEARCH_SYSTEM_PREFIX.format(CURRENT_DATE=current_date)]
        if RESEARCH_FORCE_SEARCH:
            parts.append(RESEARCH_FORCE_SEARCH)
        if RESEARCH_SYSTEM_SUFFIX:
            parts.append(RESEARCH_SYSTEM_SUFFIX)
        return "\n\n".join(parts)

    # Fallback to monolithic prompt if components are missing
    return RESEARCH_SYSTEM_PROMPT.replace("{CURRENT_DATE}", current_date)


def append_one_shot_summarization_guidance(
    system_prompt: str,
    corpus_document_count: int,
) -> str:
    """Append one-shot summarization guidance to system prompt.

    This guidance instructs the LLM to provide a direct summary without
    asking clarifying questions, suitable for small document sets where
    the user's intent is clear.

    Args:
        system_prompt: The base system prompt to append to
        corpus_document_count: Number of documents in the corpus

    Returns:
        Modified system prompt with one-shot guidance appended
    """
    import logging

    logger = logging.getLogger(__name__)

    guidance = f"""
CRITICAL INSTRUCTION - One-Shot Summarization Mode:
You MUST provide a direct, comprehensive summary immediately. DO NOT ask clarifying questions.

Context:
- The user has requested a summary of {corpus_document_count} document(s)
- All documents are already preloaded and available via `get_relevant_content`
- The corpus is small enough for direct summarization

Required Actions:
1. Call `get_relevant_content` to retrieve all document content
2. Synthesize a comprehensive summary from the retrieved content
3. If documents cover different topics, organize by document or theme
4. Provide the summary directly in your response

FORBIDDEN: Do NOT ask what the user wants to know, do NOT request clarification, do NOT ask follow-up questions before providing the summary.
"""

    logger.debug(
        "Applied one-shot summarization guidance: corpus_docs=%d",
        corpus_document_count,
    )

    return f"{system_prompt}\n{guidance}"


def append_research_guidance(
    system_prompt: str,
    corpus_preloaded: bool = False,
    local_kb_hint_enabled: bool = False,
    section_tools_enabled: bool = False,
    classification: Optional[Any] = None,
) -> str:
    """Append context-aware research guidance to the system prompt.

    Args:
        system_prompt: The base system prompt
        corpus_preloaded: Whether corpus was preloaded
        local_kb_hint_enabled: Whether to add local KB hints
        section_tools_enabled: Whether section tools are available
        classification: Optional QueryClassification result to determine guidance type

    Returns:
        Modified system prompt with appropriate guidance appended
    """
    import logging

    logger = logging.getLogger(__name__)

    # One-shot mode takes precedence over standard retrieval guidance
    if (
        classification
        and hasattr(classification, "mode")
        and classification.mode == "one_shot"
    ):
        logger.debug("Routing to one-shot summarization guidance")
        system_prompt = append_one_shot_summarization_guidance(
            system_prompt,
            classification.corpus_document_count,
        )

    # Standard research mode guidance (only if not in one-shot mode)
    else:
        logger.debug("Applying standard research guidance")
        if corpus_preloaded:
            from asky.config import RESEARCH_RETRIEVAL_ONLY_GUIDANCE_PROMPT

            system_prompt = (
                f"{system_prompt}\n{RESEARCH_RETRIEVAL_ONLY_GUIDANCE_PROMPT}"
            )

    if local_kb_hint_enabled:
        system_prompt = (
            f"{system_prompt}\n\n"
            "Local Knowledge Base Guidance:\n"
            "- Local corpus sources were preloaded from configured document roots.\n"
            "- Do not ask the user for local filesystem paths.\n"
            "- You may call `query_research_memory` first, but if it returns no findings, immediately call "
            "`get_relevant_content` against the preloaded corpus sources."
        )
    if section_tools_enabled:
        system_prompt = (
            f"{system_prompt}\n"
            "- For section-focused local corpus questions, call `list_sections` first, then "
            "`summarize_section` with `section_ref` or exact `section_id`.\n"
            "- Do not append section IDs to corpus URL paths. Use `section_ref` "
            "(`corpus://cache/<id>#section=<section-id>`) or explicit section args."
        )
    return system_prompt
