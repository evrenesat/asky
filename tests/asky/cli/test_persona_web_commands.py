from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from asky.cli import persona_commands


def test_handle_persona_web_collect(tmp_path):
    with patch("asky.cli.persona_commands.persona_exists", return_value=True), \
         patch("asky.cli.persona_commands._get_data_dir", return_value=tmp_path), \
         patch("asky.cli.persona_commands.web_service.start_seed_domain_collection", return_value="web_123") as mock_start:
        
        args = argparse.Namespace(
            name="arendt",
            target_results=10,
            url=["https://example.com"],
            url_file=None
        )
        persona_commands.handle_persona_web_collect(args)
        
        mock_start.assert_called_once_with(
            data_dir=tmp_path,
            persona_name="arendt",
            target_results=10,
            urls=["https://example.com"],
            url_file=None
        )


def test_handle_persona_web_approve_page(tmp_path):
    with patch("asky.cli.persona_commands._get_data_dir", return_value=tmp_path), \
         patch("asky.cli.persona_commands.Confirm.ask", return_value=True), \
         patch("asky.cli.persona_commands.web_service.approve_web_page") as mock_approve:
        
        args = argparse.Namespace(
            name="arendt",
            collection_id="web_123",
            page_id="page:abc",
            trust_as="authored"
        )
        persona_commands.handle_persona_web_approve_page(args)
        
        mock_approve.assert_called_once_with(
            data_dir=tmp_path,
            persona_name="arendt",
            collection_id="web_123",
            page_id="page:abc",
            trust_as="authored"
        )


def test_handle_persona_web_retract_page(tmp_path):
    with patch("asky.cli.persona_commands._get_data_dir", return_value=tmp_path), \
         patch("asky.cli.persona_commands.web_service.retract_web_page") as mock_retract:
        
        args = argparse.Namespace(
            name="arendt",
            collection_id="web_123",
            page_id="page:abc"
        )
        persona_commands.handle_persona_web_retract_page(args)
        
        mock_retract.assert_called_once_with(
            data_dir=tmp_path,
            persona_name="arendt",
            collection_id="web_123",
            page_id="page:abc"
        )
