import sqlite3
from types import SimpleNamespace

from asky.evals.research_pipeline.dataset import (
    DatasetDocument,
    DatasetExpected,
    DatasetSpec,
    DatasetTestCase,
)
from asky.evals.research_pipeline.evaluator import (
    RUN_RESULTS_MARKDOWN_FILENAME,
    SnapshotManifest,
    _build_markdown_report,
    _build_results_markdown,
    _create_unique_output_dir,
    _initialize_runtime_storage,
    _summarize_run,
    regenerate_report,
    run_evaluation_matrix,
)
from asky.evals.research_pipeline.matrix import MatrixSpec, RunProfile
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
    assert summary["token_usage_totals"]["main"]["input_tokens"] == 0
    assert summary["token_usage_totals"]["main"]["output_tokens"] == 0
    assert summary["token_usage_totals"]["main"]["total_tokens"] == 0
    assert summary["token_usage_totals"]["summarizer"]["input_tokens"] == 0
    assert summary["token_usage_totals"]["summarizer"]["output_tokens"] == 0
    assert summary["token_usage_totals"]["summarizer"]["total_tokens"] == 0
    assert summary["token_usage_totals"]["audit_planner"]["input_tokens"] == 0
    assert summary["token_usage_totals"]["audit_planner"]["output_tokens"] == 0
    assert summary["token_usage_totals"]["audit_planner"]["total_tokens"] == 0


def test_summarize_run_aggregates_token_usage_totals():
    run = RunProfile(id="r1", model_alias="gf", research_mode=True)
    case_results = [
        {
            "pass": True,
            "elapsed_ms": 10.0,
            "error": None,
            "halted": False,
            "token_usage": {
                "main": {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
                "summarizer": {
                    "input_tokens": 3,
                    "output_tokens": 1,
                    "total_tokens": 4,
                },
                "audit_planner": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                },
            },
        },
        {
            "pass": True,
            "elapsed_ms": 20.0,
            "error": None,
            "halted": False,
            "token_usage": {
                "main": {"input_tokens": 7, "output_tokens": 2, "total_tokens": 9},
                "summarizer": {
                    "input_tokens": 4,
                    "output_tokens": 2,
                    "total_tokens": 6,
                },
                "audit_planner": {
                    "input_tokens": 1,
                    "output_tokens": 0,
                    "total_tokens": 1,
                },
            },
        },
    ]

    summary = _summarize_run(run, case_results)

    assert summary["token_usage_totals"]["main"]["input_tokens"] == 17
    assert summary["token_usage_totals"]["main"]["output_tokens"] == 6
    assert summary["token_usage_totals"]["main"]["total_tokens"] == 23
    assert summary["token_usage_totals"]["summarizer"]["input_tokens"] == 7
    assert summary["token_usage_totals"]["summarizer"]["output_tokens"] == 3
    assert summary["token_usage_totals"]["summarizer"]["total_tokens"] == 10
    assert summary["token_usage_totals"]["audit_planner"]["input_tokens"] == 1
    assert summary["token_usage_totals"]["audit_planner"]["output_tokens"] == 0
    assert summary["token_usage_totals"]["audit_planner"]["total_tokens"] == 1


def test_summarize_run_aggregates_tool_call_breakdown():
    run = RunProfile(
        id="r1",
        model_alias="gf",
        research_mode=True,
        disabled_tools={"web_search"},
    )
    case_results = [
        {
            "pass": True,
            "elapsed_ms": 10.0,
            "error": None,
            "halted": False,
            "tool_calls": [
                {
                    "tool_name": "get_relevant_content",
                    "arguments": {"query": "tls", "urls": ["a"]},
                },
                {
                    "tool_name": "get_relevant_content",
                    "arguments": {"query": "tls", "urls": ["a"]},
                },
                {"tool_name": "save_finding", "arguments": {"text": "x"}},
            ],
        },
        {
            "pass": True,
            "elapsed_ms": 11.0,
            "error": None,
            "halted": False,
            "tool_calls": [
                {
                    "tool_name": "get_relevant_content",
                    "arguments": {"query": "http", "urls": ["b"]},
                }
            ],
        },
    ]

    summary = _summarize_run(run, case_results)

    assert summary["disabled_tools"] == ["web_search"]
    assert summary["tool_call_counts"]["get_relevant_content"] == 3
    assert summary["tool_call_counts"]["save_finding"] == 1
    assert summary["tool_call_breakdown"][0]["tool_name"] == "get_relevant_content"
    assert summary["tool_call_breakdown"][0]["count"] == 2


