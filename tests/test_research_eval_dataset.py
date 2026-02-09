import json

import pytest

from asky.evals.research_pipeline.dataset import load_dataset


def test_load_dataset_normalizes_doc_id_and_doc_ids(tmp_path):
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(
        json.dumps(
            {
                "id": "demo",
                "docs": [
                    {"id": "d1", "title": "Doc 1", "url": "https://example.com/1"},
                    {"id": "d2", "title": "Doc 2", "url": "https://example.com/2"},
                ],
                "tests": [
                    {
                        "id": "t1",
                        "doc_id": "d1",
                        "query": "q1",
                        "expected": {"type": "contains", "text": "abc"},
                    },
                    {
                        "id": "t2",
                        "doc_ids": ["d1", "d2"],
                        "query": "q2",
                        "expected": {"type": "regex", "pattern": "a.*b"},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    dataset = load_dataset(dataset_path)

    assert dataset.id == "demo"
    assert dataset.tests[0].doc_ids == ["d1"]
    assert dataset.tests[1].doc_ids == ["d1", "d2"]


def test_load_dataset_rejects_unknown_doc_reference(tmp_path):
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(
        json.dumps(
            {
                "id": "demo",
                "docs": [{"id": "d1", "title": "Doc 1", "url": "https://example.com/1"}],
                "tests": [
                    {
                        "id": "t1",
                        "doc_id": "missing",
                        "query": "q1",
                        "expected": {"type": "contains", "text": "abc"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown doc id"):
        load_dataset(dataset_path)
