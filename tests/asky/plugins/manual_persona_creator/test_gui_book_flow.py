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


def test_authored_book_dialog_successful_flow(monkeypatch):
    ui = FakeUI()
    queue = MagicMock()
    data_dir = Path("/tmp/data")
    
    # Mock preflight and job creation
    result = PreflightResult(
        source_path="/tmp/book.txt",
        source_fingerprint="abc",
        candidates=[MetadataCandidate(BookMetadata("Title", ["Author"]), 1.0)],
        proposed_targets=ExtractionTargets(8, 24),
        stats={"word_count": 1000, "section_count": 5},
    )
    
    mock_preflight = MagicMock(return_value=result)
    mock_create_job = MagicMock(return_value="job-123")
    
    monkeypatch.setattr("asky.plugins.manual_persona_creator.book_service.prepare_ingestion_preflight", mock_preflight)
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
    
    # After preflight, new elements are added (metadata fields)
    title_input = None
    for e in ui.elements:
        if e[0] == "input" and e[1] == "Title":
            title_input = e[2]
            break
    
    if title_input is None:
        print(f"ELEMENTS: {[ (e[0], e[1]) for e in ui.elements ]}")
        pytest.fail("Title input not found after preflight")

    assert title_input.value == "Title"
    
    # Submit
    submit_btn_click = None
    for e in ui.elements:
        if e[0] == "button" and e[1] == "Start Ingestion":
            submit_btn_click = e[2]
            break
    assert submit_btn_click is not None
    submit_btn_click()
    
    assert mock_create_job.called
    args, kwargs = mock_create_job.call_args
    assert kwargs["metadata"].title == "Title"
    assert kwargs["source_path"] == "/tmp/book.txt"
    
    assert queue.enqueue.called
    assert queue.enqueue.call_args[0][0] == "authored_book_ingest"
    assert queue.enqueue.call_args[0][1] == "job-123"

def test_validation_rejects_blank_authors_and_negative_targets(monkeypatch):
    ui = FakeUI()
    queue = MagicMock()
    data_dir = Path("/tmp/data")
    
    # Mock preflight
    result = PreflightResult(
        source_path="/tmp/book.txt",
        source_fingerprint="abc",
        candidates=[],
        proposed_targets=ExtractionTargets(8, 24),
        stats={"word_count": 1000, "section_count": 5},
    )
    
    mock_preflight = MagicMock(return_value=result)
    mock_create_job = MagicMock()
    mock_update_job = MagicMock()
    
    monkeypatch.setattr("asky.plugins.manual_persona_creator.book_service.prepare_ingestion_preflight", mock_preflight)
    monkeypatch.setattr("asky.plugins.manual_persona_creator.gui_service.create_ingestion_job", mock_create_job)
    monkeypatch.setattr("asky.plugins.manual_persona_creator.gui_service.update_ingestion_job_inputs", mock_update_job)

    _add_authored_book_dialog(ui, "TestPersona", data_dir, queue)
    
    # Preflight
    path_input = [e[2] for e in ui.elements if e[0] == "input" and e[1] == "Local Path to Book"][0]
    path_input.value = "/tmp/book.txt"
    [e[2] for e in ui.elements if e[0] == "button" and e[1] == "Preflight"][0]()
    
    title_input = [e[2] for e in ui.elements if e[0] == "input" and e[1] == "Title"][0]
    authors_input = [e[2] for e in ui.elements if e[0] == "input" and e[1] == "Authors"][0]
    topic_input = [e[2] for e in ui.elements if e[0] == "number" and e[1] == "Topic Target"][0]
    vp_input = [e[2] for e in ui.elements if e[0] == "number" and e[1] == "Viewpoint Target"][0]
    
    # Empty author
    title_input.value = "Valid Title"
    authors_input.value = "   ,   "
    topic_input.value = 1
    vp_input.value = 1
    
    submit_btn_click = [e[2] for e in ui.elements if e[0] == "button" and e[1] == "Start Ingestion"][0]
    submit_btn_click()
    
    assert "At least one author must be provided." in ui.notified
    assert not mock_create_job.called
    assert not mock_update_job.called
    assert not queue.enqueue.called
    
    # Empty title
    ui.notified.clear()
    title_input.value = "   "
    authors_input.value = "Valid Author"
    submit_btn_click()
    assert "Title cannot be blank." in ui.notified
    assert not mock_create_job.called
    
    # Zero targets
    ui.notified.clear()
    title_input.value = "Valid Title"
    topic_input.value = 0
    submit_btn_click()
    assert "Topic target must be at least 1." in ui.notified
    assert not mock_create_job.called
    
    # Negative targets
    ui.notified.clear()
    topic_input.value = 8
    vp_input.value = -5
    submit_btn_click()
    assert "Viewpoint target must be at least 1." in ui.notified
    assert not mock_create_job.called

def test_no_candidate_requires_explicit_input(monkeypatch):
    ui = FakeUI()
    queue = MagicMock()
    data_dir = Path("/tmp/data")
    
    result = PreflightResult(
        source_path="/tmp/book.txt",
        source_fingerprint="abc",
        candidates=[],
        proposed_targets=ExtractionTargets(8, 24),
        stats={"word_count": 1000, "section_count": 5},
    )
    
    mock_preflight = MagicMock(return_value=result)
    monkeypatch.setattr("asky.plugins.manual_persona_creator.book_service.prepare_ingestion_preflight", mock_preflight)

    _add_authored_book_dialog(ui, "TestPersona", data_dir, queue)
    path_input = [e[2] for e in ui.elements if e[0] == "input" and e[1] == "Local Path to Book"][0]
    path_input.value = "/tmp/book.txt"
    [e[2] for e in ui.elements if e[0] == "button" and e[1] == "Preflight"][0]()
    
    title_input = [e[2] for e in ui.elements if e[0] == "input" and e[1] == "Title"][0]
    authors_input = [e[2] for e in ui.elements if e[0] == "input" and e[1] == "Authors"][0]
    
    assert title_input.value == ""
    assert authors_input.value == ""
