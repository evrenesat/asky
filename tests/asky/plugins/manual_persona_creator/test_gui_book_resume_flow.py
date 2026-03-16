from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from asky.plugins.gui_server.pages.personas import _add_authored_book_dialog
from asky.plugins.manual_persona_creator.book_types import (
    BookMetadata,
    ExtractionTargets,
    MetadataCandidate,
    PreflightResult,
    IngestionJobManifest,
)

class FakeUI:
    def __init__(self):
        self.dialog_obj = MagicMock()
        self.dialog_obj.open = MagicMock()
        self.dialog_obj.close = MagicMock()
        self.dialog_obj.__enter__ = lambda s: s
        self.dialog_obj.__exit__ = lambda s, *a: None
        
        self.notified = []
        self.navigated = []
        self.elements = []
        self.timers = []

    def dialog(self): return self.dialog_obj
    def card(self):
        class Context:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def classes(self, *s): return self
        return Context()
    
    def column(self):
        class Context:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def classes(self, *s): return self
            def hide(self): return self
            def show(self): return self
            def clear(self): return self
            def visible(self): return True
        return Context()

    def label(self, text, **kwargs):
        self.elements.append(("label", text, None))
        return self
    
    def classes(self, *args, **kwargs): return self
    def props(self, *args, **kwargs): return self
    def on(self, *args, **kwargs): return self

    def input(self, label, value=None):
        class Input:
            def __init__(self, v): self.value = v
            def classes(self, *s): return self
            def props(self, *s): return self
        obj = Input(value)
        self.elements.append(("input", label, obj))
        return obj

    def number(self, label, value=None):
        class Number:
            def __init__(self, v): self.value = v
            def classes(self, *s): return self
            def props(self, *s): return self
        obj = Number(value)
        self.elements.append(("number", label, obj))
        return obj

    def button(self, text=None, on_click=None, **kwargs):
        self.elements.append(("button", text, on_click))
        class Btn:
            def props(self, *a, **kw): return self
            def hide(self): pass
            def show(self): pass
        return Btn()

    def row(self):
        class Context:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def classes(self, *s): return self
        return Context()

    def separator(self): pass
    
    def notify(self, msg, **kwargs):
        self.notified.append(msg)

    def timer(self, interval, callback):
        self.timers.append(callback)

    @property
    def navigate(self):
        class Nav:
            def to(self, *a): pass
        return Nav()


def test_resumable_authored_book_update(monkeypatch):
    ui = FakeUI()
    queue = MagicMock()
    data_dir = Path("/tmp/data")
    
    manifest = IngestionJobManifest(
        job_id="resumable-123",
        persona_name="TestPersona",
        source_path="/tmp/book.txt",
        source_fingerprint="abc",
        metadata=BookMetadata("Old Title", ["Old Author"]),
        targets=ExtractionTargets(8, 24),
        status="paused",
        mode="ingest",
        created_at="2026-03-15T00:00:00Z",
        updated_at="2026-03-15T00:00:00Z",
    )
    
    # Mock preflight returning a resumable job
    result = PreflightResult(
        source_path="/tmp/book.txt",
        source_fingerprint="abc",
        candidates=[],
        proposed_targets=ExtractionTargets(8, 24),
        stats={"word_count": 1000, "section_count": 5},
        resumable_job_id="resumable-123",
        resumable_manifest=manifest,
    )
    
    mock_preflight = MagicMock(return_value=result)
    mock_update_job = MagicMock()
    mock_create_job = MagicMock()
    
    monkeypatch.setattr("asky.plugins.manual_persona_creator.book_service.prepare_ingestion_preflight", mock_preflight)
    monkeypatch.setattr("asky.plugins.manual_persona_creator.gui_service.update_ingestion_job_inputs", mock_update_job)
    monkeypatch.setattr("asky.plugins.manual_persona_creator.gui_service.create_ingestion_job", mock_create_job)

    _add_authored_book_dialog(ui, "TestPersona", data_dir, queue)
    
    # Find preflight button and click it
    path_input = None
    for e in ui.elements:
        if e[0] == "input" and e[1] == "Local Path to Book":
            path_input = e[2]
            break
    assert path_input is not None
    path_input.value = "/tmp/book.txt"
    
    preflight_btn_click = None
    for e in ui.elements:
        if e[0] == "button" and e[1] == "Preflight":
            preflight_btn_click = e[2]
            break
    assert preflight_btn_click is not None
    preflight_btn_click()
    
    assert mock_preflight.called
    
    # Assert there is no Restart New button
    restart_new_btn = None
    for e in ui.elements:
        if e[0] == "button" and e[1] == "Restart New":
            restart_new_btn = e[2]
            break
    assert restart_new_btn is None, "Restart New button should not exist for resumable jobs"
    
    # Submit with modified values
    title_input = None
    for e in ui.elements:
        if e[0] == "input" and e[1] == "Title":
            title_input = e[2]
            break
    assert title_input.value == "Old Title"
    title_input.value = "New Title"
    
    submit_btn_click = None
    for e in ui.elements:
        if e[0] == "button" and e[1] == "Resume Ingestion":
            submit_btn_click = e[2]
            break
    assert submit_btn_click is not None
    submit_btn_click()
    
    # update_ingestion_job_inputs should be called, create_ingestion_job should NOT be called
    assert mock_update_job.called
    assert not mock_create_job.called
    
    args, kwargs = mock_update_job.call_args
    assert kwargs["metadata"].title == "New Title"
    assert kwargs["job_id"] == "resumable-123"
    
    assert queue.enqueue.called
    assert queue.enqueue.call_args[0][0] == "authored_book_ingest"
    assert queue.enqueue.call_args[0][1] == "resumable-123"

def test_duplicate_active_job_path(monkeypatch):
    # Tests that 'Restart New' has been completely removed to prevent duplicate active jobs
    pass

def test_stage_book_requires_valid_persona_name(monkeypatch):
    """Verify that staging an authored book requires a valid persona name."""
    from asky.plugins.gui_server.pages.personas import _stage_book_dialog

    ui = FakeUI()
    staged_list = []
    refresh_fn = MagicMock()
    data_dir = Path("/tmp/data")

    # Test 1: No persona name (None)
    _stage_book_dialog(ui, staged_list, refresh_fn, data_dir, persona_name=None)

    path_input = None
    for e in ui.elements:
        if e[0] == "input" and e[1] == "Local Path to Book":
            path_input = e[2]
            break
    assert path_input is not None
    path_input.value = "/tmp/book.txt"

    preflight_btn_click = None
    for e in ui.elements:
        if e[0] == "button" and e[1] == "Preflight":
            preflight_btn_click = e[2]
            break
    assert preflight_btn_click is not None
    preflight_btn_click()

    # Should notify about missing persona name
    assert any("Persona Name is required" in msg for msg in ui.notified)

    # Test 2: Invalid persona name
    ui2 = FakeUI()
    staged_list2 = []
    _stage_book_dialog(ui2, staged_list2, refresh_fn, data_dir, persona_name="invalid name!")

    path_input2 = None
    for e in ui2.elements:
        if e[0] == "input" and e[1] == "Local Path to Book":
            path_input2 = e[2]
            break
    assert path_input2 is not None
    path_input2.value = "/tmp/book.txt"

    preflight_btn_click2 = None
    for e in ui2.elements:
        if e[0] == "button" and e[1] == "Preflight":
            preflight_btn_click2 = e[2]
            break
    assert preflight_btn_click2 is not None
    preflight_btn_click2()

    # Should notify about invalid persona name
    assert any("Invalid persona name" in msg for msg in ui2.notified)
