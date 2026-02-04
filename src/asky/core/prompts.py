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


def extract_calls(msg: Dict[str, Any], turn: int) -> List[Dict[str, Any]]:
    """Extract tool calls from an LLM message."""
    tc = msg.get("tool_calls")
    if tc:
        return tc
    parsed = parse_textual_tool_call(msg.get("content", ""))
    if parsed:
        return [{"id": f"textual_call_{turn}", "function": parsed}]
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