def test_summarize_run_aggregates_timing_totals():
    run = RunProfile(id="r1", model_alias="gf", research_mode=True)
    case_results = [
        {
            "pass": True,
            "elapsed_ms": 10.0,
            "error": None,
            "halted": False,
            "timings_ms": {
                "case_total_ms": 10.0,
                "source_prepare_ms": 1.0,
                "client_init_ms": 0.5,
                "run_turn_ms": 8.0,
                "llm_total_ms": 5.0,
                "tool_total_ms": 2.0,
                "local_ingestion_ms": 0.4,
                "shortlist_ms": 0.3,
                "llm_calls": 2,
                "tool_calls": 1,
                "local_ingestion_calls": 1,
                "shortlist_calls": 1,
            },
        },
        {
            "pass": True,
            "elapsed_ms": 20.0,
            "error": None,
            "halted": False,
            "timings_ms": {
                "case_total_ms": 20.0,
                "source_prepare_ms": 2.0,
                "client_init_ms": 1.0,
                "run_turn_ms": 16.0,
                "llm_total_ms": 11.0,
                "tool_total_ms": 3.0,
                "local_ingestion_ms": 0.0,
                "shortlist_ms": 0.7,
                "llm_calls": 3,
                "tool_calls": 2,
                "local_ingestion_calls": 0,
                "shortlist_calls": 1,
            },
        },
    ]

    summary = _summarize_run(run, case_results)

    assert summary["timing_totals_ms"]["case_total_ms"] == 30.0
    assert summary["timing_totals_ms"]["source_prepare_ms"] == 3.0
    assert summary["timing_totals_ms"]["client_init_ms"] == 1.5
    assert summary["timing_totals_ms"]["run_turn_ms"] == 24.0
    assert summary["timing_totals_ms"]["llm_total_ms"] == 16.0
    assert summary["timing_totals_ms"]["tool_total_ms"] == 5.0
    assert summary["timing_totals_ms"]["local_ingestion_ms"] == 0.4
    assert summary["timing_totals_ms"]["shortlist_ms"] == 1.0
    assert summary["timing_averages_ms"]["case_total_ms"] == 15.0
    assert summary["timing_averages_ms"]["run_turn_ms"] == 12.0
    assert summary["timing_counts"]["llm_calls"] == 5
    assert summary["timing_counts"]["tool_calls"] == 3
    assert summary["timing_counts"]["local_ingestion_calls"] == 1
    assert summary["timing_counts"]["shortlist_calls"] == 2


def test_build_markdown_report_includes_role_token_columns(tmp_path):
    report_text = _build_markdown_report(
        dataset=SimpleNamespace(id="dataset-id"),
        output_dir=tmp_path,
        run_summaries=[
            {
                "run_id": "r1",
                "model_alias": "gf",
                "research_mode": True,
                "source_provider": "local_snapshot",
                "total_cases": 2,
                "passed_cases": 2,
                "failed_cases": 0,
                "error_cases": 0,
                "halted_cases": 0,
                "pass_rate": 1.0,
                "avg_elapsed_ms": 12.5,
                "disabled_tools": ["web_search"],
                "tool_call_breakdown": [
                    {
                        "tool_name": "get_relevant_content",
                        "arguments": {"query": "tls"},
                        "count": 2,
                    }
                ],
                "token_usage_totals": {
                    "main": {
                        "input_tokens": 11,
                        "output_tokens": 5,
                        "total_tokens": 16,
                    },
                    "summarizer": {
                        "input_tokens": 3,
                        "output_tokens": 2,
                        "total_tokens": 5,
                    },
                    "audit_planner": {
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "total_tokens": 0,
                    },
                },
            }
        ],
    )

    assert "Main Tok (in/out/total)" in report_text
    assert "Disabled Tools" in report_text
    assert "Summarizer Tok (in/out/total)" in report_text
    assert "Audit Planner Tok (in/out/total)" in report_text
    assert "Run Wall ms" in report_text
    assert "RunTurn ms" in report_text
    assert "LLM ms" in report_text
    assert "Tool Call Breakdown" in report_text
    assert "Tool Call Totals" in report_text
    assert "Total tool calls: `2`" in report_text
    assert "get_relevant_content" in report_text
    assert "11/5/16" in report_text
    assert "3/2/5" in report_text
    assert "0/0/0" in report_text


