"""Tests for the release version inspection script."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError("Unable to locate repository root")


def _parse_github_output(path: Path) -> dict[str, str]:
    outputs: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        key, value = line.split("=", 1)
        outputs[key] = value
    return outputs


def _run_release_version_script(
    tmp_path: Path,
    current_toml: str,
    *,
    previous_toml: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, object], dict[str, str]]:
    repo_root = _repo_root()
    script_path = repo_root / "scripts" / "release_version_info.py"
    current_path = tmp_path / "current.toml"
    current_path.write_text(current_toml, encoding="utf-8")

    command = [sys.executable, str(script_path), "--current", str(current_path)]
    if previous_toml is not None:
        previous_path = tmp_path / "previous.toml"
        previous_path.write_text(previous_toml, encoding="utf-8")
        command.extend(["--previous", str(previous_path)])

    output_path = tmp_path / "github_output.txt"
    env = os.environ.copy()
    env["GITHUB_OUTPUT"] = str(output_path)
    completed = subprocess.run(
        command,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    payload = json.loads(completed.stdout)
    outputs = _parse_github_output(output_path)
    return completed, payload, outputs


def test_release_version_info_marks_version_bump_for_release(tmp_path: Path) -> None:
    completed, payload, outputs = _run_release_version_script(
        tmp_path,
        """
[project]
name = "asky-cli"
version = "1.2.4"
""",
        previous_toml="""
[project]
name = "asky-cli"
version = "1.2.3"
""",
    )

    assert completed.returncode == 0
    assert payload == {
        "previous_version": "1.2.3",
        "should_release": True,
        "tag": "v1.2.4",
        "version": "1.2.4",
    }
    assert outputs == {
        "previous_version": "1.2.3",
        "should_release": "true",
        "tag": "v1.2.4",
        "version": "1.2.4",
    }


def test_release_version_info_skips_when_version_is_unchanged(tmp_path: Path) -> None:
    completed, payload, outputs = _run_release_version_script(
        tmp_path,
        """
[project]
name = "asky-cli"
version = "2.0.0"
""",
        previous_toml="""
[project]
name = "asky-cli"
version = "2.0.0"
""",
    )

    assert completed.returncode == 0
    assert payload["should_release"] is False
    assert payload["previous_version"] == "2.0.0"
    assert outputs["should_release"] == "false"
    assert outputs["tag"] == "v2.0.0"


def test_release_version_info_treats_missing_previous_file_as_initial_release(
    tmp_path: Path,
) -> None:
    completed, payload, outputs = _run_release_version_script(
        tmp_path,
        """
[project]
name = "asky-cli"
version = "0.1.0"
""",
    )

    assert completed.returncode == 0
    assert payload["should_release"] is True
    assert payload["previous_version"] is None
    assert outputs["previous_version"] == ""
    assert outputs["tag"] == "v0.1.0"


def test_release_version_info_supports_poetry_metadata(tmp_path: Path) -> None:
    completed, payload, outputs = _run_release_version_script(
        tmp_path,
        """
[tool.poetry]
name = "asky-cli"
version = "3.1.5"
""",
        previous_toml="""
[tool.poetry]
name = "asky-cli"
version = "3.1.4"
""",
    )

    assert completed.returncode == 0
    assert payload["version"] == "3.1.5"
    assert payload["should_release"] is True
    assert outputs["tag"] == "v3.1.5"
