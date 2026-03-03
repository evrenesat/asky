"""Tests for persona mention parser."""

import pytest

from asky.cli.mention_parser import parse_persona_mention


def test_parse_no_mention():
    """Test parsing query with no mention."""
    result = parse_persona_mention("What is the weather today?")
    
    assert result.persona_identifier is None
    assert result.cleaned_query == "What is the weather today?"
    assert result.mention_position == -1
    assert result.has_mention is False


def test_parse_mention_at_start():
    """Test parsing mention at the start of query."""
    result = parse_persona_mention("@dev how do I optimize this code?")
    
    assert result.persona_identifier == "dev"
    assert result.cleaned_query == "how do I optimize this code?"
    assert result.mention_position == 0
    assert result.has_mention is True


def test_parse_mention_in_middle():
    """Test parsing mention in the middle of query."""
    result = parse_persona_mention("Can you @writer help me with this article?")
    
    assert result.persona_identifier == "writer"
    assert result.cleaned_query == "Can you help me with this article?"
    assert result.mention_position == 8
    assert result.has_mention is True


def test_parse_mention_at_end():
    """Test parsing mention at the end of query."""
    result = parse_persona_mention("Help me with this @expert")
    
    assert result.persona_identifier == "expert"
    assert result.cleaned_query == "Help me with this"
    assert result.mention_position == 18
    assert result.has_mention is True


def test_parse_mention_only():
    """Test parsing query that is only a mention."""
    result = parse_persona_mention("@dev")
    
    assert result.persona_identifier == "dev"
    assert result.cleaned_query == ""
    assert result.mention_position == 0
    assert result.has_mention is True


def test_parse_mention_with_underscores():
    """Test parsing mention with underscores in name."""
    result = parse_persona_mention("@software_engineer help me")
    
    assert result.persona_identifier == "software_engineer"
    assert result.cleaned_query == "help me"
    assert result.has_mention is True


def test_parse_mention_with_hyphens():
    """Test parsing mention with hyphens in name."""
    result = parse_persona_mention("@content-creator write this")
    
    assert result.persona_identifier == "content-creator"
    assert result.cleaned_query == "write this"
    assert result.has_mention is True


def test_parse_mention_with_numbers():
    """Test parsing mention with numbers in name."""
    result = parse_persona_mention("@dev123 help")
    
    assert result.persona_identifier == "dev123"
    assert result.cleaned_query == "help"
    assert result.has_mention is True


def test_parse_mention_mixed_case():
    """Test parsing mention with mixed case."""
    result = parse_persona_mention("@DevExpert help me")
    
    assert result.persona_identifier == "DevExpert"
    assert result.cleaned_query == "help me"
    assert result.has_mention is True


def test_parse_multiple_mentions_raises_error():
    """Test that multiple mentions raise an error."""
    with pytest.raises(ValueError, match="Multiple persona mentions found"):
        parse_persona_mention("@dev and @writer help me")


def test_parse_multiple_mentions_error_message():
    """Test that multiple mentions error includes all mention names."""
    with pytest.raises(ValueError, match="dev, writer"):
        parse_persona_mention("@dev and @writer help me")


def test_parse_empty_query():
    """Test parsing empty query."""
    result = parse_persona_mention("")
    
    assert result.persona_identifier is None
    assert result.cleaned_query == ""
    assert result.mention_position == -1
    assert result.has_mention is False


def test_parse_whitespace_only_query():
    """Test parsing whitespace-only query."""
    result = parse_persona_mention("   ")
    
    assert result.persona_identifier is None
    assert result.cleaned_query == "   "
    assert result.mention_position == -1
    assert result.has_mention is False


def test_parse_mention_with_extra_whitespace():
    """Test that extra whitespace is normalized in cleaned query."""
    result = parse_persona_mention("Can  you   @dev    help    me?")
    
    assert result.persona_identifier == "dev"
    assert result.cleaned_query == "Can you help me?"
    assert result.has_mention is True


def test_parse_mention_preserves_punctuation():
    """Test that punctuation is preserved in cleaned query."""
    result = parse_persona_mention("@dev, can you help me?")
    
    assert result.persona_identifier == "dev"
    assert result.cleaned_query == ", can you help me?"
    assert result.has_mention is True


def test_parse_mention_with_special_chars_in_query():
    """Test parsing mention with special characters in the rest of query."""
    result = parse_persona_mention("@dev help with $variable and #hashtag")
    
    assert result.persona_identifier == "dev"
    assert result.cleaned_query == "help with $variable and #hashtag"
    assert result.has_mention is True


def test_parse_at_symbol_without_valid_identifier():
    """Test that @ without valid identifier is not treated as mention."""
    result = parse_persona_mention("Email me @ example.com")
    
    assert result.persona_identifier is None
    assert result.cleaned_query == "Email me @ example.com"
    assert result.has_mention is False


def test_parse_mention_does_not_match_email():
    """Test that email addresses are not treated as mentions."""
    result = parse_persona_mention("Contact user@example.com for help")
    
    assert result.persona_identifier is None
    assert result.cleaned_query == "Contact user@example.com for help"
    assert result.has_mention is False


def test_parse_mention_with_trailing_punctuation():
    """Test parsing mention followed by punctuation."""
    result = parse_persona_mention("@dev, help me")
    
    assert result.persona_identifier == "dev"
    assert result.cleaned_query == ", help me"
    assert result.has_mention is True


def test_parse_mention_position_accuracy():
    """Test that mention position is accurately reported."""
    query = "Please @expert help me with this"
    result = parse_persona_mention(query)
    
    assert result.mention_position == 7
    assert query[result.mention_position:result.mention_position + 7] == "@expert"
