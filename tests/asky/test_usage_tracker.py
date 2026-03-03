import pytest
from asky.core.api_client import UsageTracker


def test_add_usage_accumulates_correctly():
    tracker = UsageTracker()
    tracker.add_usage("model_a", 10, 5)
    tracker.add_usage("model_a", 20, 10)

    breakdown = tracker.get_usage_breakdown("model_a")
    assert breakdown["input"] == 30
    assert breakdown["output"] == 15


def test_multiple_models():
    tracker = UsageTracker()
    tracker.add_usage("model_a", 10, 5)
    tracker.add_usage("model_b", 100, 50)

    bd_a = tracker.get_usage_breakdown("model_a")
    bd_b = tracker.get_usage_breakdown("model_b")

    assert bd_a["input"] == 10
    assert bd_a["output"] == 5
    assert bd_b["input"] == 100
    assert bd_b["output"] == 50


def test_missing_model_returns_zeros():
    tracker = UsageTracker()
    bd = tracker.get_usage_breakdown("non_existent")
    assert bd["input"] == 0
    assert bd["output"] == 0