def test_build_markdown_report_includes_case_failure_details(tmp_path):
    report_text = _build_markdown_report(
        dataset=SimpleNamespace(id="dataset-id"),
        output_dir=tmp_path,
        run_summaries=[
            {
                "run_id": "r1",
                "model_alias": "gf",
                "research_mode": True,
                "source_provider": "local_snapshot",
                "total_cases": 1,
                "passed_cases": 0,
                "failed_cases": 1,
                "error_cases": 0,
                "halted_cases": 0,
                "pass_rate": 0.0,
                "avg_elapsed_ms": 12.5,
                "tool_call_breakdown": [],
                "tool_call_counts": {},
            }
        ],
        run_case_results={
            "r1": [
                {
                    "test_id": "case-1",
                    "pass": False,
                    "elapsed_ms": 9.0,
                    "query": "q1",
                    "expected": {"type": "contains", "text": "foo"},
                    "answer": "bar",
                    "assertion_detail": "missing substring",
                    "tool_calls": [
                        {"tool_name": "query_research_memory", "arguments": {"query": "q1"}}
                    ],
                }
            ]
        },
    )

    assert "## Case Failure Details" in report_text
    assert "missing substring" in report_text
    assert "query_research_memory" in report_text


def test_build_results_markdown_includes_failure_details_and_tool_calls(tmp_path):
    run_summary = {
        "run_id": "run-1",
        "total_cases": 2,
        "passed_cases": 1,
        "failed_cases": 1,
        "error_cases": 0,
        "halted_cases": 0,
        "pass_rate": 0.5,
    }
    case_results = [
        {
            "test_id": "case-pass",
            "pass": True,
            "elapsed_ms": 10.0,
            "assertion_detail": "substring found",
            "error": None,
        },
        {
            "test_id": "case-fail",
            "pass": False,
            "elapsed_ms": 12.0,
            "query": "What is the limit?",
            "expected": {"type": "contains", "text": "no more than 30 days"},
            "answer": "The policy says every 45 days.",
            "assertion_detail": "missing substring",
            "tool_calls": [
                {
                    "tool_name": "get_relevant_content",
                    "arguments": {"query": "limit", "urls": ["https://example.com"]},
                }
            ],
            "error": None,
        },
    ]

    markdown = _build_results_markdown(run_summary, case_results, tmp_path / "artifacts")

    assert "# Eval Results (run-1)" in markdown
    assert "## Case Summary" in markdown
    assert "## Failure Details" in markdown
    assert "case-fail" in markdown
    assert "missing substring" in markdown
    assert "no more than 30 days" in markdown
    assert "get_relevant_content" in markdown


