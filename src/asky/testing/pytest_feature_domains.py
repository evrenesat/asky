"""Pytest plugin that deselects inactive feature-domain tests."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from asky.testing.feature_domains import (
    FeatureDomainGitError,
    FeatureDomainConfig,
    get_active_domains,
    get_domains_for_test_path,
    get_explicitly_requested_domains,
    load_feature_domain_config,
    get_worktree_changed_paths,
    normalize_relative_path,
)

STATE_ATTR = "_asky_feature_domain_state"
FEATURE_DOMAIN_MARKER = "feature_domain"


@dataclass
class FeatureDomainState:
    """Resolved session state for the feature-domain plugin."""

    enabled: bool
    reason: str
    run_all_env_var: str
    active_domains: set[str]
    explicit_domains: set[str]
    changed_paths: tuple[str, ...]
    deselected_count: int = 0


def _is_worker(config: pytest.Config) -> bool:
    return hasattr(config, "workerinput")


def _build_state(config: pytest.Config) -> FeatureDomainState:
    feature_config = load_feature_domain_config(Path(str(config.rootpath)))
    if os.environ.get(feature_config.run_all_env_var):
        return FeatureDomainState(
            enabled=False,
            reason=f"disabled by {feature_config.run_all_env_var}",
            run_all_env_var=feature_config.run_all_env_var,
            active_domains=set(),
            explicit_domains=set(),
            changed_paths=(),
        )

    explicit_domains = get_explicitly_requested_domains(
        config.invocation_params.args,
        feature_config,
    )

    try:
        changed_paths = tuple(get_worktree_changed_paths(feature_config.repo_root))
    except FeatureDomainGitError as exc:
        return FeatureDomainState(
            enabled=False,
            reason=f"git state unavailable, running all tests ({exc})",
            run_all_env_var=feature_config.run_all_env_var,
            active_domains=set(),
            explicit_domains=explicit_domains,
            changed_paths=(),
        )

    active_domains = get_active_domains(feature_config, changed_paths)
    active_domains.update(explicit_domains)
    return FeatureDomainState(
        enabled=True,
        reason="feature-domain deselection active",
        run_all_env_var=feature_config.run_all_env_var,
        active_domains=active_domains,
        explicit_domains=explicit_domains,
        changed_paths=changed_paths,
    )


def _get_state(config: pytest.Config) -> FeatureDomainState:
    state = getattr(config, STATE_ATTR, None)
    if state is None:
        state = _build_state(config)
        setattr(config, STATE_ATTR, state)
    return state


def _feature_config(config: pytest.Config) -> FeatureDomainConfig:
    return load_feature_domain_config(Path(str(config.rootpath)))


def _iter_item_domains(item: pytest.Item, feature_config: FeatureDomainConfig) -> set[str]:
    item_path = normalize_relative_path(str(item.path), feature_config.repo_root)
    inferred_domains = (
        get_domains_for_test_path(item_path, feature_config) if item_path else set()
    )
    for marker in item.iter_markers(name=FEATURE_DOMAIN_MARKER):
        if marker.args:
            inferred_domains.add(str(marker.args[0]).strip())
    return {
        domain for domain in inferred_domains if feature_config.get_domain(domain) is not None
    }


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "feature_domain(name): assign a test module or test item to a feature domain.",
    )
    _get_state(config)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    state = _get_state(config)
    if not state.enabled:
        return

    feature_config = _feature_config(config)
    kept: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    for item in items:
        item_domains = _iter_item_domains(item, feature_config)
        if item_domains and item_domains.isdisjoint(state.active_domains):
            deselected.append(item)
            continue
        kept.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = kept
        state.deselected_count += len(deselected)


def pytest_report_header(config: pytest.Config) -> str | None:
    if _is_worker(config):
        return None
    state = _get_state(config)
    active_domains = ", ".join(sorted(state.active_domains)) or "none"
    changed_count = len(state.changed_paths)
    return (
        "feature domains: "
        f"{state.reason}; active={active_domains}; "
        f"changed_paths={changed_count}; "
        f"override={state.run_all_env_var}=1"
    )


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter,
    exitstatus: int,
    config: pytest.Config,
) -> None:
    del exitstatus
    if _is_worker(config):
        return
    state = _get_state(config)
    if not state.enabled or state.deselected_count == 0:
        return
    inactive = sorted(
        domain.name
        for domain in _feature_config(config).domains
        if domain.name not in state.active_domains
    )
    terminalreporter.write_line(
        "feature domains: "
        f"deselected {state.deselected_count} tests for inactive domains "
        f"({', '.join(inactive)})"
    )
