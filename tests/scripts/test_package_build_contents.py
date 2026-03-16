"""Tests for published package contents."""

from __future__ import annotations

import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest


def _repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError("Unable to locate repository root")


def _build_artifacts(tmp_path: Path) -> tuple[Path, Path]:
    repo_root = _repo_root()
    out_dir = tmp_path / "dist"
    completed = subprocess.run(
        ["uv", "build", "--clear", "--no-create-gitignore", "-o", str(out_dir)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout

    wheel_path = next(out_dir.glob("*.whl"))
    sdist_path = next(out_dir.glob("*.tar.gz"))
    return wheel_path, sdist_path


@pytest.mark.slow
def test_build_artifacts_only_ship_runtime_package_files(tmp_path: Path) -> None:
    wheel_path, sdist_path = _build_artifacts(tmp_path)

    with zipfile.ZipFile(wheel_path) as archive:
        wheel_names = set(archive.namelist())

    assert "asky/data/icons/asky.icns" in wheel_names
    assert "asky/data/icons/asky_icon_mono.ico" in wheel_names
    assert "asky/plugins/manual_persona_creator/docs/create_persona.md" in wheel_names
    assert "asky/testing/feature_domains.py" not in wheel_names
    assert "asky/tasks/add.md" not in wheel_names
    assert not any(name.endswith("AGENTS.md") for name in wheel_names)

    with tarfile.open(sdist_path, "r:gz") as archive:
        sdist_names = {member.name for member in archive.getmembers() if member.name}

    sdist_root = sdist_path.name.removesuffix(".tar.gz")
    assert f"{sdist_root}/pyproject.toml" in sdist_names
    assert f"{sdist_root}/README.md" in sdist_names
    assert f"{sdist_root}/src/asky/data/icons/asky.icns" in sdist_names
    assert f"{sdist_root}/src/asky/data/icons/asky_icon_mono.ico" in sdist_names
    assert f"{sdist_root}/ARCHITECTURE.md" not in sdist_names
    assert not any(name.endswith("AGENTS.md") for name in sdist_names)
    forbidden_root_prefixes = (
        f"{sdist_root}/.github/",
        f"{sdist_root}/.hypothesis/",
        f"{sdist_root}/assets/",
        f"{sdist_root}/devlog/",
        f"{sdist_root}/docs/",
        f"{sdist_root}/plans/",
        f"{sdist_root}/tests/",
    )
    assert not any(
        name.startswith(prefix)
        for name in sdist_names
        for prefix in forbidden_root_prefixes
    )
