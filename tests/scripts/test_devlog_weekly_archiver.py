"""Tests for weekly DEVLOG archive script."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import ModuleType


def _repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError("Unable to locate repository root")


def _load_module() -> ModuleType:
    script_path = _repo_root() / "scripts" / "devlog_weekly_archiver.py"
    spec = importlib.util.spec_from_file_location("devlog_weekly_archiver", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load devlog_weekly_archiver module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _entry_block(heading_date: str, title: str, repeat: int = 1) -> str:
    body_lines = "\n".join(f"- line {idx}" for idx in range(repeat))
    return f"## {heading_date}: {title}\n\n{body_lines}\n\n"


def test_parse_devlog_markdown_supports_mixed_heading_styles() -> None:
    mod = _load_module()
    content = (
        f"{mod.INTRO_BLOCK_START}\nold summary\n{mod.INTRO_BLOCK_END}\n\n"
        "# DEVLOG\n\n"
        "Intro text\n\n"
        "## 2026-03-03: Entry A\n\nA\n\n"
        "## 2026-03-02 - Entry B\n\nB\n"
    )

    parsed = mod.parse_devlog_markdown(content)

    assert parsed.preamble.startswith("# DEVLOG")
    assert len(parsed.entries) == 2
    assert parsed.entries[0].entry_date == date(2026, 3, 3)
    assert parsed.entries[1].entry_date == date(2026, 3, 2)


def test_build_archive_batches_merges_until_target_line_count() -> None:
    mod = _load_module()

    entries = [
        mod.DevlogEntry(date(2026, 2, 24), "h1", _entry_block("2026-02-24", "A", repeat=260)),
        mod.DevlogEntry(date(2026, 2, 23), "h2", _entry_block("2026-02-23", "B", repeat=260)),
        mod.DevlogEntry(date(2026, 2, 16), "h3", _entry_block("2026-02-16", "C", repeat=260)),
    ]

    batches = mod.build_archive_batches(entries, min_lines=750)

    assert len(batches) == 1
    assert batches[0].line_count >= 750


def test_write_archive_batches_uses_collision_safe_filenames(tmp_path: Path) -> None:
    mod = _load_module()
    output_dir = tmp_path / "devlog" / "archive"
    output_dir.mkdir(parents=True)
    creation_date = date(2026, 3, 3)
    (output_dir / "2026.03.03.md").write_text("existing", encoding="utf-8")

    batch_entries = [
        mod.DevlogEntry(date(2026, 2, 24), "h1", _entry_block("2026-02-24", "A", repeat=5)),
    ]
    batches = [mod.ArchiveBatch(entries=batch_entries), mod.ArchiveBatch(entries=batch_entries)]

    written = mod.write_archive_batches(
        batches,
        output_dir=output_dir,
        source_name="DEVLOG.md",
        creation_date=creation_date,
    )

    assert [path.name for path in written] == ["2026.03.03-02.md", "2026.03.03-03.md"]


def test_process_devlog_noop_when_under_size_threshold(tmp_path: Path, monkeypatch) -> None:
    mod = _load_module()
    source = tmp_path / "DEVLOG.md"
    source.write_text(_entry_block("2026-03-03", "Tiny", repeat=2), encoding="utf-8")

    called = {"value": False}

    def _fake_run(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        called["value"] = True
        return subprocess.CompletedProcess(args=["asky"], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)

    rc = mod.process_devlog(source, today=date(2026, 3, 3))

    assert rc == 0
    assert called["value"] is False


def test_process_devlog_archives_old_entries_and_updates_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    mod = _load_module()
    source = tmp_path / "DEVLOG.md"
    archive_dir = tmp_path / "devlog" / "archive"

    big_old_block = _entry_block("2026-02-20", "Older", repeat=2400)
    current_block = _entry_block("2026-03-03", "Current", repeat=10)
    source.write_text("# DEVLOG\n\n" + current_block + big_old_block, encoding="utf-8")

    monkeypatch.setattr(mod, "ARCHIVE_OUTPUT_DIR", archive_dir)
    monkeypatch.setattr(mod, "SPLIT_THRESHOLD_BYTES", 1)

    def _fake_run(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        return subprocess.CompletedProcess(
            args=["asky"],
            returncode=0,
            stdout="<intro>Weekly intro paragraph\n\n- item 1\n- item 2</intro>",
            stderr="",
        )

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)

    rc = mod.process_devlog(source, today=date(2026, 3, 3))

    assert rc == 0
    updated = source.read_text(encoding="utf-8")
    assert mod.INTRO_BLOCK_START in updated
    assert "## 2026-03-03: Current" in updated
    assert "## 2026-02-20: Older" not in updated

    archive_files = sorted(archive_dir.glob("*.md"))
    assert len(archive_files) == 1
    archive_text = archive_files[0].read_text(encoding="utf-8")
    assert "## 2026-02-20: Older" in archive_text


def test_main_returns_nonzero_when_asky_summary_fails(tmp_path: Path, monkeypatch) -> None:
    mod = _load_module()
    source = tmp_path / "DEVLOG.md"
    source.write_text(
        "# DEVLOG\n\n" + _entry_block("2026-03-03", "Current", repeat=20) + _entry_block("2026-02-20", "Older", repeat=2400),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "ARCHIVE_OUTPUT_DIR", tmp_path / "devlog" / "archive")
    monkeypatch.setattr(mod, "SPLIT_THRESHOLD_BYTES", 1)

    def _failing_run(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise subprocess.CalledProcessError(returncode=7, cmd=["asky"], stderr="boom")

    monkeypatch.setattr(mod.subprocess, "run", _failing_run)

    rc = mod.main([str(source)])

    assert rc == 1
