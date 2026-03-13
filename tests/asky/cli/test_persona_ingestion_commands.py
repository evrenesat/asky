from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from asky.cli.persona_commands import (
    handle_persona_ingest_book,
    handle_persona_reingest_book,
    handle_persona_books,
    handle_persona_book_report,
    handle_persona_viewpoints,
)
from asky.plugins.manual_persona_creator.storage import (
    create_persona,
    get_book_paths,
)


@pytest.fixture
def temp_data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def sample_persona(temp_data_dir: Path):
    create_persona(
        data_dir=temp_data_dir,
        persona_name="arendt",
        description="Hannah Arendt",
        behavior_prompt="prompt",
    )


@patch("asky.cli.persona_commands.book_service.prepare_ingestion_preflight")
@patch("asky.cli.persona_commands.Confirm.ask")
@patch("asky.cli.persona_commands.Prompt.ask")
@patch("asky.cli.persona_commands.book_service.create_ingestion_job")
@patch("asky.cli.persona_commands.BookIngestionJob")
def test_handle_persona_ingest_book_success(
    mock_job_class,
    mock_create_job,
    mock_prompt,
    mock_confirm,
    mock_preflight,
    temp_data_dir,
    sample_persona,
):
    mock_preflight.return_value = MagicMock(
        is_duplicate=False,
        resumable_job_id=None,
        candidates=[],
        source_path="/path/to/book.txt",
        source_fingerprint="fp123",
        stats={"word_count": 1000, "section_count": 5},
        proposed_targets=MagicMock(topic_target=8, viewpoint_target=24)
    )
    # 1. Selection prompt if candidates exist (not here)
    # 2. Preflight loop: Title, Authors, Year, ISBN, Topic, Viewpoint, Proceed
    mock_prompt.side_effect = ["The Human Condition", "Hannah Arendt", "1958", "isbn123", "8", "24"]
    mock_confirm.return_value = True
    mock_create_job.return_value = "job-123"
    
    args = argparse.Namespace(name="arendt", path="/path/to/book.txt")
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir):
        handle_persona_ingest_book(args)
        
    mock_create_job.assert_called_once()
    mock_job_class.assert_called_once()


def test_handle_persona_books_output(temp_data_dir, sample_persona, capsys):
    # Setup an existing book
    paths = get_book_paths(temp_data_dir / "personas" / "arendt", "hc-1958")
    paths.book_dir.mkdir(parents=True)
    paths.metadata_path.write_text("title = 'The Human Condition'\nauthors = ['Hannah Arendt']\npublication_year = 1958", encoding="utf-8")
    paths.viewpoints_path.write_text("[]", encoding="utf-8")
    
    args = argparse.Namespace(name="arendt")
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir):
        handle_persona_books(args)
        
    captured = capsys.readouterr()
    assert "The Human Condition" in captured.out
    assert "hc-1958" in captured.out


@patch("asky.cli.persona_commands.book_service.prepare_ingestion_preflight")
@patch("asky.cli.persona_commands.Confirm.ask")
@patch("asky.cli.persona_commands.Prompt.ask")
@patch("asky.cli.persona_commands.book_service.create_ingestion_job")
@patch("asky.cli.persona_commands.BookIngestionJob")
@patch("asky.cli.persona_commands.book_service.get_authored_book_report")
def test_handle_persona_reingest_book_success(
    mock_get_report,
    mock_job_class,
    mock_create_job,
    mock_prompt,
    mock_confirm,
    mock_preflight,
    temp_data_dir,
    sample_persona,
):
    from asky.plugins.manual_persona_creator.book_types import BookMetadata, ExtractionTargets
    from asky.plugins.manual_persona_creator.storage import get_book_key
    
    title = "The Human Condition"
    year = 1958
    book_key = get_book_key(title=title, publication_year=year, isbn=None)
    
    mock_get_report.return_value = MagicMock(
        metadata=BookMetadata(title=title, authors=["Hannah Arendt"], publication_year=year),
        targets=ExtractionTargets(topic_target=8, viewpoint_target=24)
    )

    mock_preflight.return_value = MagicMock(
        source_fingerprint="fp456",
        proposed_targets=MagicMock(topic_target=8, viewpoint_target=24),
        stats={"word_count": 1000, "section_count": 5}
    )
    # Metadata remains same so book_key remains same
    mock_prompt.side_effect = [title, "Hannah Arendt", str(year), "", "8", "24"]
    mock_confirm.return_value = True
    
    args = argparse.Namespace(name="arendt", book_key=book_key, path="/path/to/revised.txt")
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir):
        handle_persona_reingest_book(args)
        
    mock_create_job.assert_called_once()