def test_run_evaluation_matrix_emits_progress_events(tmp_path, monkeypatch):
    docs = {
        "doc-1": DatasetDocument(
            id="doc-1",
            title="Doc 1",
            url="https://example.com/doc-1",
        )
    }
    tests = [
        DatasetTestCase(
            id="case-1",
            doc_ids=["doc-1"],
            query="q1",
            expected=DatasetExpected(type="contains", text="ok"),
        ),
        DatasetTestCase(
            id="case-2",
            doc_ids=["doc-1"],
            query="q2",
            expected=DatasetExpected(type="contains", text="ok"),
        ),
    ]
    dataset = DatasetSpec(
        id="dataset",
        docs=docs,
        tests=tests,
        source_path=tmp_path / "dataset.yaml",
    )
    matrix = MatrixSpec(
        runs=[RunProfile(id="run-1", model_alias="gf", research_mode=True)],
        source_path=tmp_path / "matrix.toml",
    )

    doc_path = tmp_path / "doc-1.txt"
    doc_path.write_text("doc", encoding="utf-8")
    snapshot_manifest = SnapshotManifest(
        dataset_id="dataset",
        dataset_dir=tmp_path,
        manifest_path=tmp_path / "manifest.json",
        doc_paths={"doc-1": doc_path},
        doc_sha256={"doc-1": "unused"},
        timings_ms={},
        doc_prepare_timings_ms={},
    )

    monkeypatch.setattr(
        "asky.evals.research_pipeline.evaluator._initialize_runtime_storage",
        lambda: None,
    )
    monkeypatch.setattr(
        "asky.evals.research_pipeline.evaluator._evaluate_case",
        lambda **_: {
            "pass": True,
            "elapsed_ms": 12.0,
            "error": None,
            "halted": False,
            "token_usage": {
                "main": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "summarizer": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                },
                "audit_planner": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                },
            },
        },
    )

    events = []
    output_dir = run_evaluation_matrix(
        dataset=dataset,
        matrix=matrix,
        snapshot_manifest=snapshot_manifest,
        output_root=tmp_path / "out",
        progress_callback=events.append,
    )

    assert [event["event"] for event in events] == [
        "run_start",
        "case_start",
        "case_end",
        "case_start",
        "case_end",
        "run_end",
    ]
    assert events[0]["run_id"] == "run-1"
    assert events[0]["case_total"] == 2
    assert events[1]["case_id"] == "case-1"
    assert events[3]["case_id"] == "case-2"
    assert events[-1]["passed_cases"] == 2
    assert events[-1]["total_cases"] == 2
    results_markdown = output_dir / "run-1" / "artifacts" / RUN_RESULTS_MARKDOWN_FILENAME
    assert results_markdown.exists()
    markdown_text = results_markdown.read_text(encoding="utf-8")
    assert "All cases passed." in markdown_text


def test_regenerate_report_rewrites_results_markdown_from_jsonl(tmp_path):
    dataset = DatasetSpec(
        id="dataset",
        docs={
            "doc-1": DatasetDocument(
                id="doc-1",
                title="Doc 1",
                url="https://example.com/doc-1",
            )
        },
        tests=[
            DatasetTestCase(
                id="case-1",
                doc_ids=["doc-1"],
                query="q1",
                expected=DatasetExpected(type="contains", text="ok"),
            )
        ],
        source_path=tmp_path / "dataset.yaml",
    )
    run_artifacts = tmp_path / "run-1" / "artifacts"
    run_artifacts.mkdir(parents=True, exist_ok=True)
    (run_artifacts / "summary.json").write_text(
        '{"run_id":"run-1","model_alias":"gf","research_mode":true,'
        '"source_provider":"local_snapshot","total_cases":1,"passed_cases":0,'
        '"failed_cases":1,"error_cases":0,"halted_cases":0,'
        '"pass_rate":0.0,"avg_elapsed_ms":1.0}',
        encoding="utf-8",
    )
    (run_artifacts / "results.jsonl").write_text(
        (
            '{"test_id":"case-1","pass":false,"elapsed_ms":1.0,'
            '"query":"q1","expected":{"type":"contains","text":"ok"},'
            '"answer":"nope","assertion_detail":"missing substring"}\n'
        ),
        encoding="utf-8",
    )

    regenerate_report(dataset, tmp_path)

    results_markdown = run_artifacts / RUN_RESULTS_MARKDOWN_FILENAME
    assert results_markdown.exists()
    markdown_text = results_markdown.read_text(encoding="utf-8")
    assert "case-1" in markdown_text
    assert "missing substring" in markdown_text


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
