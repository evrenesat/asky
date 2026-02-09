"""CLI entrypoint for research pipeline evaluation harness."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from asky.evals.research_pipeline.dataset import load_dataset
from asky.evals.research_pipeline.evaluator import (
    DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
    RUN_RESULTS_MARKDOWN_FILENAME,
    load_snapshot_manifest,
    prepare_dataset_snapshots,
    regenerate_report,
    run_evaluation_matrix,
)
from asky.evals.research_pipeline.matrix import (
    SOURCE_PROVIDER_LOCAL_SNAPSHOT,
    load_matrix,
)

DEFAULT_EVAL_ROOT = Path("temp/research_eval")
DEFAULT_SNAPSHOT_ROOT = DEFAULT_EVAL_ROOT / "snapshots"
DEFAULT_OUTPUT_ROOT = DEFAULT_EVAL_ROOT / "runs"


def _resolve_root(path_value: Optional[str], default_path: Path) -> Path:
    candidate = Path(path_value).expanduser() if path_value else default_path
    return candidate.resolve()


def _split_run_ids(raw_values: Optional[List[str]]) -> List[str]:
    run_ids: List[str] = []
    seen = set()
    for raw in raw_values or []:
        for token in raw.split(","):
            run_id = token.strip()
            if not run_id or run_id in seen:
                continue
            seen.add(run_id)
            run_ids.append(run_id)
    return run_ids


def _format_role_tokens(item: Dict[str, Any], role: str) -> str:
    token_totals = item.get("token_usage_totals")
    if not isinstance(token_totals, dict):
        return "0/0/0"
    role_totals = token_totals.get(role)
    if not isinstance(role_totals, dict):
        return "0/0/0"
    input_tokens = int(role_totals.get("input_tokens", 0) or 0)
    output_tokens = int(role_totals.get("output_tokens", 0) or 0)
    total_tokens = int(role_totals.get("total_tokens", 0) or 0)
    return f"{input_tokens}/{output_tokens}/{total_tokens}"


def _format_timing_total(item: Dict[str, Any], key: str) -> str:
    timing_totals = item.get("timing_totals_ms")
    if not isinstance(timing_totals, dict):
        return "0.0"
    return f"{float(timing_totals.get(key, 0.0) or 0.0):.1f}"


def _format_disabled_tools(item: Dict[str, Any]) -> str:
    disabled_tools = item.get("disabled_tools")
    if not isinstance(disabled_tools, list) or not disabled_tools:
        return "-"
    return ",".join(str(tool) for tool in disabled_tools)


def _print_eval_progress(event: Dict[str, Any]) -> None:
    event_type = str(event.get("event", ""))
    if event_type == "run_start":
        run_index = int(event.get("run_index", 0) or 0)
        run_total = int(event.get("run_total", 0) or 0)
        run_id = str(event.get("run_id", "unknown"))
        case_total = int(event.get("case_total", 0) or 0)
        print(
            f"[run {run_index}/{run_total}] {run_id} started ({case_total} cases)",
            flush=True,
        )
        return

    if event_type == "case_start":
        case_index = int(event.get("case_index", 0) or 0)
        case_total = int(event.get("case_total", 0) or 0)
        case_id = str(event.get("case_id", "unknown"))
        print(
            f"  [case {case_index}/{case_total}] {case_id} running...",
            flush=True,
        )
        return

    if event_type == "case_end":
        case_index = int(event.get("case_index", 0) or 0)
        case_total = int(event.get("case_total", 0) or 0)
        case_id = str(event.get("case_id", "unknown"))
        elapsed_ms = float(event.get("elapsed_ms", 0.0) or 0.0)
        error = event.get("error")
        halted = bool(event.get("halted"))
        passed = bool(event.get("pass"))
        status = "PASS" if passed else "FAIL"
        if error:
            status = "ERROR"
        elif halted:
            status = "HALTED"
        print(
            f"  [case {case_index}/{case_total}] {case_id} {status} ({elapsed_ms:.0f} ms)",
            flush=True,
        )
        return

    if event_type == "run_end":
        run_index = int(event.get("run_index", 0) or 0)
        run_total = int(event.get("run_total", 0) or 0)
        run_id = str(event.get("run_id", "unknown"))
        passed = int(event.get("passed_cases", 0) or 0)
        total = int(event.get("total_cases", 0) or 0)
        failed = int(event.get("failed_cases", 0) or 0)
        errors = int(event.get("error_cases", 0) or 0)
        halted = int(event.get("halted_cases", 0) or 0)
        run_wall_ms = float(event.get("run_wall_ms", 0.0) or 0.0)
        print(
            f"[run {run_index}/{run_total}] {run_id} done: "
            f"passed={passed}/{total} failed={failed} errors={errors} halted={halted} "
            f"run_wall_ms={run_wall_ms:.1f}",
            flush=True,
        )
        return

    if event_type == "external_transition":
        external_type = str(event.get("external_type", "external"))
        phase = str(event.get("phase", "unknown"))
        case_id = str(event.get("test_id", "unknown"))
        run_id = str(event.get("run_id", "unknown"))
        payload = event.get("payload")
        elapsed_ms = event.get("elapsed_ms")
        if external_type == "tool" and isinstance(payload, dict):
            tool_name = str(payload.get("tool_name", "unknown_tool"))
            payload_elapsed_ms = payload.get("elapsed_ms")
            elapsed_suffix = ""
            if isinstance(payload_elapsed_ms, (int, float)):
                elapsed_suffix = f" ({float(payload_elapsed_ms):.1f} ms)"
            print(
                f"    [{run_id}/{case_id}] tool {phase}: {tool_name}{elapsed_suffix}",
                flush=True,
            )
            return
        elapsed_suffix = ""
        if isinstance(elapsed_ms, (int, float)):
            elapsed_suffix = f" ({float(elapsed_ms):.1f} ms)"
        print(
            f"    [{run_id}/{case_id}] {external_type} {phase}{elapsed_suffix}",
            flush=True,
        )
        return

    if event_type == "external_status":
        external_type = str(event.get("external_type", "external"))
        message = str(event.get("message", "")).strip()
        if not message:
            return
        case_id = str(event.get("test_id", "unknown"))
        run_id = str(event.get("run_id", "unknown"))
        print(
            f"    [{run_id}/{case_id}] {external_type}: {message}",
            flush=True,
        )


def _resolve_dataset_path(
    dataset_arg: Optional[str],
    matrix_dataset_path: Optional[Path],
) -> Path:
    if dataset_arg:
        return Path(dataset_arg).expanduser().resolve()
    if matrix_dataset_path is not None:
        return matrix_dataset_path
    raise ValueError("Dataset path is required (pass --dataset or set matrix dataset).")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dual-mode research evaluation harness (programmatic AskyClient).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser(
        "prepare",
        help="Download and pin local dataset snapshots.",
    )
    prepare_parser.add_argument(
        "--dataset", required=True, help="Path to dataset yaml/json."
    )
    prepare_parser.add_argument(
        "--snapshot-root",
        default=None,
        help=f"Snapshot root directory (default: {DEFAULT_SNAPSHOT_ROOT}).",
    )
    prepare_parser.add_argument(
        "--refresh",
        action="store_true",
        help="Redownload files even if snapshots already exist.",
    )
    prepare_parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
        help=f"Download timeout in seconds (default: {DEFAULT_DOWNLOAD_TIMEOUT_SECONDS}).",
    )

    run_parser = subparsers.add_parser(
        "run",
        help="Execute evaluation matrix and write artifacts.",
    )
    run_parser.add_argument("--matrix", required=True, help="Path to matrix toml.")
    run_parser.add_argument(
        "--dataset",
        default=None,
        help="Optional dataset path override. If omitted, matrix.dataset is used.",
    )
    run_parser.add_argument(
        "--snapshot-root",
        default=None,
        help=f"Snapshot root override (default: {DEFAULT_SNAPSHOT_ROOT}).",
    )
    run_parser.add_argument(
        "--output-root",
        default=None,
        help=f"Run output root override (default: {DEFAULT_OUTPUT_ROOT}).",
    )
    run_parser.add_argument(
        "--run",
        action="append",
        default=[],
        help="Run id filter. Can be repeated or comma-separated.",
    )

    report_parser = subparsers.add_parser(
        "report",
        help="Regenerate markdown report from an existing output directory.",
    )
    report_parser.add_argument(
        "--dataset", required=True, help="Path to dataset yaml/json."
    )
    report_parser.add_argument(
        "--results-dir", required=True, help="Path to run output dir."
    )

    return parser


def _handle_prepare(args: argparse.Namespace) -> int:
    dataset = load_dataset(Path(args.dataset))
    snapshot_root = _resolve_root(args.snapshot_root, DEFAULT_SNAPSHOT_ROOT)
    manifest = prepare_dataset_snapshots(
        dataset,
        snapshot_root,
        refresh=bool(args.refresh),
        timeout_seconds=int(args.timeout),
    )
    print(f"Prepared dataset '{dataset.id}' snapshots at: {manifest.dataset_dir}")
    print(f"Manifest: {manifest.manifest_path}")
    print(f"Documents: {len(manifest.doc_paths)}")
    prepare_total_ms = float(manifest.timings_ms.get("prepare_total_ms", 0.0) or 0.0)
    downloaded_docs = int(manifest.timings_ms.get("downloaded_docs", 0.0) or 0.0)
    reused_docs = int(manifest.timings_ms.get("reused_docs", 0.0) or 0.0)
    print(
        f"Prepare timing: total={prepare_total_ms:.1f}ms "
        f"downloaded={downloaded_docs} reused={reused_docs}"
    )
    if manifest.doc_prepare_timings_ms:
        print("Document timings:")
        for doc_id, doc_timing in sorted(manifest.doc_prepare_timings_ms.items()):
            action = str(doc_timing.get("action", "unknown"))
            elapsed_ms = float(doc_timing.get("elapsed_ms", 0.0) or 0.0)
            print(f"- {doc_id}: {action} ({elapsed_ms:.1f} ms)")
    return 0


def _handle_run(args: argparse.Namespace) -> int:
    matrix = load_matrix(Path(args.matrix))
    dataset_path = _resolve_dataset_path(args.dataset, matrix.dataset_path)
    dataset = load_dataset(dataset_path)

    snapshot_root_default = matrix.snapshot_root or DEFAULT_SNAPSHOT_ROOT
    output_root_default = matrix.output_root or DEFAULT_OUTPUT_ROOT

    snapshot_root = _resolve_root(args.snapshot_root, snapshot_root_default)
    output_root = _resolve_root(args.output_root, output_root_default)

    selected_run_ids = _split_run_ids(args.run)
    selected_run_id_set = set(selected_run_ids)
    selected_runs = [
        run
        for run in matrix.runs
        if not selected_run_id_set or run.id in selected_run_id_set
    ]

    needs_snapshots = any(
        run.resolved_source_provider() == SOURCE_PROVIDER_LOCAL_SNAPSHOT
        for run in selected_runs
    )
    snapshot_manifest = None
    if needs_snapshots:
        snapshot_manifest = load_snapshot_manifest(dataset, snapshot_root)

    output_dir = run_evaluation_matrix(
        dataset=dataset,
        matrix=matrix,
        snapshot_manifest=snapshot_manifest,
        output_root=output_root,
        selected_run_ids=selected_run_ids,
        progress_callback=_print_eval_progress,
    )

    print(f"Run output: {output_dir}")
    summary_path = output_dir / "summary.json"
    report_path = output_dir / "report.md"
    print(f"Summary: {summary_path}")
    print(f"Report: {report_path}")

    if summary_path.exists():
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        runs = payload.get("runs", []) if isinstance(payload, dict) else []
        if isinstance(runs, list) and runs:
            print("")
            print("Run results:")
            for item in runs:
                run_id = str(item.get("run_id", "unknown"))
                results_markdown_path = (
                    output_dir / run_id / "artifacts" / RUN_RESULTS_MARKDOWN_FILENAME
                )
                passed = int(item.get("passed_cases", 0) or 0)
                total = int(item.get("total_cases", 0) or 0)
                failed = int(item.get("failed_cases", 0) or 0)
                errors = int(item.get("error_cases", 0) or 0)
                halted = int(item.get("halted_cases", 0) or 0)
                print(
                    f"- {run_id}: passed={passed}/{total} "
                    f"failed={failed} errors={errors} halted={halted}"
                )
                print(f"  disabled_tools={_format_disabled_tools(item)}")
                print(f"  results_markdown= {results_markdown_path}")
                print(
                    "  tokens "
                    f"main={_format_role_tokens(item, 'main')} "
                    f"summarizer={_format_role_tokens(item, 'summarizer')} "
                    f"audit_planner={_format_role_tokens(item, 'audit_planner')}"
                )
                print(
                    "  timings_ms "
                    f"run_wall={_format_timing_total(item, 'run_wall_ms')} "
                    f"case_total={_format_timing_total(item, 'case_total_ms')} "
                    f"source_prepare={_format_timing_total(item, 'source_prepare_ms')} "
                    f"client_init={_format_timing_total(item, 'client_init_ms')} "
                    f"run_turn={_format_timing_total(item, 'run_turn_ms')} "
                    f"llm={_format_timing_total(item, 'llm_total_ms')} "
                    f"tool={_format_timing_total(item, 'tool_total_ms')} "
                    f"local_ingest={_format_timing_total(item, 'local_ingestion_ms')} "
                    f"shortlist={_format_timing_total(item, 'shortlist_ms')}"
                )
                tool_call_counts = item.get("tool_call_counts")
                if isinstance(tool_call_counts, dict) and tool_call_counts:
                    ordered_counts = sorted(
                        (
                            (str(name), int(count or 0))
                            for name, count in tool_call_counts.items()
                        ),
                        key=lambda entry: (-entry[1], entry[0]),
                    )
                    counts_text = ", ".join(
                        f"{name}:{count}" for name, count in ordered_counts
                    )
                    print(f"  tool_calls_by_type {counts_text}")

            total_errors = sum(int(item.get("error_cases", 0) or 0) for item in runs)
            if total_errors > 0:
                print("")
                print(
                    "Note: Some cases had execution errors. "
                    "Inspect per-case details in each run's artifacts/results.jsonl."
                )
        timing_totals = (
            payload.get("timing_totals_ms", {}) if isinstance(payload, dict) else {}
        )
        if isinstance(timing_totals, dict):
            session_wall_ms = float(timing_totals.get("session_wall_ms", 0.0) or 0.0)
            runs_wall_ms = float(timing_totals.get("runs_wall_ms", 0.0) or 0.0)
            print("")
            print(
                f"Session timing: session_wall_ms={session_wall_ms:.1f} "
                f"runs_wall_ms={runs_wall_ms:.1f}"
            )
    return 0


def _handle_report(args: argparse.Namespace) -> int:
    dataset = load_dataset(Path(args.dataset))
    results_dir = Path(args.results_dir).expanduser().resolve()
    report_path = regenerate_report(dataset, results_dir)
    print(f"Report written: {report_path}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "prepare":
        return _handle_prepare(args)
    if args.command == "run":
        return _handle_run(args)
    if args.command == "report":
        return _handle_report(args)

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
