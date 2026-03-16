"""Tests for release workflow dependency selection."""

from __future__ import annotations

import tomllib
from pathlib import Path


def _repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError("Unable to locate repository root")


def test_mac_only_extras_are_guarded_by_platform_markers() -> None:
    pyproject_path = _repo_root() / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    optional = data["project"]["optional-dependencies"]

    assert "iterm2>=2.13; sys_platform == 'darwin'" in optional["test"]
    assert "mlx-whisper>=0.4.2; sys_platform == 'darwin'" in optional["mlx-whisper"]
    assert "iterm2>=2.13; sys_platform == 'darwin'" in optional["mac"]
    assert "mlx-whisper>=0.4.2; sys_platform == 'darwin'" in optional["mac"]
    assert "rumps>=0.4.0; sys_platform == 'darwin'" in optional["mac"]
    assert "slixmpp>=1.11.0" in optional["mac"]


def test_publish_workflow_uses_linux_safe_extras() -> None:
    workflow_path = _repo_root() / ".github" / "workflows" / "publish-package.yml"
    workflow_text = workflow_path.read_text(encoding="utf-8")

    assert "uv sync --all-extras --group dev" not in workflow_text
    assert "uv sync --group dev --extra tray --extra xmpp --extra playwright" in workflow_text
