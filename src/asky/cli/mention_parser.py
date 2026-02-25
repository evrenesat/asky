"""Parser for @persona_name mention syntax in user queries."""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class MentionParseResult:
    """Result of parsing @mentions from query text."""
    
    persona_identifier: Optional[str]
    cleaned_query: str
    mention_position: int
    has_mention: bool


def parse_persona_mention(query_text: str) -> MentionParseResult:
    """
    Parse @persona_name mention from query text.
    
    Rules:
    - @mention can appear anywhere in the query
    - Only one @mention is allowed per query
    - @mention is removed from the cleaned query text
    - Persona identifier can be a name or alias
    - Persona identifier format: alphanumeric, underscore, hyphen
    
    Args:
        query_text: The user query text to parse
        
    Returns:
        MentionParseResult with extracted persona and cleaned query
        
    Raises:
        ValueError: If multiple @mentions are found in the query
    """
    if not query_text:
        return MentionParseResult(
            persona_identifier=None,
            cleaned_query="",
            mention_position=-1,
            has_mention=False,
        )
    
    pattern = r'(?<![a-zA-Z0-9_-])@([a-zA-Z0-9_-]+)'
    matches = list(re.finditer(pattern, query_text))
    
    if len(matches) == 0:
        return MentionParseResult(
            persona_identifier=None,
            cleaned_query=query_text,
            mention_position=-1,
            has_mention=False,
        )
    
    if len(matches) > 1:
        mention_names = [match.group(1) for match in matches]
        raise ValueError(
            f"Multiple persona mentions found: {', '.join(mention_names)}. "
            "Only one persona can be active per query."
        )
    
    match = matches[0]
    persona_identifier = match.group(1)
    mention_position = match.start()
    
    cleaned_query = query_text[:match.start()] + query_text[match.end():]
    cleaned_query = ' '.join(cleaned_query.split())
    
    return MentionParseResult(
        persona_identifier=persona_identifier,
        cleaned_query=cleaned_query,
        mention_position=mention_position,
        has_mention=True,
    )
