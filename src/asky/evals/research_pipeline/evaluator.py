"""Core evaluator orchestration for research pipeline integration runs."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence
from urllib.parse import urlsplit

import requests

from asky.api import AskyClient, AskyConfig, AskyTurnRequest
from asky.api.preload import preload_local_research_sources, shortlist_prompt_sources
from asky.config import MODELS, SUMMARIZATION_MODEL
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
RUN_RESULTS_MARKDOWN_FILENAME = "results.md"
RUN_SUMMARY_FILENAME = "summary.json"
SESSION_SUMMARY_FILENAME = "summary.json"
SESSION_REPORT_FILENAME = "report.md"

DEFAULT_DOWNLOAD_TIMEOUT_SECONDS = 60
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
DEFAULT_OUTPUT_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
MAX_OUTPUT_DIR_COLLISIONS = 1000
TIMING_KEY_PREPARE_TOTAL_MS = "prepare_total_ms"
TIMING_KEY_DOWNLOAD_DOCS = "downloaded_docs"
TIMING_KEY_REUSED_DOCS = "reused_docs"
TIMING_KEY_CASE_TOTAL_MS = "case_total_ms"
TIMING_KEY_SOURCE_PREPARE_MS = "source_prepare_ms"
TIMING_KEY_CLIENT_INIT_MS = "client_init_ms"
TIMING_KEY_RUN_TURN_MS = "run_turn_ms"
TIMING_KEY_LLM_TOTAL_MS = "llm_total_ms"
TIMING_KEY_TOOL_TOTAL_MS = "tool_total_ms"
TIMING_KEY_LOCAL_INGESTION_MS = "local_ingestion_ms"
TIMING_KEY_SHORTLIST_MS = "shortlist_ms"
TIMING_KEY_RUN_WALL_MS = "run_wall_ms"
TIMING_KEY_SESSION_WALL_MS = "session_wall_ms"
TOKEN_USAGE_ROLE_MAIN = "main"
TOKEN_USAGE_ROLE_SUMMARIZER = "summarizer"
TOKEN_USAGE_ROLE_AUDIT_PLANNER = "audit_planner"
AUDIT_PLANNER_MODEL_ALIAS_PLACEHOLDER = "audit-planner"
TOKEN_USAGE_ROLES = (
    TOKEN_USAGE_ROLE_MAIN,
    TOKEN_USAGE_ROLE_SUMMARIZER,
    TOKEN_USAGE_ROLE_AUDIT_PLANNER,
)
RESULTS_TABLE_TEXT_LIMIT = 100


@dataclass(frozen=True)
class SnapshotManifest:
    """Resolved snapshot file mapping for one dataset."""

    dataset_id: str
    dataset_dir: Path
    manifest_path: Path
    doc_paths: Dict[str, Path]
    doc_sha256: Dict[str, str]
    timings_ms: Dict[str, float]
    doc_prepare_timings_ms: Dict[str, Dict[str, Any]]


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


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _compact_markdown_text(value: Any, limit: int = RESULTS_TABLE_TEXT_LIMIT) -> str:
    text = str(value or "").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _escape_markdown_cell(value: Any) -> str:
    text = str(value or "").replace("\n", " ").replace("|", "\\|")
    return text


def _format_case_status(case_result: Dict[str, Any]) -> str:
    if case_result.get("error"):
        return "ERROR"
    if case_result.get("halted"):
        return "HALTED"
    if case_result.get("pass"):
        return "PASS"
    return "FAIL"


def _format_json_block(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, default=_json_default)


def _format_tool_calls_markdown(case_result: Dict[str, Any]) -> List[str]:
    tool_calls = case_result.get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls:
        return ["No tool calls recorded."]

    lines = ["| Tool | Arguments |", "| --- | --- |"]
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        tool_name = _escape_markdown_cell(call.get("tool_name", "unknown_tool"))
        arguments = _escape_markdown_cell(_format_tool_arguments_for_report(call.get("arguments")))
        lines.append(f"| `{tool_name}` | {arguments} |")
    if len(lines) == 2:
        return ["No tool calls recorded."]
    return lines


def _build_results_markdown(
    run_summary: Dict[str, Any],
    case_results: Sequence[Dict[str, Any]],
    artifacts_dir: Path,
) -> str:
    run_id = str(run_summary.get("run_id", "unknown"))
    total_cases = int(run_summary.get("total_cases", len(case_results)) or 0)
    passed_cases = int(run_summary.get("passed_cases", 0) or 0)
    failed_cases = int(run_summary.get("failed_cases", 0) or 0)
    error_cases = int(run_summary.get("error_cases", 0) or 0)
    halted_cases = int(run_summary.get("halted_cases", 0) or 0)
    pass_rate = float(run_summary.get("pass_rate", 0.0) or 0.0) * 100.0

    lines = [
        f"# Eval Results ({run_id})",
        "",
        f"Artifacts directory: `{artifacts_dir}`",
        "",
        (
            "Summary: "
            f"passed={passed_cases}/{total_cases} failed={failed_cases} "
            f"errors={error_cases} halted={halted_cases} pass_rate={pass_rate:.1f}%"
        ),
        "",
        "## Case Summary",
        "",
        "| Case ID | Status | Elapsed ms | Assertion Detail | Error |",
        "| --- | --- | ---: | --- | --- |",
    ]

    for case_result in case_results:
        case_id = _escape_markdown_cell(case_result.get("test_id", "unknown"))
        status = _format_case_status(case_result)
        elapsed_ms = float(case_result.get("elapsed_ms", 0.0) or 0.0)
        assertion_detail = _escape_markdown_cell(
            _compact_markdown_text(case_result.get("assertion_detail", ""))
        )
        error = _escape_markdown_cell(_compact_markdown_text(case_result.get("error", "")))
        lines.append(
            f"| `{case_id}` | {status} | {elapsed_ms:.1f} | {assertion_detail} | {error} |"
        )

    failing_cases = [
        case_result
        for case_result in case_results
        if _format_case_status(case_result) in {"FAIL", "ERROR", "HALTED"}
    ]

    lines.extend(["", "## Failure Details", ""])
    if not failing_cases:
        lines.append("All cases passed.")
        lines.append("")
        return "\n".join(lines) + "\n"

    for case_result in failing_cases:
        case_id = str(case_result.get("test_id", "unknown"))
        status = _format_case_status(case_result)
        elapsed_ms = float(case_result.get("elapsed_ms", 0.0) or 0.0)
        lines.append(f"### `{case_id}` ({status})")
        lines.append("")
        lines.append(f"- Elapsed: `{elapsed_ms:.1f} ms`")
        lines.append(f"- Query: `{case_result.get('query', '')}`")
        lines.append(f"- Assertion detail: `{case_result.get('assertion_detail', '')}`")
        if case_result.get("error"):
            lines.append(f"- Error: `{case_result.get('error')}`")
        if case_result.get("halted"):
            lines.append(f"- Halt reason: `{case_result.get('halt_reason')}`")
        doc_ids = case_result.get("doc_ids")
        if isinstance(doc_ids, list) and doc_ids:
            lines.append(f"- Documents: `{', '.join(str(doc_id) for doc_id in doc_ids)}`")
        source_ids = case_result.get("source_identifiers")
        if isinstance(source_ids, list) and source_ids:
            lines.append(
                "- Source identifiers: "
                f"`{', '.join(str(source_id) for source_id in source_ids)}`"
            )

        expected_payload = case_result.get("expected")
        lines.extend(["", "Expected:", "```json", _format_json_block(expected_payload), "```"])

        answer_text = str(case_result.get("answer", "") or "")
        lines.extend(["", "Answer:", "```text", answer_text, "```"])

        lines.extend(["", "Tool Calls:"])
        lines.extend(_format_tool_calls_markdown(case_result))
        lines.append("")

    return "\n".join(lines) + "\n"


def _write_results_markdown(
    path: Path,
    run_summary: Dict[str, Any],
    case_results: Sequence[Dict[str, Any]],
) -> None:
    markdown = _build_results_markdown(run_summary, case_results, path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")


def _append_failure_details_for_run(
    lines: List[str],
    *,
    run_id: str,
    case_results: Sequence[Dict[str, Any]],
) -> None:
    failing_cases = [
        case_result
        for case_result in case_results
        if _format_case_status(case_result) in {"FAIL", "ERROR", "HALTED"}
    ]
    lines.append(f"### {run_id}")
    if not failing_cases:
        lines.append("No failing/error/halted cases.")
        lines.append("")
        return

    for case_result in failing_cases:
        case_id = str(case_result.get("test_id", "unknown"))
        status = _format_case_status(case_result)
        elapsed_ms = float(case_result.get("elapsed_ms", 0.0) or 0.0)
        lines.append(f"#### `{case_id}` ({status})")
        lines.append("")
        lines.append(f"- Elapsed: `{elapsed_ms:.1f} ms`")
        lines.append(f"- Query: `{case_result.get('query', '')}`")
        lines.append(f"- Assertion detail: `{case_result.get('assertion_detail', '')}`")
        if case_result.get("error"):
            lines.append(f"- Error: `{case_result.get('error')}`")
        if case_result.get("halted"):
            lines.append(f"- Halt reason: `{case_result.get('halt_reason')}`")
        doc_ids = case_result.get("doc_ids")
        if isinstance(doc_ids, list) and doc_ids:
            lines.append(f"- Documents: `{', '.join(str(doc_id) for doc_id in doc_ids)}`")
        source_ids = case_result.get("source_identifiers")
        if isinstance(source_ids, list) and source_ids:
            lines.append(
                "- Source identifiers: "
                f"`{', '.join(str(source_id) for source_id in source_ids)}`"
            )

        expected_payload = case_result.get("expected")
        lines.extend(["", "Expected:", "```json", _format_json_block(expected_payload), "```"])

        answer_text = str(case_result.get("answer", "") or "")
        lines.extend(["", "Answer:", "```text", answer_text, "```"])

        lines.extend(["", "Tool Calls:"])
        lines.extend(_format_tool_calls_markdown(case_result))
        lines.append("")


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
    prepare_started = time.perf_counter()
    dataset_dir = snapshot_root.expanduser().resolve() / dataset.id
    docs_dir = dataset_dir / SNAPSHOT_DOCS_DIRNAME
    manifest_path = dataset_dir / SNAPSHOT_MANIFEST_FILENAME

    docs_dir.mkdir(parents=True, exist_ok=True)

    doc_paths: Dict[str, Path] = {}
    doc_sha256: Dict[str, str] = {}
    docs_payload: Dict[str, Dict[str, Any]] = {}
    doc_prepare_timings_ms: Dict[str, Dict[str, Any]] = {}
    downloaded_docs = 0
    reused_docs = 0

    for doc_id, doc in dataset.docs.items():
        doc_started = time.perf_counter()
        ext = _extension_from_url(doc.url)
        filename = f"{doc_id}{ext}"
        file_path = docs_dir / filename

        action = "reused"
        if refresh or not file_path.exists():
            action = "downloaded"
            file_data = _download_document(doc.url, timeout_seconds)
            file_path.write_bytes(file_data)
            downloaded_docs += 1
        else:
            file_data = file_path.read_bytes()
            reused_docs += 1

        checksum = _sha256_bytes(file_data)
        relative_path = file_path.relative_to(dataset_dir)
        doc_elapsed_ms = (time.perf_counter() - doc_started) * 1000.0

        doc_paths[doc_id] = file_path
        doc_sha256[doc_id] = checksum
        docs_payload[doc_id] = {
            "id": doc.id,
            "title": doc.title,
            "url": doc.url,
            "path": str(relative_path),
            "sha256": checksum,
            "bytes": len(file_data),
            "prepare_action": action,
            "prepare_elapsed_ms": doc_elapsed_ms,
        }
        doc_prepare_timings_ms[doc_id] = {
            "action": action,
            "elapsed_ms": doc_elapsed_ms,
        }

    prepare_total_ms = (time.perf_counter() - prepare_started) * 1000.0
    timings_ms: Dict[str, float] = {
        TIMING_KEY_PREPARE_TOTAL_MS: prepare_total_ms,
        TIMING_KEY_DOWNLOAD_DOCS: float(downloaded_docs),
        TIMING_KEY_REUSED_DOCS: float(reused_docs),
    }

    _write_json(
        manifest_path,
        {
            "dataset_id": dataset.id,
            "dataset_source": str(dataset.source_path),
            "created_at": _format_timestamp(_utc_now()),
            "timings_ms": timings_ms,
            "doc_prepare_timings_ms": doc_prepare_timings_ms,
            "docs": docs_payload,
        },
    )

    return SnapshotManifest(
        dataset_id=dataset.id,
        dataset_dir=dataset_dir,
        manifest_path=manifest_path,
        doc_paths=doc_paths,
        doc_sha256=doc_sha256,
        timings_ms=timings_ms,
        doc_prepare_timings_ms=doc_prepare_timings_ms,
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
    timings_payload = payload.get("timings_ms")
    doc_prepare_timings_payload = payload.get("doc_prepare_timings_ms")
    parsed_timings: Dict[str, float] = {}
    if isinstance(timings_payload, dict):
        for key, value in timings_payload.items():
            if isinstance(value, (int, float)):
                parsed_timings[str(key)] = float(value)
    parsed_doc_prepare_timings: Dict[str, Dict[str, Any]] = {}
    if isinstance(doc_prepare_timings_payload, dict):
        for key, value in doc_prepare_timings_payload.items():
            if isinstance(value, dict):
                parsed_doc_prepare_timings[str(key)] = dict(value)

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
        timings_ms=parsed_timings,
        doc_prepare_timings_ms=parsed_doc_prepare_timings,
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


def _build_token_usage_entry(
    *,
    model_alias: Optional[str],
    input_tokens: int,
    output_tokens: int,
) -> Dict[str, Any]:
    return {
        "model_alias": model_alias,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


def _summarization_model_alias() -> str:
    model_config = MODELS.get(SUMMARIZATION_MODEL, {})
    return str(model_config.get("alias", SUMMARIZATION_MODEL))


def _usage_breakdown_with_totals(
    tracker: UsageTracker,
    model_alias: str,
) -> Dict[str, Any]:
    usage = tracker.get_usage_breakdown(model_alias)
    input_tokens = int(usage.get("input", 0) or 0)
    output_tokens = int(usage.get("output", 0) or 0)
    return _build_token_usage_entry(
        model_alias=model_alias,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _empty_token_usage_by_role(run: RunProfile) -> Dict[str, Dict[str, Any]]:
    return {
        TOKEN_USAGE_ROLE_MAIN: _build_token_usage_entry(
            model_alias=run.model_alias,
            input_tokens=0,
            output_tokens=0,
        ),
        TOKEN_USAGE_ROLE_SUMMARIZER: _build_token_usage_entry(
            model_alias=_summarization_model_alias(),
            input_tokens=0,
            output_tokens=0,
        ),
        TOKEN_USAGE_ROLE_AUDIT_PLANNER: _build_token_usage_entry(
            model_alias=AUDIT_PLANNER_MODEL_ALIAS_PLACEHOLDER,
            input_tokens=0,
            output_tokens=0,
        ),
    }


def _build_case_token_usage(
    *,
    run: RunProfile,
    usage_tracker: UsageTracker,
    summarization_tracker: UsageTracker,
) -> Dict[str, Dict[str, Any]]:
    token_usage = _empty_token_usage_by_role(run)
    token_usage[TOKEN_USAGE_ROLE_MAIN] = _usage_breakdown_with_totals(
        usage_tracker,
        run.model_alias,
    )
    token_usage[TOKEN_USAGE_ROLE_SUMMARIZER] = _usage_breakdown_with_totals(
        summarization_tracker,
        _summarization_model_alias(),
    )
    return token_usage


def _accumulate_token_usage(
    total: Dict[str, Any],
    current: Dict[str, Any],
) -> None:
    total["input_tokens"] += int(current.get("input_tokens", 0) or 0)
    total["output_tokens"] += int(current.get("output_tokens", 0) or 0)
    total["total_tokens"] += int(current.get("total_tokens", 0) or 0)


def _format_role_token_usage(
    summary: Dict[str, Any],
    role: str,
) -> str:
    token_usage = summary.get("token_usage_totals", {})
    if not isinstance(token_usage, dict):
        return "0/0/0"
    role_usage = token_usage.get(role, {})
    if not isinstance(role_usage, dict):
        return "0/0/0"
    input_tokens = int(role_usage.get("input_tokens", 0) or 0)
    output_tokens = int(role_usage.get("output_tokens", 0) or 0)
    total_tokens = int(role_usage.get("total_tokens", 0) or 0)
    return f"{input_tokens}/{output_tokens}/{total_tokens}"


def _new_case_timings_ms() -> Dict[str, Any]:
    return {
        TIMING_KEY_CASE_TOTAL_MS: 0.0,
        TIMING_KEY_SOURCE_PREPARE_MS: 0.0,
        TIMING_KEY_CLIENT_INIT_MS: 0.0,
        TIMING_KEY_RUN_TURN_MS: 0.0,
        TIMING_KEY_LLM_TOTAL_MS: 0.0,
        TIMING_KEY_TOOL_TOTAL_MS: 0.0,
        TIMING_KEY_LOCAL_INGESTION_MS: 0.0,
        TIMING_KEY_SHORTLIST_MS: 0.0,
        "llm_calls": 0,
        "tool_calls": 0,
        "local_ingestion_calls": 0,
        "shortlist_calls": 0,
    }


def _new_run_timing_totals_ms() -> Dict[str, float]:
    return {
        TIMING_KEY_CASE_TOTAL_MS: 0.0,
        TIMING_KEY_SOURCE_PREPARE_MS: 0.0,
        TIMING_KEY_CLIENT_INIT_MS: 0.0,
        TIMING_KEY_RUN_TURN_MS: 0.0,
        TIMING_KEY_LLM_TOTAL_MS: 0.0,
        TIMING_KEY_TOOL_TOTAL_MS: 0.0,
        TIMING_KEY_LOCAL_INGESTION_MS: 0.0,
        TIMING_KEY_SHORTLIST_MS: 0.0,
        TIMING_KEY_RUN_WALL_MS: 0.0,
    }


def _timing_total_ms(summary: Dict[str, Any], key: str) -> float:
    totals = summary.get("timing_totals_ms")
    if not isinstance(totals, dict):
        return 0.0
    return float(totals.get(key, 0.0) or 0.0)


def _format_timing_ms(value: float) -> str:
    return f"{value:.1f}"


def _parse_tool_arguments(raw_arguments: Any) -> Any:
    if raw_arguments is None:
        return {}
    if isinstance(raw_arguments, (dict, list, int, float, bool)):
        return raw_arguments
    if isinstance(raw_arguments, str):
        stripped = raw_arguments.strip()
        if not stripped:
            return {}
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return {"_raw": raw_arguments}
    return {"_raw": str(raw_arguments)}


def _serialize_tool_arguments(arguments: Any) -> str:
    try:
        return json.dumps(arguments, sort_keys=True, ensure_ascii=True)
    except TypeError:
        return json.dumps(str(arguments), ensure_ascii=True)


def _format_tool_arguments_for_report(arguments: Any) -> str:
    serialized = _serialize_tool_arguments(arguments)
    escaped = serialized.replace("|", "\\|").replace("`", "'")
    return f"`{escaped}`"


def _evaluate_case(
    *,
    run: RunProfile,
    dataset: DatasetSpec,
    test_case: DatasetTestCase,
    snapshot_manifest: Optional[SnapshotManifest],
    case_progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    case_started = time.perf_counter()
    timings_ms = _new_case_timings_ms()

    source_prepare_started = time.perf_counter()
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
    timings_ms[TIMING_KEY_SOURCE_PREPARE_MS] = (
        time.perf_counter() - source_prepare_started
    ) * 1000.0

    client_init_started = time.perf_counter()
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
    timings_ms[TIMING_KEY_CLIENT_INIT_MS] = (
        time.perf_counter() - client_init_started
    ) * 1000.0

    answer = ""
    notices: List[str] = []
    halted = False
    halt_reason: Optional[str] = None
    error: Optional[str] = None
    run_turn_started = 0.0
    phase_starts: Dict[str, float] = {}
    tool_calls: List[Dict[str, Any]] = []

    def _emit_case_progress(event: Dict[str, Any]) -> None:
        if case_progress_callback is None:
            return
        case_progress_callback(
            {
                "run_id": run.id,
                "test_id": test_case.id,
                **event,
            }
        )

    def _preload_status(message: str) -> None:
        _emit_case_progress(
            {
                "event": "external_status",
                "external_type": "preload",
                "message": message,
            }
        )

    def _summarization_status(message: Optional[str]) -> None:
        if not message:
            return
        _emit_case_progress(
            {
                "event": "external_status",
                "external_type": "summarizer",
                "message": message,
            }
        )

    def _turn_event(name: str, payload: Dict[str, Any]) -> None:
        if name not in {"llm_start", "llm_end", "tool_start", "tool_end"}:
            return
        external_type = "llm" if name.startswith("llm_") else "tool"
        if name == "tool_start":
            tool_name = str(payload.get("tool_name", "unknown_tool"))
            tool_arguments = _parse_tool_arguments(payload.get("tool_arguments"))
            tool_calls.append(
                {
                    "tool_name": tool_name,
                    "arguments": tool_arguments,
                }
            )
        phase_key = (
            f"{external_type}:{payload.get('turn')}:{payload.get('call_index')}"
            if external_type == "tool"
            else f"{external_type}:{payload.get('turn')}"
        )
        now = time.perf_counter()
        elapsed_ms: Optional[float] = None
        if name.endswith("_start"):
            phase_starts[phase_key] = now
        else:
            started = phase_starts.pop(phase_key, None)
            if started is not None:
                elapsed_ms = (now - started) * 1000.0
                if external_type == "llm":
                    timings_ms[TIMING_KEY_LLM_TOTAL_MS] += elapsed_ms
                    timings_ms["llm_calls"] += 1
                else:
                    timings_ms[TIMING_KEY_TOOL_TOTAL_MS] += elapsed_ms
                    timings_ms["tool_calls"] += 1
        trimmed_payload = {
            "turn": payload.get("turn"),
            "call_index": payload.get("call_index"),
            "total_calls": payload.get("total_calls"),
            "tool_name": payload.get("tool_name"),
            "use_tools": payload.get("use_tools"),
            "message_count": payload.get("message_count"),
            "has_tool_calls": payload.get("has_tool_calls"),
            "tool_arguments": payload.get("tool_arguments"),
            "elapsed_ms": elapsed_ms,
        }
        _emit_case_progress(
            {
                "event": "external_transition",
                "external_type": external_type,
                "phase": name,
                "payload": trimmed_payload,
            }
        )

    try:
        _emit_case_progress(
            {
                "event": "external_transition",
                "external_type": "run_turn",
                "phase": "start",
            }
        )
        run_turn_started = time.perf_counter()

        def _timed_local_ingestion_executor(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            _emit_case_progress(
                {
                    "event": "external_transition",
                    "external_type": "local_ingestion",
                    "phase": "start",
                }
            )
            local_started = time.perf_counter()
            try:
                return preload_local_research_sources(*args, **kwargs)
            finally:
                elapsed_ms = (time.perf_counter() - local_started) * 1000.0
                timings_ms[TIMING_KEY_LOCAL_INGESTION_MS] += elapsed_ms
                timings_ms["local_ingestion_calls"] += 1
                _emit_case_progress(
                    {
                        "event": "external_transition",
                        "external_type": "local_ingestion",
                        "phase": "end",
                        "elapsed_ms": elapsed_ms,
                    }
                )

        def _timed_shortlist_executor(*args: Any, **kwargs: Any) -> Dict[str, Any]:
            _emit_case_progress(
                {
                    "event": "external_transition",
                    "external_type": "shortlist",
                    "phase": "start",
                }
            )
            shortlist_started = time.perf_counter()
            try:
                return shortlist_prompt_sources(*args, **kwargs)
            finally:
                elapsed_ms = (time.perf_counter() - shortlist_started) * 1000.0
                timings_ms[TIMING_KEY_SHORTLIST_MS] += elapsed_ms
                timings_ms["shortlist_calls"] += 1
                _emit_case_progress(
                    {
                        "event": "external_transition",
                        "external_type": "shortlist",
                        "phase": "end",
                        "elapsed_ms": elapsed_ms,
                    }
                )

        result = client.run_turn(
            _build_turn_request(query_text, run),
            event_callback=_turn_event,
            preload_status_callback=_preload_status,
            summarization_status_callback=_summarization_status,
            local_ingestion_executor=_timed_local_ingestion_executor,
            shortlist_executor=_timed_shortlist_executor,
        )
        timings_ms[TIMING_KEY_RUN_TURN_MS] = (
            time.perf_counter() - run_turn_started
        ) * 1000.0
        _emit_case_progress(
            {
                "event": "external_transition",
                "external_type": "run_turn",
                "phase": "end",
                "elapsed_ms": timings_ms[TIMING_KEY_RUN_TURN_MS],
            }
        )
        answer = result.final_answer
        notices = list(result.notices)
        halted = bool(result.halted)
        halt_reason = result.halt_reason
    except Exception as exc:
        if run_turn_started > 0:
            timings_ms[TIMING_KEY_RUN_TURN_MS] = (
                time.perf_counter() - run_turn_started
            ) * 1000.0
        _emit_case_progress(
            {
                "event": "external_transition",
                "external_type": "run_turn",
                "phase": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_ms": timings_ms[TIMING_KEY_RUN_TURN_MS],
            }
        )
        error = f"{type(exc).__name__}: {exc}"

    elapsed_ms = (time.perf_counter() - case_started) * 1000.0
    timings_ms[TIMING_KEY_CASE_TOTAL_MS] = elapsed_ms

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
    token_usage = _build_case_token_usage(
        run=run,
        usage_tracker=usage_tracker,
        summarization_tracker=summarization_tracker,
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
        "tool_calls": tool_calls,
        "token_usage": token_usage,
        "timings_ms": timings_ms,
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
    token_usage_totals = _empty_token_usage_by_role(run)
    timing_totals_ms = _new_run_timing_totals_ms()
    llm_calls = 0
    tool_calls = 0
    local_ingestion_calls = 0
    shortlist_calls = 0
    tool_call_breakdown_map: Dict[str, Dict[str, Any]] = {}
    tool_call_counts: Dict[str, int] = {}

    for item in case_results:
        case_token_usage = item.get("token_usage")
        if not isinstance(case_token_usage, dict):
            continue
        for role in TOKEN_USAGE_ROLES:
            role_usage = case_token_usage.get(role)
            if not isinstance(role_usage, dict):
                continue
            _accumulate_token_usage(token_usage_totals[role], role_usage)

    for item in case_results:
        explicit_tool_calls_count = 0
        case_tool_calls = item.get("tool_calls")
        if isinstance(case_tool_calls, list):
            for call in case_tool_calls:
                if not isinstance(call, dict):
                    continue
                tool_name = str(call.get("tool_name", "unknown_tool"))
                arguments = call.get("arguments", {})
                signature = f"{tool_name}\u001f{_serialize_tool_arguments(arguments)}"
                if signature not in tool_call_breakdown_map:
                    tool_call_breakdown_map[signature] = {
                        "tool_name": tool_name,
                        "arguments": arguments,
                        "count": 0,
                    }
                tool_call_breakdown_map[signature]["count"] += 1
                tool_call_counts[tool_name] = tool_call_counts.get(tool_name, 0) + 1
                explicit_tool_calls_count += 1

        if explicit_tool_calls_count == 0:
            case_tool_usage = item.get("tool_usage")
            if isinstance(case_tool_usage, dict):
                for tool_name, raw_count in case_tool_usage.items():
                    count = int(raw_count or 0)
                    if count <= 0:
                        continue
                    tool_name_str = str(tool_name)
                    signature = f"{tool_name_str}\u001f{_serialize_tool_arguments({})}"
                    if signature not in tool_call_breakdown_map:
                        tool_call_breakdown_map[signature] = {
                            "tool_name": tool_name_str,
                            "arguments": {},
                            "count": 0,
                        }
                    tool_call_breakdown_map[signature]["count"] += count
                    tool_call_counts[tool_name_str] = (
                        tool_call_counts.get(tool_name_str, 0) + count
                    )

        case_timings = item.get("timings_ms")
        if not isinstance(case_timings, dict):
            continue
        timing_totals_ms[TIMING_KEY_CASE_TOTAL_MS] += float(
            case_timings.get(TIMING_KEY_CASE_TOTAL_MS, 0.0) or 0.0
        )
        timing_totals_ms[TIMING_KEY_SOURCE_PREPARE_MS] += float(
            case_timings.get(TIMING_KEY_SOURCE_PREPARE_MS, 0.0) or 0.0
        )
        timing_totals_ms[TIMING_KEY_CLIENT_INIT_MS] += float(
            case_timings.get(TIMING_KEY_CLIENT_INIT_MS, 0.0) or 0.0
        )
        timing_totals_ms[TIMING_KEY_RUN_TURN_MS] += float(
            case_timings.get(TIMING_KEY_RUN_TURN_MS, 0.0) or 0.0
        )
        timing_totals_ms[TIMING_KEY_LLM_TOTAL_MS] += float(
            case_timings.get(TIMING_KEY_LLM_TOTAL_MS, 0.0) or 0.0
        )
        timing_totals_ms[TIMING_KEY_TOOL_TOTAL_MS] += float(
            case_timings.get(TIMING_KEY_TOOL_TOTAL_MS, 0.0) or 0.0
        )
        timing_totals_ms[TIMING_KEY_LOCAL_INGESTION_MS] += float(
            case_timings.get(TIMING_KEY_LOCAL_INGESTION_MS, 0.0) or 0.0
        )
        timing_totals_ms[TIMING_KEY_SHORTLIST_MS] += float(
            case_timings.get(TIMING_KEY_SHORTLIST_MS, 0.0) or 0.0
        )
        llm_calls += int(case_timings.get("llm_calls", 0) or 0)
        tool_calls += int(case_timings.get("tool_calls", 0) or 0)
        local_ingestion_calls += int(case_timings.get("local_ingestion_calls", 0) or 0)
        shortlist_calls += int(case_timings.get("shortlist_calls", 0) or 0)

    timing_averages_ms = {
        key: (value / total) if total else 0.0
        for key, value in timing_totals_ms.items()
        if key != TIMING_KEY_RUN_WALL_MS
    }
    tool_call_breakdown = sorted(
        tool_call_breakdown_map.values(),
        key=lambda item: (-int(item.get("count", 0)), str(item.get("tool_name", ""))),
    )

    return {
        "run_id": run.id,
        "model_alias": run.model_alias,
        "research_mode": run.research_mode,
        "source_provider": run.resolved_source_provider(),
        "parameters": dict(run.parameters),
        "disabled_tools": sorted(run.disabled_tools),
        "total_cases": total,
        "passed_cases": passed,
        "failed_cases": failed,
        "error_cases": errored,
        "halted_cases": halted,
        "pass_rate": (passed / total) if total else 0.0,
        "avg_elapsed_ms": avg_ms,
        "tool_call_counts": tool_call_counts,
        "tool_call_breakdown": tool_call_breakdown,
        "token_usage_totals": token_usage_totals,
        "timing_totals_ms": timing_totals_ms,
        "timing_averages_ms": timing_averages_ms,
        "timing_counts": {
            "llm_calls": llm_calls,
            "tool_calls": tool_calls,
            "local_ingestion_calls": local_ingestion_calls,
            "shortlist_calls": shortlist_calls,
        },
    }


def _build_markdown_report(
    dataset: DatasetSpec,
    output_dir: Path,
    run_summaries: Sequence[Dict[str, Any]],
    run_case_results: Optional[Dict[str, Sequence[Dict[str, Any]]]] = None,
) -> str:
    lines = [
        f"# Research Eval Report ({dataset.id})",
        "",
        f"Output directory: `{output_dir}`",
        "",
        (
            "| Run | Mode | Model | Provider | Disabled Tools | Cases | Passed | Failed | Errors | Halted | "
            "Pass Rate | Avg ms | Run Wall ms | RunTurn ms | LLM ms | Tool ms | "
            "Local Ingest ms | Shortlist ms | Main Tok (in/out/total) | "
            "Summarizer Tok (in/out/total) | Audit Planner Tok (in/out/total) |"
        ),
        (
            "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | "
            "---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
        ),
    ]

    for summary in run_summaries:
        mode_label = "research" if summary["research_mode"] else "standard"
        disabled_tools = summary.get("disabled_tools", [])
        disabled_tools_text = (
            ", ".join(str(tool) for tool in disabled_tools)
            if isinstance(disabled_tools, list) and disabled_tools
            else "-"
        )
        lines.append(
            "| {run_id} | {mode} | {model} | {provider} | {disabled_tools} | {total} | {passed} | {failed} | {errors} | {halted} | {rate:.1%} | {avg:.1f} | {run_wall_ms} | {run_turn_ms} | {llm_ms} | {tool_ms} | {local_ingest_ms} | {shortlist_ms} | {main_tokens} | {sum_tokens} | {audit_tokens} |".format(
                run_id=summary["run_id"],
                mode=mode_label,
                model=summary["model_alias"],
                provider=summary["source_provider"],
                disabled_tools=disabled_tools_text,
                total=summary["total_cases"],
                passed=summary["passed_cases"],
                failed=summary["failed_cases"],
                errors=summary.get("error_cases", 0),
                halted=summary.get("halted_cases", 0),
                rate=float(summary["pass_rate"]),
                avg=float(summary["avg_elapsed_ms"]),
                run_wall_ms=_format_timing_ms(
                    _timing_total_ms(summary, TIMING_KEY_RUN_WALL_MS)
                ),
                run_turn_ms=_format_timing_ms(
                    _timing_total_ms(summary, TIMING_KEY_RUN_TURN_MS)
                ),
                llm_ms=_format_timing_ms(_timing_total_ms(summary, TIMING_KEY_LLM_TOTAL_MS)),
                tool_ms=_format_timing_ms(
                    _timing_total_ms(summary, TIMING_KEY_TOOL_TOTAL_MS)
                ),
                local_ingest_ms=_format_timing_ms(
                    _timing_total_ms(summary, TIMING_KEY_LOCAL_INGESTION_MS)
                ),
                shortlist_ms=_format_timing_ms(
                    _timing_total_ms(summary, TIMING_KEY_SHORTLIST_MS)
                ),
                main_tokens=_format_role_token_usage(summary, TOKEN_USAGE_ROLE_MAIN),
                sum_tokens=_format_role_token_usage(
                    summary,
                    TOKEN_USAGE_ROLE_SUMMARIZER,
                ),
                audit_tokens=_format_role_token_usage(
                    summary,
                    TOKEN_USAGE_ROLE_AUDIT_PLANNER,
                ),
            )
        )

    lines.extend(["", "## Tool Call Totals", ""])
    for summary in run_summaries:
        run_id = str(summary.get("run_id", "unknown"))
        lines.append(f"### {run_id}")
        raw_counts = summary.get("tool_call_counts")
        tool_totals: Dict[str, int] = {}
        if isinstance(raw_counts, dict):
            for tool_name, count in raw_counts.items():
                parsed_count = int(count or 0)
                if parsed_count > 0:
                    tool_totals[str(tool_name)] = parsed_count
        if not tool_totals:
            breakdown = summary.get("tool_call_breakdown")
            if isinstance(breakdown, list):
                for item in breakdown:
                    if not isinstance(item, dict):
                        continue
                    tool_name = str(item.get("tool_name", "unknown_tool"))
                    count = int(item.get("count", 0) or 0)
                    if count > 0:
                        tool_totals[tool_name] = tool_totals.get(tool_name, 0) + count

        if not tool_totals:
            lines.append("No tool calls recorded.")
            lines.append("")
            continue

        ordered_totals = sorted(tool_totals.items(), key=lambda item: (-item[1], item[0]))
        total_calls = sum(count for _, count in ordered_totals)
        lines.append(f"Total tool calls: `{total_calls}`")
        lines.append("")
        lines.append("| Tool | Total Calls |")
        lines.append("| --- | ---: |")
        for tool_name, count in ordered_totals:
            lines.append(f"| `{tool_name}` | {count} |")
        lines.append("")

    lines.extend(["", "## Tool Call Breakdown", ""])
    for summary in run_summaries:
        run_id = str(summary.get("run_id", "unknown"))
        lines.append(f"### {run_id}")
        breakdown = summary.get("tool_call_breakdown", [])
        if not isinstance(breakdown, list) or not breakdown:
            lines.append("No tool calls recorded.")
            lines.append("")
            continue

        lines.append("| Tool | Calls | Arguments |")
        lines.append("| --- | ---: | --- |")
        for item in breakdown:
            if not isinstance(item, dict):
                continue
            tool_name = str(item.get("tool_name", "unknown_tool"))
            count = int(item.get("count", 0) or 0)
            arguments = item.get("arguments", {})
            lines.append(
                f"| `{tool_name}` | {count} | {_format_tool_arguments_for_report(arguments)} |"
            )
        lines.append("")

    if isinstance(run_case_results, dict):
        lines.extend(["", "## Case Failure Details", ""])
        for summary in run_summaries:
            run_id = str(summary.get("run_id", "unknown"))
            case_results = run_case_results.get(run_id)
            if not isinstance(case_results, list):
                lines.append(f"### {run_id}")
                lines.append("No case details found.")
                lines.append("")
                continue
            _append_failure_details_for_run(lines, run_id=run_id, case_results=case_results)

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
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Path:
    """Execute all selected run profiles and persist evaluation artifacts."""
    session_started = time.perf_counter()
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
    run_case_results: Dict[str, List[Dict[str, Any]]] = {}
    run_total = len(selected_runs)

    for run_index, run in enumerate(selected_runs, start=1):
        run_started = time.perf_counter()
        if (
            run.resolved_source_provider() == SOURCE_PROVIDER_LOCAL_SNAPSHOT
            and snapshot_manifest is None
        ):
            raise ValueError(
                "Run requires local_snapshot provider but snapshot manifest is missing."
            )

        run_dir = output_dir / run.id
        runtime_paths = build_runtime_paths(run_dir)
        case_total = len(dataset.tests)
        if progress_callback is not None:
            progress_callback(
                {
                    "event": "run_start",
                    "run_id": run.id,
                    "run_index": run_index,
                    "run_total": run_total,
                    "case_total": case_total,
                }
            )

        with isolated_asky_runtime(runtime_paths):
            _initialize_runtime_storage()
            case_results: List[Dict[str, Any]] = []
            for case_index, test_case in enumerate(dataset.tests, start=1):
                if progress_callback is not None:
                    progress_callback(
                        {
                            "event": "case_start",
                            "run_id": run.id,
                            "case_id": test_case.id,
                            "case_index": case_index,
                            "case_total": case_total,
                        }
                    )
                case_result = _evaluate_case(
                    run=run,
                    dataset=dataset,
                    test_case=test_case,
                    snapshot_manifest=snapshot_manifest,
                    case_progress_callback=progress_callback,
                )
                case_results.append(case_result)
                if progress_callback is not None:
                    progress_callback(
                        {
                            "event": "case_end",
                            "run_id": run.id,
                            "case_id": test_case.id,
                            "case_index": case_index,
                            "case_total": case_total,
                            "pass": bool(case_result.get("pass")),
                            "halted": bool(case_result.get("halted")),
                            "error": case_result.get("error"),
                            "elapsed_ms": float(case_result.get("elapsed_ms", 0.0) or 0.0),
                        }
                    )

        run_summary = _summarize_run(run, case_results)
        run_wall_ms = (time.perf_counter() - run_started) * 1000.0
        timing_totals = run_summary.get("timing_totals_ms")
        if isinstance(timing_totals, dict):
            timing_totals[TIMING_KEY_RUN_WALL_MS] = run_wall_ms
        results_jsonl_path = runtime_paths.artifacts_dir / RUN_RESULTS_FILENAME
        _write_jsonl(results_jsonl_path, case_results)
        _write_json(runtime_paths.artifacts_dir / RUN_SUMMARY_FILENAME, run_summary)
        _write_results_markdown(
            runtime_paths.artifacts_dir / RUN_RESULTS_MARKDOWN_FILENAME,
            run_summary,
            case_results,
        )
        run_summaries.append(run_summary)
        run_case_results[run.id] = case_results
        if progress_callback is not None:
            progress_callback(
                {
                    "event": "run_end",
                    "run_id": run.id,
                    "run_index": run_index,
                    "run_total": run_total,
                    "passed_cases": int(run_summary.get("passed_cases", 0) or 0),
                    "total_cases": int(run_summary.get("total_cases", 0) or 0),
                    "failed_cases": int(run_summary.get("failed_cases", 0) or 0),
                    "error_cases": int(run_summary.get("error_cases", 0) or 0),
                    "halted_cases": int(run_summary.get("halted_cases", 0) or 0),
                    "run_wall_ms": run_wall_ms,
                }
            )

    session_wall_ms = (time.perf_counter() - session_started) * 1000.0
    runs_wall_ms = sum(
        _timing_total_ms(summary, TIMING_KEY_RUN_WALL_MS) for summary in run_summaries
    )
    session_summary = {
        "dataset_id": dataset.id,
        "created_at": _format_timestamp(_utc_now()),
        "run_count": len(run_summaries),
        "timing_totals_ms": {
            TIMING_KEY_SESSION_WALL_MS: session_wall_ms,
            "runs_wall_ms": runs_wall_ms,
        },
        "runs": run_summaries,
    }
    _write_json(output_dir / SESSION_SUMMARY_FILENAME, session_summary)

    report_text = _build_markdown_report(
        dataset,
        output_dir,
        run_summaries,
        run_case_results=run_case_results,
    )
    report_path = output_dir / SESSION_REPORT_FILENAME
    report_path.write_text(report_text, encoding="utf-8")

    return output_dir


def regenerate_report(dataset: DatasetSpec, output_dir: Path) -> Path:
    """Regenerate markdown report from stored run summaries."""
    resolved_output_dir = output_dir.expanduser().resolve()
    run_summaries: List[Dict[str, Any]] = []
    run_case_results: Dict[str, List[Dict[str, Any]]] = {}

    for run_dir in sorted(resolved_output_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        results_path = run_dir / "artifacts" / RUN_RESULTS_FILENAME
        summary_path = run_dir / "artifacts" / RUN_SUMMARY_FILENAME
        if not summary_path.exists():
            continue
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            run_summaries.append(payload)
            if results_path.exists():
                case_results = _read_jsonl(results_path)
                run_case_results[str(payload.get("run_id", run_dir.name))] = case_results
                _write_results_markdown(
                    run_dir / "artifacts" / RUN_RESULTS_MARKDOWN_FILENAME,
                    payload,
                    case_results,
                )

    if not run_summaries:
        raise ValueError(f"No run summaries found in {resolved_output_dir}.")

    report_text = _build_markdown_report(
        dataset,
        resolved_output_dir,
        run_summaries,
        run_case_results=run_case_results,
    )
    report_path = resolved_output_dir / SESSION_REPORT_FILENAME
    report_path.write_text(report_text, encoding="utf-8")
    return report_path
