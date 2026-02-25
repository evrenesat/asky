"""Integration tests for mention parsing pipeline.

Tests the full flow from query input through mention parsing, persona resolution,
and persona loading into sessions.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from asky.api.types import AskyTurnRequest
from asky.cli.mention_parser import parse_persona_mention
from asky.plugins.kvstore import PluginKVStore
from asky.plugins.manual_persona_creator.storage import create_persona
from asky.plugins.persona_manager.resolver import (
    resolve_persona_name,
    set_persona_alias,
)
from asky.plugins.persona_manager.session_binding import (
    get_session_binding,
    set_session_binding,
)


@pytest.fixture
def temp_data_dir(tmp_path: Path) -> Path:
    """Create a temporary data directory for testing."""
    return tmp_path / "data"


@pytest.fixture
def kvstore(tmp_path: Path) -> PluginKVStore:
    """Create a KVStore instance for testing."""
    db_path = tmp_path / "test.db"
    return PluginKVStore("persona_manager", db_path=db_path)


@pytest.fixture
def sample_personas(temp_data_dir: Path):
    """Create sample personas for testing."""
    create_persona(
        data_dir=temp_data_dir,
        persona_name="developer",
        description="Software developer persona",
        behavior_prompt="You are a helpful software developer.",
    )
    
    create_persona(
        data_dir=temp_data_dir,
        persona_name="writer",
        description="Content writer persona",
        behavior_prompt="You are a creative content writer.",
    )


@pytest.fixture
def mock_session():
    """Mock session for testing session-dependent operations."""
    session = MagicMock()
    session.id = 1
    session.name = "test-session"
    return session


class TestMentionParsingInCLIFlow:
    """Test mention parsing in CLI flow."""
    
    def test_cli_mention_parsing_extracts_persona(self, temp_data_dir: Path, sample_personas):
        """Test that CLI flow extracts persona from @mention."""
        from asky.cli.chat import run_chat
        
        args = argparse.Namespace(
            model="gf",
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
        
        query = "@developer how do I optimize this code?"
        
        with patch("asky.cli.chat.AskyClient") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            
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
            
            mock_finalize_result = MagicMock()
            mock_finalize_result.notices = []
            mock_client.finalize_turn_history.return_value = mock_finalize_result
            
            with patch("asky.cli.chat.LIVE_BANNER", False), \
                 patch("asky.cli.chat.get_shell_session_id", return_value=None), \
                 patch("asky.cli.chat.set_shell_session_id"), \
                 patch("asky.cli.chat.generate_session_name", return_value="test-session"), \
                 patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir):
                
                run_chat(args, query)
                
                assert hasattr(args, "persona_mention")
                assert args.persona_mention == "developer"
    
    def test_cli_cleaned_query_propagates(self, temp_data_dir: Path, sample_personas):
        """Test that cleaned query (without @mention) is used in CLI flow."""
        from asky.cli.chat import run_chat
        
        args = argparse.Namespace(
            model="gf",
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
        
        query = "@developer how do I optimize this code?"
        
        with patch("asky.cli.chat.AskyClient") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            
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
            
            mock_finalize_result = MagicMock()
            mock_finalize_result.notices = []
            mock_client.finalize_turn_history.return_value = mock_finalize_result
            
            with patch("asky.cli.chat.LIVE_BANNER", False), \
                 patch("asky.cli.chat.get_shell_session_id", return_value=None), \
                 patch("asky.cli.chat.set_shell_session_id"), \
                 patch("asky.cli.chat.generate_session_name", return_value="test-session"), \
                 patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir):
                
                run_chat(args, query)
                
                call_args = mock_client.run_turn.call_args
                turn_request = call_args[0][0]
                
                assert "@developer" not in turn_request.query_text
                assert "how do I optimize this code?" in turn_request.query_text
    
    def test_cli_error_handling_invalid_mention(self, temp_data_dir: Path, sample_personas):
        """Test CLI handles invalid persona mentions gracefully."""
        from asky.cli.chat import run_chat
        
        args = argparse.Namespace(
            model="gf",
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
        
        query = "@nonexistent help me"
        
        with patch("asky.cli.chat.AskyClient") as mock_client_class, \
             patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir):
            
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            
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
            
            mock_finalize_result = MagicMock()
            mock_finalize_result.notices = []
            mock_client.finalize_turn_history.return_value = mock_finalize_result
            
            with patch("asky.cli.chat.LIVE_BANNER", False), \
                 patch("asky.cli.chat.get_shell_session_id", return_value=None), \
                 patch("asky.cli.chat.set_shell_session_id"), \
                 patch("asky.cli.chat.generate_session_name", return_value="test-session"):
                
                run_chat(args, query)
                
                assert hasattr(args, "persona_mention")
                assert args.persona_mention == "nonexistent"
    
    def test_cli_error_handling_multiple_mentions(self, temp_data_dir: Path, sample_personas):
        """Test CLI error handling for multiple persona mentions."""
        from asky.cli.chat import run_chat
        
        args = argparse.Namespace(
            model="gf",
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
        
        query = "@developer @writer help me"
        
        with patch("asky.cli.chat.Console") as mock_console_class:
            mock_console = MagicMock()
            mock_console_class.return_value = mock_console
            
            run_chat(args, query)
            
            mock_console.print.assert_called()
            error_call = mock_console.print.call_args[0][0]
            assert "Multiple persona mentions" in error_call or "Error" in error_call


class TestMentionParsingInAPIFlow:
    """Test mention parsing in API flow."""
    
    def test_api_turn_request_persona_mention_field(self):
        """Test that AskyTurnRequest has persona_mention field."""
        request = AskyTurnRequest(
            query_text="test query",
            persona_mention="developer",
        )
        
        assert request.persona_mention == "developer"
    
    def test_api_turn_request_persona_mention_optional(self):
        """Test that persona_mention field is optional."""
        request = AskyTurnRequest(
            query_text="test query",
        )
        
        assert request.persona_mention is None


class TestPersonaLoadingViaMention:
    """Test persona loading via @mention syntax."""
    
    def test_persona_loads_into_session_via_mention(
        self,
        temp_data_dir: Path,
        kvstore: PluginKVStore,
        sample_personas,
        mock_session,
    ):
        """Test that persona is loaded into session when mentioned."""
        query = "@developer how do I optimize this?"
        
        result = parse_persona_mention(query)
        assert result.has_mention
        assert result.persona_identifier == "developer"
        
        resolved_name = resolve_persona_name(
            result.persona_identifier,
            kvstore,
            temp_data_dir,
        )
        assert resolved_name == "developer"
        
        set_session_binding(
            temp_data_dir,
            session_id=mock_session.id,
            persona_name=resolved_name,
        )
        
        bound_persona = get_session_binding(temp_data_dir, mock_session.id)
        assert bound_persona == "developer"
    
    def test_persona_loads_via_alias_mention(
        self,
        temp_data_dir: Path,
        kvstore: PluginKVStore,
        sample_personas,
        mock_session,
    ):
        """Test that persona loads when mentioned by alias."""
        set_persona_alias("dev", "developer", kvstore, temp_data_dir)
        
        query = "@dev help me with this code"
        
        result = parse_persona_mention(query)
        assert result.has_mention
        assert result.persona_identifier == "dev"
        
        resolved_name = resolve_persona_name(
            result.persona_identifier,
            kvstore,
            temp_data_dir,
        )
        assert resolved_name == "developer"
        
        set_session_binding(
            temp_data_dir,
            session_id=mock_session.id,
            persona_name=resolved_name,
        )
        
        bound_persona = get_session_binding(temp_data_dir, mock_session.id)
        assert bound_persona == "developer"
    
    def test_persona_replaces_existing_binding(
        self,
        temp_data_dir: Path,
        kvstore: PluginKVStore,
        sample_personas,
        mock_session,
    ):
        """Test that new persona mention replaces existing binding."""
        set_session_binding(
            temp_data_dir,
            session_id=mock_session.id,
            persona_name="developer",
        )
        
        assert get_session_binding(temp_data_dir, mock_session.id) == "developer"
        
        query = "@writer help me write an article"
        result = parse_persona_mention(query)
        resolved_name = resolve_persona_name(
            result.persona_identifier,
            kvstore,
            temp_data_dir,
        )
        
        set_session_binding(
            temp_data_dir,
            session_id=mock_session.id,
            persona_name=resolved_name,
        )
        
        bound_persona = get_session_binding(temp_data_dir, mock_session.id)
        assert bound_persona == "writer"


class TestErrorHandlingForInvalidMentions:
    """Test error handling for invalid persona mentions."""
    
    def test_nonexistent_persona_returns_none(
        self,
        temp_data_dir: Path,
        kvstore: PluginKVStore,
        sample_personas,
    ):
        """Test that resolving non-existent persona returns None."""
        query = "@nonexistent help me"
        result = parse_persona_mention(query)
        
        resolved_name = resolve_persona_name(
            result.persona_identifier,
            kvstore,
            temp_data_dir,
        )
        
        assert resolved_name is None
    
    def test_nonexistent_alias_returns_none(
        self,
        temp_data_dir: Path,
        kvstore: PluginKVStore,
        sample_personas,
    ):
        """Test that resolving non-existent alias returns None."""
        query = "@fakealias help me"
        result = parse_persona_mention(query)
        
        resolved_name = resolve_persona_name(
            result.persona_identifier,
            kvstore,
            temp_data_dir,
        )
        
        assert resolved_name is None
    
    def test_multiple_mentions_raises_error(self):
        """Test that multiple mentions raise ValueError."""
        query = "@developer @writer help me"
        
        with pytest.raises(ValueError, match="Multiple persona mentions found"):
            parse_persona_mention(query)
    
    def test_empty_mention_not_treated_as_mention(self):
        """Test that @ without identifier is not treated as mention."""
        query = "Email me @ example.com"
        result = parse_persona_mention(query)
        
        assert not result.has_mention
        assert result.persona_identifier is None


class TestCleanedQueryTextPropagation:
    """Test that cleaned query text (with @mention removed) propagates correctly."""
    
    def test_mention_removed_from_query(self):
        """Test that @mention is removed from cleaned query."""
        query = "@developer how do I optimize this code?"
        result = parse_persona_mention(query)
        
        assert "@developer" not in result.cleaned_query
        assert result.cleaned_query == "how do I optimize this code?"
    
    def test_mention_removed_from_middle(self):
        """Test that @mention in middle is removed correctly."""
        query = "Can you @developer help me with this?"
        result = parse_persona_mention(query)
        
        assert "@developer" not in result.cleaned_query
        assert result.cleaned_query == "Can you help me with this?"
    
    def test_mention_removed_from_end(self):
        """Test that @mention at end is removed correctly."""
        query = "Help me with this @developer"
        result = parse_persona_mention(query)
        
        assert "@developer" not in result.cleaned_query
        assert result.cleaned_query == "Help me with this"
    
    def test_whitespace_normalized_in_cleaned_query(self):
        """Test that extra whitespace is normalized after mention removal."""
        query = "Can  you   @developer    help    me?"
        result = parse_persona_mention(query)
        
        assert result.cleaned_query == "Can you help me?"
        assert "  " not in result.cleaned_query
    
    def test_query_without_mention_unchanged(self):
        """Test that query without mention passes through unchanged."""
        query = "How do I optimize this code?"
        result = parse_persona_mention(query)
        
        assert result.cleaned_query == query
        assert not result.has_mention


class TestEndToEndIntegration:
    """End-to-end integration tests for the complete mention parsing pipeline."""
    
    def test_complete_flow_parse_resolve_load(
        self,
        temp_data_dir: Path,
        kvstore: PluginKVStore,
        sample_personas,
        mock_session,
    ):
        """Test complete flow: parse mention -> resolve persona -> load into session."""
        query = "@developer how do I optimize this code?"
        
        result = parse_persona_mention(query)
        assert result.has_mention
        assert result.persona_identifier == "developer"
        assert result.cleaned_query == "how do I optimize this code?"
        
        resolved_name = resolve_persona_name(
            result.persona_identifier,
            kvstore,
            temp_data_dir,
        )
        assert resolved_name == "developer"
        
        set_session_binding(
            temp_data_dir,
            session_id=mock_session.id,
            persona_name=resolved_name,
        )
        
        bound_persona = get_session_binding(temp_data_dir, mock_session.id)
        assert bound_persona == "developer"
    
    def test_complete_flow_with_alias(
        self,
        temp_data_dir: Path,
        kvstore: PluginKVStore,
        sample_personas,
        mock_session,
    ):
        """Test complete flow with alias: parse -> resolve alias -> load."""
        set_persona_alias("dev", "developer", kvstore, temp_data_dir)
        
        query = "@dev optimize this function"
        
        result = parse_persona_mention(query)
        assert result.has_mention
        assert result.persona_identifier == "dev"
        
        resolved_name = resolve_persona_name(
            result.persona_identifier,
            kvstore,
            temp_data_dir,
        )
        assert resolved_name == "developer"
        
        set_session_binding(
            temp_data_dir,
            session_id=mock_session.id,
            persona_name=resolved_name,
        )
        
        bound_persona = get_session_binding(temp_data_dir, mock_session.id)
        assert bound_persona == "developer"
    
    def test_complete_flow_error_handling(
        self,
        temp_data_dir: Path,
        kvstore: PluginKVStore,
        sample_personas,
        mock_session,
    ):
        """Test complete flow with error: parse -> resolve fails -> no binding."""
        query = "@nonexistent help me"
        
        result = parse_persona_mention(query)
        assert result.has_mention
        assert result.persona_identifier == "nonexistent"
        
        resolved_name = resolve_persona_name(
            result.persona_identifier,
            kvstore,
            temp_data_dir,
        )
        assert resolved_name is None
        
        bound_persona = get_session_binding(temp_data_dir, mock_session.id)
        assert bound_persona is None
