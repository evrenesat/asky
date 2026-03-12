"""Tests for research quality gate script path scoping."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError("Unable to locate repository root")


def _write_executable(path: Path, contents: str) -> None:
    path.write_text(contents, encoding="utf-8")
    path.chmod(0o755)


def _run_gate_with_changed_files(tmp_path: Path, changed_files: list[str]) -> subprocess.CompletedProcess[str]:
    repo_root = _repo_root()
    script_path = repo_root / "scripts" / "run_research_quality_gate.sh"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    log_path = tmp_path / "uv.log"
    changed_output = "\n".join(changed_files)
    name_status_output = "\n".join(f"M\t{path}" for path in changed_files)

    _write_executable(
        bin_dir / "git",
        "#!/usr/bin/env bash\n"
        "if [[ \"$1\" == \"diff\" && \"$2\" == \"--name-only\" ]]; then\n"
        f"  printf '%s\\n' '{changed_output}'\n"
        "  exit 0\n"
        "fi\n"
        "if [[ \"$1\" == \"diff\" && \"$2\" == \"--name-status\" ]]; then\n"
        f"  printf '%s\\n' '{name_status_output}'\n"
        "  exit 0\n"
        "fi\n"
        "echo \"unexpected git args: $*\" >&2\n"
        "exit 1\n",
    )
    _write_executable(
        bin_dir / "uv",
        "#!/usr/bin/env bash\n"
        "if [[ \"$1\" == \"run\" && \"$2\" == \"python\" && \"$3\" == \"-m\" && \"$4\" == \"asky.testing.feature_domains\" ]]; then\n"
        f"  printf '%s\\n' \"$*\" >> '{log_path}'\n"
        "  shift 2\n"
        "  exec python \"$@\"\n"
        "fi\n"
        f"printf '%s\\n' \"$*\" >> '{log_path}'\n"
        "exit 0\n",
    )

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["OPENROUTER_API_KEY"] = "test-openrouter-key"
    env["PYTHONPATH"] = f"{repo_root / 'src'}:{env.get('PYTHONPATH', '')}"

    completed = subprocess.run(
        [str(script_path), "--base", "A", "--head", "B"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return completed


def test_gate_runs_for_pyproject_policy_changes(tmp_path: Path) -> None:
    completed = _run_gate_with_changed_files(tmp_path, ["pyproject.toml"])

    assert completed.returncode == 0
    log_text = (tmp_path / "uv.log").read_text(encoding="utf-8")
    assert "python -m asky.testing.feature_domains domain-active --domain research --base A --head B --repo-root ." in log_text
    assert "tests/integration/cli_recorded -q -o addopts=-n0 --record-mode=none -m recorded_cli and not real_recorded_cli" in log_text
    assert "tests/integration/cli_recorded -q -o addopts=-n0 --record-mode=none -m real_recorded_cli" in log_text
    assert "tests/integration/cli_live -q -o addopts=-n0 -m live_research" in log_text


def test_gate_skips_for_unrelated_changes(tmp_path: Path) -> None:
    completed = _run_gate_with_changed_files(tmp_path, ["README.md"])

    assert completed.returncode == 0
    assert "skipping research quality gate" in completed.stdout.lower()
    log_text = (tmp_path / "uv.log").read_text(encoding="utf-8")
    assert "python -m asky.testing.feature_domains domain-active --domain research --base A --head B --repo-root ." in log_text
    assert "tests/integration/cli_recorded" not in log_text
    assert "tests/integration/cli_live" not in log_text
