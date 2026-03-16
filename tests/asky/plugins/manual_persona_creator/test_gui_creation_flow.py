"""Tests for /personas/new browser creation flow."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from asky.plugins.gui_server.pages.personas import _stage_manual_source_dialog, _stage_book_dialog
from asky.plugins.manual_persona_creator.creation_service import (
    StagedSourceSpec,
    PersonaCreationSpecs,
    create_persona_from_scratch,
)


class FakeUI:
    """Lightweight fake UI harness for testing page dialogs."""

    def __init__(self):
        self.dialog_obj = MagicMock()
        self.dialog_obj.open = MagicMock()
        self.dialog_obj.close = MagicMock()
        self.dialog_obj.__enter__ = lambda s: s
        self.dialog_obj.__exit__ = lambda s, *a: None

        self.notified = []
        self.navigated = []
        self.elements = []

    def dialog(self):
        return self.dialog_obj

    def card(self):
        class Context:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def classes(self, *s):
                return self

        return Context()

    def column(self):
        class Context:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def classes(self, *s):
                return self

            def hide(self):
                return self

            def show(self):
                return self

            def clear(self):
                return self

            def visible(self):
                return True

        return Context()

    def label(self, text, **kwargs):
        self.elements.append(("label", text, None))
        return self

    def classes(self, *args, **kwargs):
        return self

    def props(self, *args, **kwargs):
        return self

    def input(self, label, value=None):
        class Input:
            def __init__(self, v):
                self.value = v

            def classes(self, *s):
                return self

            def props(self, *s):
                return self

        obj = Input(value)
        self.elements.append(("input", label, obj))
        return obj

    def number(self, label, value=None):
        class Number:
            def __init__(self, v):
                self.value = v

            def classes(self, *s):
                return self

            def props(self, *s):
                return self

        obj = Number(value)
        self.elements.append(("number", label, obj))
        return obj

    def button(self, text=None, on_click=None, **kwargs):
        self.elements.append(("button", text, on_click))

        class Btn:
            def props(self, *a, **kw):
                return self

            def hide(self):
                pass

            def show(self):
                pass

        return Btn()

    def row(self):
        class Context:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def classes(self, *s):
                return self

        return Context()

    def separator(self):
        pass

    def select(self, options, value=None, label=None):
        class Select:
            def __init__(self, opts, v):
                self.value = v or (opts[0] if opts else None)
                self.options = opts

            def classes(self, *s):
                return self

            def props(self, *s):
                return self

        obj = Select(options, value)
        self.elements.append(("select", label, obj))
        return obj

    def notify(self, msg, **kwargs):
        self.notified.append(msg)

    @property
    def navigate(self):
        class Nav:
            def to(self, *a):
                pass

        return Nav()


def test_manual_source_staging_validates_kind():
    """Verify manual-source staging validates the source kind."""
    ui = FakeUI()
    staged_list = []
    refresh_fn = MagicMock()

    _stage_manual_source_dialog(ui, staged_list, refresh_fn)

    # Find inputs
    path_input = None
    kind_select = None
    for e in ui.elements:
        if e[0] == "input" and e[1] == "File or Directory Path":
            path_input = e[2]
        elif e[0] == "select" and e[1] == "Kind":
            kind_select = e[2]

    assert path_input is not None
    assert kind_select is not None

    # Set invalid kind (by mocking a valid path first)
    path_input.value = "/tmp/test.txt"
    kind_select.value = "invalid_kind"

    # Find and click stage button
    stage_btn = None
    for e in ui.elements:
        if e[0] == "button" and e[1] == "Stage Source":
            stage_btn = e[2]
            break

    assert stage_btn is not None
    stage_btn()

    # Should have notified about unsupported kind
    assert any("Unsupported source kind" in msg for msg in ui.notified)
    assert len(staged_list) == 0  # Nothing staged


def test_manual_source_staging_validates_path():
    """Verify manual-source staging validates the source path existence."""
    ui = FakeUI()
    staged_list = []
    refresh_fn = MagicMock()

    _stage_manual_source_dialog(ui, staged_list, refresh_fn)

    # Find inputs
    path_input = None
    kind_select = None
    for e in ui.elements:
        if e[0] == "input" and e[1] == "File or Directory Path":
            path_input = e[2]
        elif e[0] == "select" and e[1] == "Kind":
            kind_select = e[2]

    assert path_input is not None
    assert kind_select is not None

    # Set nonexistent path
    path_input.value = "/nonexistent/path/to/file.txt"
    kind_select.value = "article"

    # Find and click stage button
    stage_btn = None
    for e in ui.elements:
        if e[0] == "button" and e[1] == "Stage Source":
            stage_btn = e[2]
            break

    assert stage_btn is not None
    stage_btn()

    # Should have notified about missing path
    assert any("does not exist" in msg for msg in ui.notified)
    assert len(staged_list) == 0  # Nothing staged


def test_manual_source_staging_success(tmp_path):
    """Verify manual-source staging succeeds with valid kind and path."""
    ui = FakeUI()
    staged_list = []
    refresh_fn = MagicMock()

    # Create a real file
    test_file = tmp_path / "article.txt"
    test_file.write_text("Test article content")

    _stage_manual_source_dialog(ui, staged_list, refresh_fn)

    # Find inputs
    path_input = None
    kind_select = None
    for e in ui.elements:
        if e[0] == "input" and e[1] == "File or Directory Path":
            path_input = e[2]
        elif e[0] == "select" and e[1] == "Kind":
            kind_select = e[2]

    assert path_input is not None
    assert kind_select is not None

    # Set valid path and kind
    path_input.value = str(test_file)
    kind_select.value = "article"

    # Find and click stage button
    stage_btn = None
    for e in ui.elements:
        if e[0] == "button" and e[1] == "Stage Source":
            stage_btn = e[2]
            break

    assert stage_btn is not None
    stage_btn()

    # Should have staged the source
    assert len(staged_list) == 1
    assert staged_list[0].kind == "article"
    assert staged_list[0].path == str(test_file)
    refresh_fn.assert_called_once()


def test_manual_source_kinds_locked():
    """Verify manual-source dialog exposes only locked offline kinds."""
    ui = FakeUI()
    staged_list = []
    refresh_fn = MagicMock()

    _stage_manual_source_dialog(ui, staged_list, refresh_fn)

    # Find the kind select
    kind_select = None
    for e in ui.elements:
        if e[0] == "select" and e[1] == "Kind":
            kind_select = e[2]
            break

    assert kind_select is not None
    expected_kinds = {"biography", "autobiography", "interview", "article", "essay", "speech", "notes", "posts"}
    actual_kinds = set(kind_select.options)

    assert actual_kinds == expected_kinds
    assert "web_page" not in actual_kinds


def test_persona_creation_with_valid_sources(tmp_path, monkeypatch):
    """Verify persona creation flow accepts staged manual sources after validation."""
    from asky.plugins.manual_persona_creator import source_service

    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # Create a real source file
    source_file = data_dir / "article.txt"
    source_file.write_text("Test article")

    # Mock source job creation
    monkeypatch.setattr(
        "asky.plugins.manual_persona_creator.source_service.create_source_ingestion_job",
        MagicMock(return_value="job-article-123"),
    )

    specs = PersonaCreationSpecs(
        name="test-persona",
        description="Test",
        behavior_prompt="Test behavior",
        initial_sources=[
            StagedSourceSpec(
                kind="article",
                path=str(source_file),
            )
        ],
    )

    name, jobs = create_persona_from_scratch(data_dir, specs)

    assert name == "test-persona"
    assert len(jobs) == 1
    assert jobs[0].job_id == "job-article-123"
