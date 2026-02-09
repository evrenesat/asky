"""Core evaluator orchestration for research pipeline integration runs."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence
from urllib.parse import urlsplit

import requests

from asky.api import AskyClient, AskyConfig, AskyTurnRequest
from asky.core.api_client import UsageTracker
from asky.evals.research_pipeline.assertions import evaluate_answer
from asky.evals.research_pipeline.dataset import (
    DatasetExpected,
    DatasetSpec,
    DatasetTestCase,
)
from asky.evals.research_pipeline.matrix import (
    SOURCE_PROVIDER_LOCAL_SNAPSHOT,
    MatrixSpec,
    RunProfile,
)
from asky.evals.research_pipeline.runtime_isolation import (
    build_runtime_paths,
    isolated_asky_runtime,
)
from asky.evals.research_pipeline.source_providers import get_source_provider

SNAPSHOT_DOCS_DIRNAME = "docs"
SNAPSHOT_MANIFEST_FILENAME = "manifest.json"
RUN_RESULTS_FILENAME = "results.jsonl"
RUN_SUMMARY_FILENAME = "summary.json"
SESSION_SUMMARY_FILENAME = "summary.json"
SESSION_REPORT_FILENAME = "report.md"

DEFAULT_DOWNLOAD_TIMEOUT_SECONDS = 60
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
DEFAULT_OUTPUT_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
MAX_OUTPUT_DIR_COLLISIONS = 1000


@dataclass(frozen=True)
class SnapshotManifest:
    """Resolved snapshot file mapping for one dataset."""

    dataset_id: str
    dataset_dir: Path
    manifest_path: Path
    doc_paths: Dict[str, Path]
    doc_sha256: Dict[str, str]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_timestamp(moment: datetime) -> str:
    return moment.isoformat()


def _result_timestamp() -> str:
    return _utc_now().strftime(DEFAULT_OUTPUT_TIMESTAMP_FORMAT)


def _create_unique_output_dir(output_root: Path) -> Path:
    """Create a unique session output directory, avoiding same-second collisions."""
    base_name = _result_timestamp()
    base_path = output_root / base_name
    if not base_path.exists():
        base_path.mkdir(parents=True, exist_ok=False)
        return base_path

    for index in range(1, MAX_OUTPUT_DIR_COLLISIONS + 1):
        candidate = output_root / f"{base_name}_{index:03d}"
        if candidate.exists():
            continue
        candidate.mkdir(parents=True, exist_ok=False)
        return candidate

    raise RuntimeError(
        f"Failed to allocate unique output directory under {output_root} "
        f"after {MAX_OUTPUT_DIR_COLLISIONS} attempts."
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Unsupported JSON serialization type: {type(value)!r}")


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, default=_json_default)
        handle.write("\n")


def _write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, default=_json_default))
            handle.write("\n")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _extension_from_url(url: str) -> str:
    parsed = urlsplit(url)
    suffix = Path(parsed.path).suffix.strip().lower()
    if suffix and re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
        return suffix
    return ".bin"


def _download_document(url: str, timeout_seconds: int) -> bytes:
    response = requests.get(url, timeout=timeout_seconds, stream=True)
    response.raise_for_status()
    chunks: List[bytes] = []
    for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
        if chunk:
            chunks.append(chunk)
    return b"".join(chunks)


def prepare_dataset_snapshots(
    dataset: DatasetSpec,
    snapshot_root: Path,
    *,
    refresh: bool = False,
    timeout_seconds: int = DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
) -> SnapshotManifest:
    """Download or reuse pinned local files for one dataset."""
    dataset_dir = snapshot_root.expanduser().resolve() / dataset.id
    docs_dir = dataset_dir / SNAPSHOT_DOCS_DIRNAME
    manifest_path = dataset_dir / SNAPSHOT_MANIFEST_FILENAME

    docs_dir.mkdir(parents=True, exist_ok=True)

    doc_paths: Dict[str, Path] = {}
    doc_sha256: Dict[str, str] = {}
    docs_payload: Dict[str, Dict[str, Any]] = {}

    for doc_id, doc in dataset.docs.items():
        ext = _extension_from_url(doc.url)
        filename = f"{doc_id}{ext}"
        file_path = docs_dir / filename

        if refresh or not file_path.exists():
            file_data = _download_document(doc.url, timeout_seconds)
            file_path.write_bytes(file_data)
        else:
            file_data = file_path.read_bytes()

        checksum = _sha256_bytes(file_data)
        relative_path = file_path.relative_to(dataset_dir)

        doc_paths[doc_id] = file_path
        doc_sha256[doc_id] = checksum
        docs_payload[doc_id] = {
            "id": doc.id,
            "title": doc.title,
            "url": doc.url,
            "path": str(relative_path),
            "sha256": checksum,
            "bytes": len(file_data),
        }

    _write_json(
        manifest_path,
        {
            "dataset_id": dataset.id,
            "dataset_source": str(dataset.source_path),
            "created_at": _format_timestamp(_utc_now()),
            "docs": docs_payload,
        },
    )

    return SnapshotManifest(
        dataset_id=dataset.id,
        dataset_dir=dataset_dir,
        manifest_path=manifest_path,
        doc_paths=doc_paths,
        doc_sha256=doc_sha256,
    )


def load_snapshot_manifest(dataset: DatasetSpec, snapshot_root: Path) -> SnapshotManifest:
    """Load snapshot metadata and resolve absolute paths for one dataset."""
    dataset_dir = snapshot_root.expanduser().resolve() / dataset.id
    manifest_path = dataset_dir / SNAPSHOT_MANIFEST_FILENAME
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Snapshot manifest not found: {manifest_path}. Run prepare first."
        )

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    docs_payload = payload.get("docs")
    if not isinstance(docs_payload, dict):
        raise ValueError(f"Invalid snapshot manifest shape: {manifest_path}")

    doc_paths: Dict[str, Path] = {}
    doc_sha256: Dict[str, str] = {}
    for doc_id in dataset.docs:
        item = docs_payload.get(doc_id)
        if not isinstance(item, dict):
            raise ValueError(
                f"Snapshot manifest missing doc '{doc_id}' for dataset '{dataset.id}'."
            )
        relative_path = item.get("path")
        checksum = item.get("sha256")
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise ValueError(f"Snapshot manifest doc '{doc_id}' path is invalid.")
        if not isinstance(checksum, str) or not checksum.strip():
            raise ValueError(f"Snapshot manifest doc '{doc_id}' sha256 is invalid.")

        resolved_path = (dataset_dir / relative_path).resolve()
        if not resolved_path.exists():
            raise FileNotFoundError(
                f"Snapshot file for doc '{doc_id}' not found: {resolved_path}"
            )
        computed_sha = _sha256_bytes(resolved_path.read_bytes())
        if computed_sha != checksum:
            raise ValueError(
                f"Snapshot checksum mismatch for doc '{doc_id}': "
                f"expected {checksum}, got {computed_sha}"
            )

        doc_paths[doc_id] = resolved_path
        doc_sha256[doc_id] = checksum

    return SnapshotManifest(
        dataset_id=dataset.id,
        dataset_dir=dataset_dir,
        manifest_path=manifest_path,
        doc_paths=doc_paths,
        doc_sha256=doc_sha256,
    )


def _serialize_expected(expected: DatasetExpected) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"type": expected.type}
    if expected.text is not None:
        payload["text"] = expected.text
    if expected.pattern is not None:
        payload["pattern"] = expected.pattern
    return payload


def _apply_query_affixes(query_text: str, run: RunProfile) -> str:
    pieces: List[str] = []
    if run.query_prefix:
        pieces.append(run.query_prefix)
    pieces.append(query_text)
    if run.query_suffix:
        pieces.append(run.query_suffix)
    return "\n\n".join(piece for piece in pieces if piece)


def _build_turn_request(query_text: str, run: RunProfile) -> AskyTurnRequest:
    return AskyTurnRequest(
        query_text=query_text,
        lean=run.lean,
        preload_local_sources=run.preload_local_sources,
        preload_shortlist=run.preload_shortlist,
        additional_source_context=run.additional_source_context,
        save_history=run.save_history,
    )


def _evaluate_case(
    *,
    run: RunProfile,
    dataset: DatasetSpec,
    test_case: DatasetTestCase,
    snapshot_manifest: Optional[SnapshotManifest],
) -> Dict[str, Any]:
    provider = get_source_provider(run.resolved_source_provider())
    docs = [dataset.docs[doc_id] for doc_id in test_case.doc_ids]

    snapshot_paths: Optional[Dict[str, Path]] = None
    if snapshot_manifest is not None:
        snapshot_paths = snapshot_manifest.doc_paths

    source_payload = provider.build_query(
        base_query=test_case.query,
        docs=docs,
        snapshot_paths=snapshot_paths,
    )
    query_text = _apply_query_affixes(source_payload.query_text, run)

    usage_tracker = UsageTracker()
    summarization_tracker = UsageTracker()
    client = AskyClient(
        AskyConfig(
            model_alias=run.model_alias,
            research_mode=run.research_mode,
            disabled_tools=set(run.disabled_tools),
            model_parameters_override=dict(run.parameters),
        ),
        usage_tracker=usage_tracker,
        summarization_tracker=summarization_tracker,
    )

    started = time.perf_counter()
    answer = ""
    notices: List[str] = []
    halted = False
    halt_reason: Optional[str] = None
    error: Optional[str] = None

    try:
        result = client.run_turn(_build_turn_request(query_text, run))
        answer = result.final_answer
        notices = list(result.notices)
        halted = bool(result.halted)
        halt_reason = result.halt_reason
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    elapsed_ms = (time.perf_counter() - started) * 1000.0

    assertion_result = evaluate_answer(answer, test_case.expected)
    if error is not None:
        assertion_result = assertion_result.__class__(
            passed=False,
            detail=f"execution failed: {error}",
        )
    if halted and not answer:
        assertion_result = assertion_result.__class__(
            passed=False,
            detail=f"run halted before answer: {halt_reason}",
        )

    return {
        "timestamp": _format_timestamp(_utc_now()),
        "run_id": run.id,
        "model_alias": run.model_alias,
        "research_mode": run.research_mode,
        "source_provider": source_payload.provider_name,
        "parameters": dict(run.parameters),
        "test_id": test_case.id,
        "doc_ids": list(test_case.doc_ids),
        "source_identifiers": list(source_payload.source_identifiers),
        "query": query_text,
        "expected": _serialize_expected(test_case.expected),
        "answer": answer,
        "pass": bool(assertion_result.passed),
        "assertion_detail": assertion_result.detail,
        "elapsed_ms": elapsed_ms,
        "halted": halted,
        "halt_reason": halt_reason,
        "notices": notices,
        "tool_usage": usage_tracker.get_tool_usage(),
        "error": error,
    }


def _summarize_run(run: RunProfile, case_results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(case_results)
    passed = sum(1 for item in case_results if item.get("pass"))
    failed = total - passed
    errored = sum(1 for item in case_results if item.get("error"))
    halted = sum(1 for item in case_results if item.get("halted"))
    total_ms = sum(float(item.get("elapsed_ms", 0.0) or 0.0) for item in case_results)
    avg_ms = (total_ms / total) if total else 0.0

    return {
        "run_id": run.id,
        "model_alias": run.model_alias,
        "research_mode": run.research_mode,
        "source_provider": run.resolved_source_provider(),
        "parameters": dict(run.parameters),
        "total_cases": total,
        "passed_cases": passed,
        "failed_cases": failed,
        "error_cases": errored,
        "halted_cases": halted,
        "pass_rate": (passed / total) if total else 0.0,
        "avg_elapsed_ms": avg_ms,
    }


def _build_markdown_report(
    dataset: DatasetSpec,
    output_dir: Path,
    run_summaries: Sequence[Dict[str, Any]],
) -> str:
    lines = [
        f"# Research Eval Report ({dataset.id})",
        "",
        f"Output directory: `{output_dir}`",
        "",
        "| Run | Mode | Model | Provider | Cases | Passed | Failed | Errors | Halted | Pass Rate | Avg ms |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for summary in run_summaries:
        mode_label = "research" if summary["research_mode"] else "standard"
        lines.append(
            "| {run_id} | {mode} | {model} | {provider} | {total} | {passed} | {failed} | {errors} | {halted} | {rate:.1%} | {avg:.1f} |".format(
                run_id=summary["run_id"],
                mode=mode_label,
                model=summary["model_alias"],
                provider=summary["source_provider"],
                total=summary["total_cases"],
                passed=summary["passed_cases"],
                failed=summary["failed_cases"],
                errors=summary.get("error_cases", 0),
                halted=summary.get("halted_cases", 0),
                rate=float(summary["pass_rate"]),
                avg=float(summary["avg_elapsed_ms"]),
            )
        )

    return "\n".join(lines) + "\n"


def _initialize_runtime_storage() -> None:
    """Ensure isolated runtime DB schema is initialized before evaluations."""
    from asky.storage import init_db

    init_db()


def run_evaluation_matrix(
    *,
    dataset: DatasetSpec,
    matrix: MatrixSpec,
    snapshot_manifest: Optional[SnapshotManifest],
    output_root: Path,
    selected_run_ids: Optional[Sequence[str]] = None,
) -> Path:
    """Execute all selected run profiles and persist evaluation artifacts."""
    selection = set(selected_run_ids or [])

    output_root_resolved = output_root.expanduser().resolve()
    output_root_resolved.mkdir(parents=True, exist_ok=True)
    output_dir = _create_unique_output_dir(output_root_resolved)

    selected_runs: List[RunProfile] = []
    for run in matrix.runs:
        if selection and run.id not in selection:
            continue
        selected_runs.append(run)

    if not selected_runs:
        raise ValueError("No runs selected for execution.")

    run_summaries: List[Dict[str, Any]] = []

    for run in selected_runs:
        if (
            run.resolved_source_provider() == SOURCE_PROVIDER_LOCAL_SNAPSHOT
            and snapshot_manifest is None
        ):
            raise ValueError(
                "Run requires local_snapshot provider but snapshot manifest is missing."
            )

        run_dir = output_dir / run.id
        runtime_paths = build_runtime_paths(run_dir)

        with isolated_asky_runtime(runtime_paths):
            _initialize_runtime_storage()
            case_results: List[Dict[str, Any]] = []
            for test_case in dataset.tests:
                case_results.append(
                    _evaluate_case(
                        run=run,
                        dataset=dataset,
                        test_case=test_case,
                        snapshot_manifest=snapshot_manifest,
                    )
                )

        run_summary = _summarize_run(run, case_results)
        _write_jsonl(runtime_paths.artifacts_dir / RUN_RESULTS_FILENAME, case_results)
        _write_json(runtime_paths.artifacts_dir / RUN_SUMMARY_FILENAME, run_summary)
        run_summaries.append(run_summary)

    session_summary = {
        "dataset_id": dataset.id,
        "created_at": _format_timestamp(_utc_now()),
        "run_count": len(run_summaries),
        "runs": run_summaries,
    }
    _write_json(output_dir / SESSION_SUMMARY_FILENAME, session_summary)

    report_text = _build_markdown_report(dataset, output_dir, run_summaries)
    report_path = output_dir / SESSION_REPORT_FILENAME
    report_path.write_text(report_text, encoding="utf-8")

    return output_dir


def regenerate_report(dataset: DatasetSpec, output_dir: Path) -> Path:
    """Regenerate markdown report from stored run summaries."""
    resolved_output_dir = output_dir.expanduser().resolve()
    run_summaries: List[Dict[str, Any]] = []

    for run_dir in sorted(resolved_output_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        summary_path = run_dir / "artifacts" / RUN_SUMMARY_FILENAME
        if not summary_path.exists():
            continue
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            run_summaries.append(payload)

    if not run_summaries:
        raise ValueError(f"No run summaries found in {resolved_output_dir}.")

    report_text = _build_markdown_report(dataset, resolved_output_dir, run_summaries)
    report_path = resolved_output_dir / SESSION_REPORT_FILENAME
    report_path.write_text(report_text, encoding="utf-8")
    return report_path
