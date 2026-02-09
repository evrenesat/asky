"""Answer assertion helpers for research pipeline evaluations."""

from __future__ import annotations

import re
from dataclasses import dataclass

from asky.evals.research_pipeline.dataset import (
    EXPECTED_TYPE_CONTAINS,
    EXPECTED_TYPE_REGEX,
    DatasetExpected,
)

MISSING_CONTEXT_SNIPPET = 200


@dataclass(frozen=True)
class AssertionResult:
    """Outcome of evaluating one answer expectation."""

    passed: bool
    detail: str


def _contains_assertion(answer: str, expected_text: str) -> AssertionResult:
    if expected_text in answer:
        return AssertionResult(passed=True, detail="contains assertion passed")

    preview = answer[:MISSING_CONTEXT_SNIPPET]
    return AssertionResult(
        passed=False,
        detail=(
            "contains assertion failed: expected substring not found. "
            f"expected={expected_text!r} answer_preview={preview!r}"
        ),
    )


def _regex_assertion(answer: str, pattern: str) -> AssertionResult:
    try:
        matched = re.search(pattern, answer) is not None
    except re.error as exc:
        return AssertionResult(
            passed=False,
            detail=f"regex assertion failed to compile pattern: {exc}",
        )

    if matched:
        return AssertionResult(passed=True, detail="regex assertion passed")

    preview = answer[:MISSING_CONTEXT_SNIPPET]
    return AssertionResult(
        passed=False,
        detail=(
            "regex assertion failed: pattern not matched. "
            f"pattern={pattern!r} answer_preview={preview!r}"
        ),
    )


def evaluate_answer(answer: str, expected: DatasetExpected) -> AssertionResult:
    """Evaluate one model answer against one expectation."""
    if expected.type == EXPECTED_TYPE_CONTAINS:
        if expected.text is None:
            return AssertionResult(
                passed=False,
                detail="contains assertion failed: expected.text is missing",
            )
        return _contains_assertion(answer, expected.text)

    if expected.type == EXPECTED_TYPE_REGEX:
        if expected.pattern is None:
            return AssertionResult(
                passed=False,
                detail="regex assertion failed: expected.pattern is missing",
            )
        return _regex_assertion(answer, expected.pattern)

    return AssertionResult(
        passed=False,
        detail=f"unsupported assertion type: {expected.type}",
    )
