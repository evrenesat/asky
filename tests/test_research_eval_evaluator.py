import sqlite3

from asky.evals.research_pipeline.evaluator import (
    _create_unique_output_dir,
    _initialize_runtime_storage,
    _summarize_run,
)
from asky.evals.research_pipeline.matrix import RunProfile
from asky.evals.research_pipeline.runtime_isolation import (
    build_runtime_paths,
    isolated_asky_runtime,
)


def test_create_unique_output_dir_adds_suffix_on_collision(tmp_path, monkeypatch):
    # Freeze timestamp so both allocations target the same base directory name.
    monkeypatch.setattr(
        "asky.evals.research_pipeline.evaluator._result_timestamp",
        lambda: "20260209_120000",
    )

    first = _create_unique_output_dir(tmp_path)
    second = _create_unique_output_dir(tmp_path)

    assert first.name == "20260209_120000"
    assert second.name == "20260209_120000_001"


def test_summarize_run_counts_errors_and_halts():
    run = RunProfile(id="r1", model_alias="gf", research_mode=True)
    case_results = [
        {"pass": True, "elapsed_ms": 10.0, "error": None, "halted": False},
        {
            "pass": False,
            "elapsed_ms": 20.0,
            "error": "RuntimeError: boom",
            "halted": False,
        },
        {"pass": False, "elapsed_ms": 30.0, "error": None, "halted": True},
    ]

    summary = _summarize_run(run, case_results)

    assert summary["total_cases"] == 3
    assert summary["passed_cases"] == 1
    assert summary["failed_cases"] == 2
    assert summary["error_cases"] == 1
    assert summary["halted_cases"] == 1


def test_initialize_runtime_storage_creates_sessions_table(tmp_path):
    runtime_paths = build_runtime_paths(tmp_path / "run")

    with isolated_asky_runtime(runtime_paths):
        _initialize_runtime_storage()
        conn = sqlite3.connect(runtime_paths.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='sessions'
            """
        )
        row = cursor.fetchone()
        conn.close()

    assert row is not None
