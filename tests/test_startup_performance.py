"""Startup performance guardrails for CLI responsiveness and memory usage."""

from __future__ import annotations

import statistics
import subprocess
import sys
import time
from pathlib import Path

import pytest

HELP_RUN_COUNT = 5
HELP_WARMUP_RUNS = 1
HELP_STARTUP_MEDIAN_MAX_SECONDS = 0.60

EDIT_MODEL_IDLE_SAMPLE_COUNT = 5
EDIT_MODEL_IDLE_SAMPLE_INTERVAL_SECONDS = 0.20
# Keep a practical cushion above typical local idle RSS (~20-30MB) while still
# catching meaningful regressions from eager heavy imports.
EDIT_MODEL_IDLE_MAX_RSS_KB = 80_000

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_help_once() -> float:
    """Execute `python -m asky --help` and return wall-clock seconds."""
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, "-m", "asky", "--help"],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    elapsed = time.perf_counter() - started
    assert "usage:" in completed.stdout.lower()
    return elapsed


def _get_rss_kb(pid: int) -> int:
    """Read process RSS in KiB via `ps`."""
    out = subprocess.check_output(
        ["ps", "-o", "rss=", "-p", str(pid)],
        text=True,
    ).strip()
    return int(out.splitlines()[-1].strip())


@pytest.mark.skipif(sys.platform == "win32", reason="RSS collection uses ps.")
def test_help_startup_time_guardrail():
    """Keep startup latency for `--help` in a bounded range."""
    for _ in range(HELP_WARMUP_RUNS):
        _run_help_once()

    samples = [_run_help_once() for _ in range(HELP_RUN_COUNT)]
    median_elapsed = statistics.median(samples)
    assert median_elapsed <= HELP_STARTUP_MEDIAN_MAX_SECONDS, (
        "Median help startup exceeded budget: "
        f"median={median_elapsed:.3f}s budget={HELP_STARTUP_MEDIAN_MAX_SECONDS:.3f}s "
        f"samples={[round(x, 3) for x in samples]}"
    )


@pytest.mark.skipif(sys.platform == "win32", reason="RSS collection uses ps.")
def test_edit_model_idle_memory_guardrail():
    """Ensure `--edit-model` idle RSS stays below threshold."""
    process = subprocess.Popen(
        [sys.executable, "-m", "asky", "--edit-model"],
        cwd=REPO_ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        rss_samples = []
        for _ in range(EDIT_MODEL_IDLE_SAMPLE_COUNT):
            if process.poll() is not None:
                stdout, stderr = process.communicate(timeout=1)
                raise AssertionError(
                    "Expected --edit-model process to remain idle awaiting input, "
                    f"but exited early with code={process.returncode}, "
                    f"stdout_tail={stdout[-500:]}, stderr_tail={stderr[-500:]}"
                )
            rss_samples.append(_get_rss_kb(process.pid))
            time.sleep(EDIT_MODEL_IDLE_SAMPLE_INTERVAL_SECONDS)

        peak_rss_kb = max(rss_samples)
        assert peak_rss_kb <= EDIT_MODEL_IDLE_MAX_RSS_KB, (
            "Idle RSS exceeded budget for --edit-model: "
            f"peak={peak_rss_kb}KiB budget={EDIT_MODEL_IDLE_MAX_RSS_KB}KiB "
            f"samples={rss_samples}"
        )
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
