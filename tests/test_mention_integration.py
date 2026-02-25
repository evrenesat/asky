"""Tests for @mention parsing integration in chat flow."""

import argparse
from unittest.mock import MagicMock, patch

import pytest

from asky.cli.mention_parser import parse_persona_mention


def test_parse_persona_mention_integration():
    """Test that mention parsing extracts persona and cleans query."""
    query = "@developer how do I optimize this code?"
    result = parse_persona_mention(query)
    
    assert result.has_mention is True
    assert result.persona_identifier == "developer"
    assert result.cleaned_query == "how do I optimize this code?"
    assert result.mention_position == 0


def test_parse_persona_mention_with_alias():
    """Test that mention parsing works with aliases."""
    query = "Can you help me @dev with this bug?"
    result = parse_persona_mention(query)
    
    assert result.has_mention is True
    assert result.persona_identifier == "dev"
    assert result.cleaned_query == "Can you help me with this bug?"


def test_parse_persona_mention_no_mention():
    """Test that queries without mentions pass through unchanged."""
    query = "How do I optimize this code?"
    result = parse_persona_mention(query)
    
    assert result.has_mention is False
    assert result.persona_identifier is None
    assert result.cleaned_query == query


def test_parse_persona_mention_multiple_raises_error():
    """Test that multiple mentions raise an error."""
    query = "@developer @writer help me"
    
    with pytest.raises(ValueError) as exc_info:
        parse_persona_mention(query)
    
    assert "Multiple persona mentions found" in str(exc_info.value)
    assert "developer, writer" in str(exc_info.value)


def test_mention_parsing_stores_in_args():
    """Test that mention parsing stores persona_identifier in args."""
    from asky.cli.chat import run_chat
    
    args = argparse.Namespace(
        model="gf",  # Use a valid model from models.toml
        summarize=False,
        verbose=False,
        double_verbose=False,
        open=False,
        research=False,
        local_corpus=None,
        tool_off=[],
        lean=False,
        sticky_session=["test-session"],
        resume_session=None,
        continue_ids=None,
        elephant_mode=False,
        turns=None,
        terminal_lines=None,
        system_prompt=None,
        research_flag_provided=False,
        research_source_mode=None,
        replace_research_corpus=False,
        shortlist="auto",
    )
    
    query = "@developer how do I optimize this?"
    
    # Mock the entire AskyClient.run_turn to avoid actual execution
    with patch("asky.cli.chat.AskyClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        # Mock run_turn to return a minimal result
        mock_turn_result = MagicMock()
        mock_turn_result.final_answer = "Test answer"
        mock_turn_result.session_id = 1
        mock_turn_result.session = MagicMock()
        mock_turn_result.session.research_mode = False
        mock_turn_result.session.matched_sessions = []
        mock_turn_result.preload = MagicMock()
        mock_turn_result.preload.shortlist_stats = None
        mock_turn_result.preload.shortlist_payload = None
        mock_turn_result.notices = []
        mock_turn_result.halted = False
        mock_client.run_turn.return_value = mock_turn_result
        
        # Mock finalize_turn_history
        mock_finalize_result = MagicMock()
        mock_finalize_result.notices = []
        mock_client.finalize_turn_history.return_value = mock_finalize_result
        
        # Mock other dependencies
        with patch("asky.cli.chat.LIVE_BANNER", False), \
             patch("asky.cli.chat.get_shell_session_id", return_value=None), \
             patch("asky.cli.chat.set_shell_session_id"), \
             patch("asky.cli.chat.generate_session_name", return_value="test-session"):
            
            run_chat(args, query)
            
            # Verify that persona_mention was stored in args
            assert hasattr(args, "persona_mention")
            assert args.persona_mention == "developer"
            
            # Verify that the cleaned query was used
            call_args = mock_client.run_turn.call_args
            turn_request = call_args[0][0]
            # The query_text should be cleaned (mention removed)
            assert "@developer" not in turn_request.query_text


def test_mention_parsing_error_handling():
    """Test that mention parsing errors are handled gracefully."""
    from asky.cli.chat import run_chat
    
    args = argparse.Namespace(
        model="gf",  # Use a valid model from models.toml
        summarize=False,
        verbose=False,
        double_verbose=False,
        open=False,
        research=False,
        local_corpus=None,
        tool_off=[],
        lean=False,
        sticky_session=None,
        resume_session=None,
        continue_ids=None,
        elephant_mode=False,
        turns=None,
        terminal_lines=None,
        system_prompt=None,
    )
    
    # Query with multiple mentions (should error)
    query = "@developer @writer help me"
    
    with patch("asky.cli.chat.Console") as mock_console_class:
        mock_console = MagicMock()
        mock_console_class.return_value = mock_console
        
        run_chat(args, query)
        
        # Verify error was printed
        mock_console.print.assert_called()
        error_call = mock_console.print.call_args[0][0]
        assert "Error" in error_call or "Multiple persona mentions" in error_call