def test_handle_persona_viewpoints_output(temp_data_dir, sample_persona, capsys):
    persona_root = temp_data_dir / "personas" / "arendt"
    book_key = "hc-1958"
    book_paths = get_book_paths(persona_root, book_key)
    book_paths.book_dir.mkdir(parents=True)
    
    viewpoints = [
        {
            "entry_id": "v1",
            "topic": "Labor",
            "claim": "Labor is the activity which corresponds to the biological process of the human body.",
            "stance_label": "supports",
            "confidence": 0.95,
            "book_key": "hc-1958",
            "book_title": "The Human Condition",
            "publication_year": 1958,
            "isbn": None,
            "evidence": [{"excerpt": "Biological process", "section_ref": "1"}]
        }
    ]
    book_paths.viewpoints_path.write_text(json.dumps(viewpoints), encoding="utf-8")
    
    args = argparse.Namespace(name="arendt", book=None, limit=20)
    
    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir):
        handle_persona_viewpoints(args)
        
    captured = capsys.readouterr()
    assert "Topic: Labor" in captured.out
    assert "Biological process" in captured.out


@patch("asky.cli.persona_commands.book_service.update_ingestion_job_inputs")
@patch("asky.cli.persona_commands.book_service.get_ingestion_identity_status")
@patch("asky.cli.persona_commands.Confirm.ask")
@patch("asky.cli.persona_commands.Prompt.ask")
@patch("asky.cli.persona_commands.BookIngestionJob")
def test_resumable_ingest_persists_edited_preflight_inputs(
    mock_job_class,
    mock_prompt,
    mock_confirm,
    mock_identity_status,
    mock_update_job,
    temp_data_dir,
    sample_persona,
):
    from asky.plugins.manual_persona_creator.book_types import (
        BookMetadata,
        ExtractionTargets,
        IngestionIdentityStatus,
    )

    mock_identity_status.return_value = IngestionIdentityStatus.AVAILABLE
    mock_prompt.side_effect = ["Edited Title", "Edited Author", "2024", "", "9", "27"]
    mock_confirm.return_value = True

    args = {
        "data_dir": temp_data_dir,
        "persona_name": "arendt",
        "source_path": "/path/to/book.txt",
        "source_fingerprint": "fp123",
        "initial_metadata": BookMetadata(title="Draft", authors=["Author"]),
        "initial_targets": ExtractionTargets(topic_target=8, viewpoint_target=24),
        "stats": {"word_count": 1000, "section_count": 5},
        "mode": "ingest",
        "job_id": "job-123",
    }

    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir):
        from asky.cli.persona_commands import _handle_preflight_loop

        _handle_preflight_loop(**args)

    mock_update_job.assert_called_once()
    _, kwargs = mock_update_job.call_args
    assert kwargs["job_id"] == "job-123"
    assert kwargs["metadata"].title == "Edited Title"
    assert kwargs["targets"].topic_target == 9


def test_handle_persona_viewpoints_honors_topic_filter(temp_data_dir, sample_persona, capsys):
    persona_root = temp_data_dir / "personas" / "arendt"
    book_key = "hc-1958"
    book_paths = get_book_paths(persona_root, book_key)
    book_paths.book_dir.mkdir(parents=True)

    viewpoints = [
        {
            "entry_id": "v1",
            "topic": "Labor",
            "claim": "Claim A",
            "stance_label": "supports",
            "confidence": 0.95,
            "book_key": "hc-1958",
            "book_title": "The Human Condition",
            "publication_year": 1958,
            "isbn": None,
            "evidence": [{"excerpt": "Labor excerpt", "section_ref": "1"}],
        },
        {
            "entry_id": "v2",
            "topic": "Action",
            "claim": "Claim B",
            "stance_label": "supports",
            "confidence": 0.75,
            "book_key": "hc-1958",
            "book_title": "The Human Condition",
            "publication_year": 1958,
            "isbn": None,
            "evidence": [{"excerpt": "Action excerpt", "section_ref": "2"}],
        },
    ]
    book_paths.viewpoints_path.write_text(json.dumps(viewpoints), encoding="utf-8")

    args = argparse.Namespace(name="arendt", book=None, topic="Labor", limit=20)

    with patch("asky.cli.persona_commands._get_data_dir", return_value=temp_data_dir):
        handle_persona_viewpoints(args)

    captured = capsys.readouterr()
    assert "Topic: Labor" in captured.out
    assert "Labor excerpt" in captured.out
    assert "Topic: Action" not in captured.out
