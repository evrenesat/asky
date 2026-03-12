"""Tests for feature-domain matching and pytest deselection."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from asky.testing.feature_domains import (
    CHANGED_PATHS_OVERRIDE_ENV_VAR,
    get_active_domains,
    get_explicitly_requested_domains,
    get_ref_range_changed_paths,
    get_worktree_changed_paths,
    load_feature_domain_config,
)

pytest_plugins = ("pytester",)


def _write_pytester_tree(pytester: pytest.Pytester) -> None:
    research_path = pytester.path / "tests" / "research" / "test_research.py"
    regular_path = pytester.path / "tests" / "unit" / "test_regular.py"
    research_path.parent.mkdir(parents=True, exist_ok=True)
    regular_path.parent.mkdir(parents=True, exist_ok=True)
    research_path.write_text("def test_research():\n    assert True\n", encoding="utf-8")
    regular_path.write_text("def test_regular():\n    assert True\n", encoding="utf-8")


def test_get_worktree_changed_paths_prefers_override_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        CHANGED_PATHS_OVERRIDE_ENV_VAR,
        "src/asky/research/vector_store.py\npyproject.toml",
    )

    changed_paths = get_worktree_changed_paths()

    assert changed_paths == ["pyproject.toml", "src/asky/research/vector_store.py"]


def test_get_ref_range_changed_paths_parses_rename_and_modify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args, **kwargs) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        return subprocess.CompletedProcess(
            args=["git"],
            returncode=0,
            stdout=(
                "M\tsrc/asky/research/vector_store.py\n"
                "R100\tsrc/asky/research/old.py\tsrc/asky/research/new.py\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    changed_paths = get_ref_range_changed_paths("A", "B", repo_root=Path.cwd())

    assert changed_paths == [
        "src/asky/research/new.py",
        "src/asky/research/old.py",
        "src/asky/research/vector_store.py",
    ]


def test_get_active_domains_matches_research_scope() -> None:
    config = load_feature_domain_config()

    active_domains = get_active_domains(
        config,
        ["src/asky/research/vector_store.py", "README.md"],
    )

    assert active_domains == {"research"}


def test_get_explicitly_requested_domains_matches_test_path() -> None:
    config = load_feature_domain_config()

    explicit_domains = get_explicitly_requested_domains(
        ["tests/integration/cli_live/test_cli_research_live.py::test_live_model_healthcheck"],
        config,
    )

    assert explicit_domains == {"research"}


def test_pytest_plugin_deselects_inactive_domain_tests(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ASKY_PYTEST_RUN_ALL_DOMAINS", raising=False)
    pytester.makepyprojecttoml(
        """
        [tool.pytest.ini_options]
        markers = ["feature_domain(name): Assign a test module or item to a feature domain"]

        [tool.asky.pytest_feature_domains]
        fallback = "run_all"
        run_all_env_var = "ASKY_PYTEST_RUN_ALL_DOMAINS"

        [tool.asky.pytest_feature_domains.domains.research]
        activation_paths = ["src/asky/research"]
        test_paths = ["tests/research"]
        """
    )
    pytester.makeconftest(
        'pytest_plugins = ("asky.testing.pytest_feature_domains",)\n'
    )
    _write_pytester_tree(pytester)
    monkeypatch.setenv(CHANGED_PATHS_OVERRIDE_ENV_VAR, "src/asky/core/engine.py")

    result = pytester.runpytest("-q")

    result.assert_outcomes(passed=1, deselected=1)
    result.stdout.fnmatch_lines(
        ["*feature domains: deselected 1 tests for inactive domains (research)*"]
    )


def test_pytest_plugin_keeps_active_domain_tests(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ASKY_PYTEST_RUN_ALL_DOMAINS", raising=False)
    pytester.makepyprojecttoml(
        """
        [tool.pytest.ini_options]
        markers = ["feature_domain(name): Assign a test module or item to a feature domain"]

        [tool.asky.pytest_feature_domains]
        fallback = "run_all"
        run_all_env_var = "ASKY_PYTEST_RUN_ALL_DOMAINS"

        [tool.asky.pytest_feature_domains.domains.research]
        activation_paths = ["src/asky/research"]
        test_paths = ["tests/research"]
        """
    )
    pytester.makeconftest(
        'pytest_plugins = ("asky.testing.pytest_feature_domains",)\n'
    )
    _write_pytester_tree(pytester)
    monkeypatch.setenv(CHANGED_PATHS_OVERRIDE_ENV_VAR, "src/asky/research/cache.py")

    result = pytester.runpytest("-q")

    result.assert_outcomes(passed=2)


def test_pytest_plugin_respects_explicit_test_target(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ASKY_PYTEST_RUN_ALL_DOMAINS", raising=False)
    pytester.makepyprojecttoml(
        """
        [tool.pytest.ini_options]
        markers = ["feature_domain(name): Assign a test module or item to a feature domain"]

        [tool.asky.pytest_feature_domains]
        fallback = "run_all"
        run_all_env_var = "ASKY_PYTEST_RUN_ALL_DOMAINS"

        [tool.asky.pytest_feature_domains.domains.research]
        activation_paths = ["src/asky/research"]
        test_paths = ["tests/research"]
        """
    )
    pytester.makeconftest(
        'pytest_plugins = ("asky.testing.pytest_feature_domains",)\n'
    )
    test_path = pytester.path / "tests" / "research" / "test_research.py"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text("def test_research():\n    assert True\n", encoding="utf-8")
    monkeypatch.setenv(CHANGED_PATHS_OVERRIDE_ENV_VAR, "src/asky/core/engine.py")

    result = pytester.runpytest("-q", str(test_path))

    result.assert_outcomes(passed=1)
