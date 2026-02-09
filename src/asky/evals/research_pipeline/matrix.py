"""Run-matrix parsing for research pipeline evaluations."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

SOURCE_PROVIDER_AUTO = "auto"
SOURCE_PROVIDER_LOCAL_SNAPSHOT = "local_snapshot"
SOURCE_PROVIDER_LIVE_WEB = "live_web"
SOURCE_PROVIDER_MOCK_WEB = "mock_web"
SUPPORTED_SOURCE_PROVIDERS = frozenset(
    {
        SOURCE_PROVIDER_AUTO,
        SOURCE_PROVIDER_LOCAL_SNAPSHOT,
        SOURCE_PROVIDER_LIVE_WEB,
        SOURCE_PROVIDER_MOCK_WEB,
    }
)


@dataclass(frozen=True)
class RunProfile:
    """Configuration for one model/profile evaluation run."""

    id: str
    model_alias: str
    research_mode: bool = True
    lean: bool = False
    preload_local_sources: bool = True
    preload_shortlist: bool = True
    save_history: bool = False
    source_provider: str = SOURCE_PROVIDER_AUTO
    disabled_tools: Set[str] = field(default_factory=set)
    parameters: Dict[str, Any] = field(default_factory=dict)
    additional_source_context: Optional[str] = None
    query_prefix: Optional[str] = None
    query_suffix: Optional[str] = None

    def resolved_source_provider(self) -> str:
        """Resolve provider mode when run uses automatic provider selection."""
        if self.source_provider != SOURCE_PROVIDER_AUTO:
            return self.source_provider
        if self.research_mode:
            return SOURCE_PROVIDER_LOCAL_SNAPSHOT
        return SOURCE_PROVIDER_LIVE_WEB


@dataclass(frozen=True)
class MatrixSpec:
    """Parsed matrix definition with one or more run profiles."""

    runs: List[RunProfile]
    source_path: Path
    dataset_path: Optional[Path] = None
    snapshot_root: Optional[Path] = None
    output_root: Optional[Path] = None


def _require_non_empty_string(data: Dict[str, Any], field_name: str, context: str) -> str:
    value = data.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} requires non-empty string field '{field_name}'.")
    return value.strip()


def _parse_disabled_tools(raw_value: Any, run_id: str) -> Set[str]:
    if raw_value is None:
        return set()
    if isinstance(raw_value, str):
        tokens = [part.strip() for part in raw_value.split(",")]
        return {part for part in tokens if part}
    if isinstance(raw_value, list):
        values: Set[str] = set()
        for item in raw_value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError(
                    f"Run '{run_id}' disabled_tools entries must be non-empty strings."
                )
            values.add(item.strip())
        return values
    raise ValueError(f"Run '{run_id}' disabled_tools must be string or list.")


def _parse_parameters(raw_value: Any, run_id: str) -> Dict[str, Any]:
    if raw_value is None:
        return {}
    if not isinstance(raw_value, dict):
        raise ValueError(f"Run '{run_id}' parameters must be a table/object.")
    return dict(raw_value)


def _resolve_optional_path(base_path: Path, raw_value: Any, field_name: str) -> Optional[Path]:
    if raw_value is None:
        return None
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise ValueError(f"Matrix field '{field_name}' must be a non-empty string path.")

    raw_path = str(raw_value).strip()
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        return candidate

    # Path resolution policy:
    # - ./ or ../ paths are matrix-file relative for portability.
    # - bare relative paths are cwd-relative (typically repo root).
    if raw_path.startswith("./") or raw_path.startswith("../"):
        return (base_path.parent / candidate).resolve()
    return candidate.resolve()


def _parse_run_profile(raw_run: Dict[str, Any]) -> RunProfile:
    run_id = _require_non_empty_string(raw_run, "id", "Run")
    provider = str(raw_run.get("source_provider", SOURCE_PROVIDER_AUTO)).strip().lower()
    if provider not in SUPPORTED_SOURCE_PROVIDERS:
        raise ValueError(
            f"Run '{run_id}' has unsupported source_provider '{provider}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_SOURCE_PROVIDERS))}"
        )

    additional_source_context = raw_run.get("additional_source_context")
    if additional_source_context is not None and not isinstance(
        additional_source_context,
        str,
    ):
        raise ValueError(
            f"Run '{run_id}' additional_source_context must be a string when provided."
        )

    query_prefix = raw_run.get("query_prefix")
    if query_prefix is not None and not isinstance(query_prefix, str):
        raise ValueError(f"Run '{run_id}' query_prefix must be a string when provided.")

    query_suffix = raw_run.get("query_suffix")
    if query_suffix is not None and not isinstance(query_suffix, str):
        raise ValueError(f"Run '{run_id}' query_suffix must be a string when provided.")

    return RunProfile(
        id=run_id,
        model_alias=_require_non_empty_string(raw_run, "model_alias", f"Run '{run_id}'"),
        research_mode=bool(raw_run.get("research_mode", True)),
        lean=bool(raw_run.get("lean", False)),
        preload_local_sources=bool(raw_run.get("preload_local_sources", True)),
        preload_shortlist=bool(raw_run.get("preload_shortlist", True)),
        save_history=bool(raw_run.get("save_history", False)),
        source_provider=provider,
        disabled_tools=_parse_disabled_tools(raw_run.get("disabled_tools"), run_id),
        parameters=_parse_parameters(raw_run.get("parameters"), run_id),
        additional_source_context=(additional_source_context.strip() if isinstance(additional_source_context, str) and additional_source_context.strip() else None),
        query_prefix=(query_prefix.strip() if isinstance(query_prefix, str) and query_prefix.strip() else None),
        query_suffix=(query_suffix.strip() if isinstance(query_suffix, str) and query_suffix.strip() else None),
    )


def load_matrix(path: Path) -> MatrixSpec:
    """Load a matrix definition from TOML."""
    matrix_path = path.expanduser().resolve()
    with matrix_path.open("rb") as handle:
        payload = tomllib.load(handle)

    raw_runs = payload.get("runs")
    if not isinstance(raw_runs, list) or not raw_runs:
        raise ValueError("Matrix must include at least one [[runs]] entry.")

    runs: List[RunProfile] = []
    seen_ids = set()
    for raw_run in raw_runs:
        if not isinstance(raw_run, dict):
            raise ValueError("Each matrix run entry must be a table/object.")
        profile = _parse_run_profile(raw_run)
        if profile.id in seen_ids:
            raise ValueError(f"Duplicate run id '{profile.id}'.")
        seen_ids.add(profile.id)
        runs.append(profile)

    dataset_path = _resolve_optional_path(matrix_path, payload.get("dataset"), "dataset")
    snapshot_root = _resolve_optional_path(
        matrix_path,
        payload.get("snapshot_root"),
        "snapshot_root",
    )
    output_root = _resolve_optional_path(
        matrix_path,
        payload.get("output_root"),
        "output_root",
    )

    return MatrixSpec(
        runs=runs,
        source_path=matrix_path,
        dataset_path=dataset_path,
        snapshot_root=snapshot_root,
        output_root=output_root,
    )
