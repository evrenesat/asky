"""Dataset loading and validation for research pipeline evaluations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

DATASET_SUFFIX_YAML = ".yaml"
DATASET_SUFFIX_YML = ".yml"
DATASET_SUFFIX_JSON = ".json"
SUPPORTED_DATASET_SUFFIXES = frozenset(
    {
        DATASET_SUFFIX_YAML,
        DATASET_SUFFIX_YML,
        DATASET_SUFFIX_JSON,
    }
)
EXPECTED_TYPE_CONTAINS = "contains"
EXPECTED_TYPE_REGEX = "regex"


@dataclass(frozen=True)
class DatasetDocument:
    """One source document used by evaluation cases."""

    id: str
    title: str
    url: str


@dataclass(frozen=True)
class DatasetExpected:
    """Expected answer matcher configuration for one test case."""

    type: str
    text: Optional[str] = None
    pattern: Optional[str] = None


@dataclass(frozen=True)
class DatasetTestCase:
    """One evaluation test case."""

    id: str
    doc_ids: List[str]
    query: str
    expected: DatasetExpected


@dataclass(frozen=True)
class DatasetSpec:
    """Complete dataset definition."""

    id: str
    docs: Dict[str, DatasetDocument]
    tests: List[DatasetTestCase]
    source_path: Path


def _require_non_empty_string(data: Dict[str, Any], field_name: str, context: str) -> str:
    value = data.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} requires non-empty string field '{field_name}'.")
    return value.strip()


def _load_yaml_file(path: Path) -> Dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - dependency error path
        raise RuntimeError(
            "YAML dataset loading requires PyYAML. "
            "Install it or convert dataset to JSON."
        ) from exc

    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if not isinstance(loaded, dict):
        raise ValueError(f"Dataset root must be a mapping: {path}")
    return loaded


def _load_json_file(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise ValueError(f"Dataset root must be a mapping: {path}")
    return loaded


def _load_dataset_payload(path: Path) -> Dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_DATASET_SUFFIXES:
        raise ValueError(
            f"Unsupported dataset extension '{suffix}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_DATASET_SUFFIXES))}"
        )
    if suffix in {DATASET_SUFFIX_YAML, DATASET_SUFFIX_YML}:
        return _load_yaml_file(path)
    return _load_json_file(path)


def _normalize_doc_ids(test_data: Dict[str, Any], test_id: str) -> List[str]:
    doc_ids: List[str] = []

    single_doc = test_data.get("doc_id")
    if isinstance(single_doc, str) and single_doc.strip():
        doc_ids.append(single_doc.strip())

    raw_doc_ids = test_data.get("doc_ids")
    if raw_doc_ids is not None:
        if not isinstance(raw_doc_ids, list):
            raise ValueError(f"Test '{test_id}' has non-list doc_ids.")
        for entry in raw_doc_ids:
            if not isinstance(entry, str) or not entry.strip():
                raise ValueError(f"Test '{test_id}' includes invalid doc_ids entry.")
            doc_ids.append(entry.strip())

    deduped: List[str] = []
    seen = set()
    for doc_id in doc_ids:
        if doc_id in seen:
            continue
        seen.add(doc_id)
        deduped.append(doc_id)

    if not deduped:
        raise ValueError(
            f"Test '{test_id}' must define doc_id or doc_ids with at least one document."
        )

    return deduped


def _parse_expected(test_data: Dict[str, Any], test_id: str) -> DatasetExpected:
    raw_expected = test_data.get("expected")
    if not isinstance(raw_expected, dict):
        raise ValueError(f"Test '{test_id}' requires an expected mapping.")

    expected_type = _require_non_empty_string(
        raw_expected,
        "type",
        f"Test '{test_id}' expected",
    ).lower()

    if expected_type == EXPECTED_TYPE_CONTAINS:
        text = _require_non_empty_string(raw_expected, "text", f"Test '{test_id}' expected")
        return DatasetExpected(type=expected_type, text=text)

    if expected_type == EXPECTED_TYPE_REGEX:
        pattern = _require_non_empty_string(
            raw_expected,
            "pattern",
            f"Test '{test_id}' expected",
        )
        return DatasetExpected(type=expected_type, pattern=pattern)

    raise ValueError(
        f"Test '{test_id}' expected.type must be '{EXPECTED_TYPE_CONTAINS}' "
        f"or '{EXPECTED_TYPE_REGEX}'."
    )


def load_dataset(path: Path) -> DatasetSpec:
    """Load and validate a dataset file."""
    dataset_path = path.expanduser().resolve()
    payload = _load_dataset_payload(dataset_path)

    dataset_id = str(payload.get("id") or dataset_path.stem).strip()
    if not dataset_id:
        raise ValueError("Dataset id cannot be empty.")

    raw_docs = payload.get("docs")
    if not isinstance(raw_docs, list) or not raw_docs:
        raise ValueError("Dataset must define a non-empty 'docs' list.")

    docs: Dict[str, DatasetDocument] = {}
    for raw_doc in raw_docs:
        if not isinstance(raw_doc, dict):
            raise ValueError("Each docs entry must be a mapping.")
        doc_id = _require_non_empty_string(raw_doc, "id", "Doc entry")
        if doc_id in docs:
            raise ValueError(f"Duplicate doc id '{doc_id}'.")
        docs[doc_id] = DatasetDocument(
            id=doc_id,
            title=_require_non_empty_string(raw_doc, "title", f"Doc '{doc_id}'"),
            url=_require_non_empty_string(raw_doc, "url", f"Doc '{doc_id}'"),
        )

    raw_tests = payload.get("tests")
    if not isinstance(raw_tests, list) or not raw_tests:
        raise ValueError("Dataset must define a non-empty 'tests' list.")

    tests: List[DatasetTestCase] = []
    seen_test_ids = set()
    for raw_test in raw_tests:
        if not isinstance(raw_test, dict):
            raise ValueError("Each tests entry must be a mapping.")

        test_id = _require_non_empty_string(raw_test, "id", "Test entry")
        if test_id in seen_test_ids:
            raise ValueError(f"Duplicate test id '{test_id}'.")
        seen_test_ids.add(test_id)

        doc_ids = _normalize_doc_ids(raw_test, test_id)
        for doc_id in doc_ids:
            if doc_id not in docs:
                raise ValueError(
                    f"Test '{test_id}' references unknown doc id '{doc_id}'."
                )

        tests.append(
            DatasetTestCase(
                id=test_id,
                doc_ids=doc_ids,
                query=_require_non_empty_string(raw_test, "query", f"Test '{test_id}'"),
                expected=_parse_expected(raw_test, test_id),
            )
        )

    return DatasetSpec(
        id=dataset_id,
        docs=docs,
        tests=tests,
        source_path=dataset_path,
    )
