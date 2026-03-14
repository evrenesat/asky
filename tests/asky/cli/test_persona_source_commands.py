"""Tests for milestone-3 persona source CLI commands."""

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from asky.cli import persona_commands
from asky.plugins.manual_persona_creator.source_types import PersonaSourceKind


def test_handle_persona_ingest_source_basic(tmp_path):
    """Verify ingest-source preflight and job initiation."""
    with patch("asky.cli.persona_commands.persona_exists", return_value=True), \
         patch("asky.cli.persona_commands._get_data_dir", return_value=tmp_path), \
         patch("asky.cli.persona_commands.source_service.prepare_source_preflight") as mock_preflight, \
         patch("asky.cli.persona_commands.Confirm.ask", return_value=True), \
         patch("asky.cli.persona_commands.source_service.create_source_ingestion_job", return_value="job123"), \
         patch("asky.cli.persona_commands.source_service.run_source_job") as mock_run:
        
        mock_preflight.return_value = {
            "source_class": "manual_source",
            "trust_class": "authored_primary",
            "initial_status": "approved"
        }
        mock_run.return_value = MagicMock(
            source_id="source:article:123",
            extracted_counts={"viewpoints": 1, "facts": 1, "timeline": 1}
        )
        
        args = argparse.Namespace(name="arendt", kind="article", path="art.txt")
        persona_commands.handle_persona_ingest_source(args)
        
        assert mock_preflight.called
        assert mock_run.called


def test_handle_persona_sources_list(tmp_path):
    """Verify sources listing table."""
    with patch("asky.cli.persona_commands.persona_exists", return_value=True), \
         patch("asky.cli.persona_commands._get_data_dir", return_value=tmp_path), \
         patch("asky.cli.persona_commands.source_service.list_source_bundles_for_persona") as mock_list, \
         patch("asky.cli.persona_commands.Table") as mock_table:
        
        mock_list.return_value = [
            {"source_id": "s1", "label": "L1", "kind": "article", "review_status": "approved", "updated_at": "2024-01-01"}
        ]
        
        args = argparse.Namespace(name="arendt", status=None, kind=None, limit=20)
        persona_commands.handle_persona_sources(args)
        
        assert mock_list.called
        assert mock_table.called


def test_handle_persona_approve_source(tmp_path):
    """Verify approve-source confirmation and service call."""
    with patch("asky.cli.persona_commands._get_data_dir", return_value=tmp_path), \
         patch("asky.cli.persona_commands.Confirm.ask", return_value=True), \
         patch("asky.cli.persona_commands.source_service.approve_source_bundle") as mock_approve:
        
        args = argparse.Namespace(name="arendt", source_id="source:biography:123")
        persona_commands.handle_persona_approve_source(args)
        
        mock_approve.assert_called_with(tmp_path, "arendt", "source:biography:123")


def test_handle_persona_facts_query_with_topic(tmp_path):
    """Verify facts query with topic filtering."""
    with patch("asky.cli.persona_commands._get_data_dir", return_value=tmp_path), \
         patch("asky.cli.persona_commands.source_service.query_approved_facts") as mock_query:
        
        args = argparse.Namespace(name="arendt", source="s1", topic="politics", limit=10)
        persona_commands.handle_persona_facts(args)
        
        mock_query.assert_called_with(tmp_path, "arendt", "s1", topic="politics")
