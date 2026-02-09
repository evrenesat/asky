"""CLI entrypoint for research pipeline evaluation harness."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Optional

from asky.evals.research_pipeline.dataset import load_dataset
from asky.evals.research_pipeline.evaluator import (
    DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
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
    prepare_parser.add_argument("--dataset", required=True, help="Path to dataset yaml/json.")
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
    report_parser.add_argument("--dataset", required=True, help="Path to dataset yaml/json.")
    report_parser.add_argument("--results-dir", required=True, help="Path to run output dir.")

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
        run for run in matrix.runs if not selected_run_id_set or run.id in selected_run_id_set
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
                passed = int(item.get("passed_cases", 0) or 0)
                total = int(item.get("total_cases", 0) or 0)
                failed = int(item.get("failed_cases", 0) or 0)
                errors = int(item.get("error_cases", 0) or 0)
                halted = int(item.get("halted_cases", 0) or 0)
                print(
                    f"- {run_id}: passed={passed}/{total} "
                    f"failed={failed} errors={errors} halted={halted}"
                )

            total_errors = sum(int(item.get("error_cases", 0) or 0) for item in runs)
            if total_errors > 0:
                print("")
                print(
                    "Note: Some cases had execution errors. "
                    "Inspect per-case details in each run's artifacts/results.jsonl."
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
