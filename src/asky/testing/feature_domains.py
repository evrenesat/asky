"""Shared feature-domain matching for pytest and local quality gates."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

PYPROJECT_FILE_NAME = "pyproject.toml"
DEFAULT_RUN_ALL_ENV_VAR = "ASKY_PYTEST_RUN_ALL_DOMAINS"
CHANGED_PATHS_OVERRIDE_ENV_VAR = "ASKY_PYTEST_CHANGED_PATHS"
GIT_DIFF_NAME_STATUS_ARGS = ("diff", "--name-status", "--find-renames", "--relative")
GIT_UNTRACKED_ARGS = ("ls-files", "--others", "--exclude-standard")


class FeatureDomainError(RuntimeError):
    """Base error for feature-domain loading and matching."""


class FeatureDomainGitError(FeatureDomainError):
    """Raised when git state cannot be determined."""


@dataclass(frozen=True)
class FeatureDomain:
    """Config for one feature-domain test group."""

    name: str
    activation_paths: tuple[str, ...]
    test_paths: tuple[str, ...]

    def matches_changed_path(self, relative_path: str) -> bool:
        return any(_path_matches_prefix(relative_path, prefix) for prefix in self.activation_paths)

    def matches_test_path(self, relative_path: str) -> bool:
        return any(_path_matches_prefix(relative_path, prefix) for prefix in self.test_paths)


@dataclass(frozen=True)
class FeatureDomainConfig:
    """Top-level feature-domain config loaded from pyproject."""

    repo_root: Path
    fallback: str
    run_all_env_var: str
    domains: tuple[FeatureDomain, ...]

    def get_domain(self, name: str) -> FeatureDomain | None:
        for domain in self.domains:
            if domain.name == name:
                return domain
        return None


def _normalize_prefix(value: str) -> str:
    cleaned = value.strip().replace("\\", "/").strip("/")
    if not cleaned:
        raise FeatureDomainError("Feature-domain path values must not be empty.")
    return cleaned


def _path_matches_prefix(relative_path: str, prefix: str) -> bool:
    normalized_path = relative_path.strip().replace("\\", "/").strip("/")
    normalized_prefix = _normalize_prefix(prefix)
    return normalized_path == normalized_prefix or normalized_path.startswith(
        f"{normalized_prefix}/"
    )


def discover_repo_root(start_path: Path | None = None) -> Path:
    """Locate the repository root by walking upward to pyproject.toml."""

    current = (start_path or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / PYPROJECT_FILE_NAME).exists():
            return candidate
    raise FeatureDomainError("Unable to locate repository root from current working directory.")


def load_feature_domain_config(repo_root: Path | None = None) -> FeatureDomainConfig:
    """Load feature-domain config from pyproject.toml."""

    resolved_root = discover_repo_root(repo_root)
    pyproject_path = resolved_root / PYPROJECT_FILE_NAME
    with pyproject_path.open("rb") as handle:
        data = tomllib.load(handle)

    raw_config = (
        data.get("tool", {})
        .get("asky", {})
        .get("pytest_feature_domains", {})
    )
    fallback = str(raw_config.get("fallback", "run_all")).strip().lower()
    if fallback != "run_all":
        raise FeatureDomainError(
            f"Unsupported feature-domain fallback policy: {fallback!r}."
        )

    run_all_env_var = str(
        raw_config.get("run_all_env_var", DEFAULT_RUN_ALL_ENV_VAR)
    ).strip() or DEFAULT_RUN_ALL_ENV_VAR
    raw_domains = raw_config.get("domains", {})
    if not isinstance(raw_domains, dict):
        raise FeatureDomainError("Feature-domain config requires a [domains] table.")

    domains: list[FeatureDomain] = []
    for name, raw_domain in raw_domains.items():
        if not isinstance(raw_domain, dict):
            raise FeatureDomainError(f"Feature-domain {name!r} must be a table.")
        activation_paths = tuple(
            _normalize_prefix(value) for value in raw_domain.get("activation_paths", [])
        )
        test_paths = tuple(
            _normalize_prefix(value) for value in raw_domain.get("test_paths", [])
        )
        if not activation_paths:
            raise FeatureDomainError(
                f"Feature-domain {name!r} requires at least one activation path."
            )
        if not test_paths:
            raise FeatureDomainError(
                f"Feature-domain {name!r} requires at least one test path."
            )
        domains.append(
            FeatureDomain(
                name=str(name).strip(),
                activation_paths=activation_paths,
                test_paths=test_paths,
            )
        )

    return FeatureDomainConfig(
        repo_root=resolved_root,
        fallback=fallback,
        run_all_env_var=run_all_env_var,
        domains=tuple(domains),
    )


def _run_git_command(repo_root: Path, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    command = ["git", *args]
    completed = subprocess.run(
        command,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip() or "git command failed"
        raise FeatureDomainGitError(stderr)
    return completed


def _parse_name_status_output(output: str) -> set[str]:
    paths: set[str] = set()
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0].strip().upper()
        if status.startswith("R") or status.startswith("C"):
            path_parts = parts[1:3]
        else:
            path_parts = parts[1:2]
        for path_part in path_parts:
            normalized = path_part.strip().replace("\\", "/").strip("/")
            if normalized:
                paths.add(normalized)
    return paths


def _parse_simple_path_output(output: str) -> set[str]:
    return {
        line.strip().replace("\\", "/").strip("/")
        for line in output.splitlines()
        if line.strip()
    }


def get_worktree_changed_paths(repo_root: Path | None = None) -> list[str]:
    """Collect staged, unstaged, and untracked paths from the current worktree."""

    override = os.environ.get(CHANGED_PATHS_OVERRIDE_ENV_VAR, "")
    if override.strip():
        separators = (os.pathsep, "\n")
        normalized = override
        for separator in separators:
            normalized = normalized.replace(separator, "\n")
        return sorted(_parse_simple_path_output(normalized))

    resolved_root = discover_repo_root(repo_root)
    changed_paths: set[str] = set()
    unstaged = _run_git_command(resolved_root, [*GIT_DIFF_NAME_STATUS_ARGS])
    staged = _run_git_command(resolved_root, [*GIT_DIFF_NAME_STATUS_ARGS, "--cached"])
    untracked = _run_git_command(resolved_root, [*GIT_UNTRACKED_ARGS])
    changed_paths.update(_parse_name_status_output(unstaged.stdout))
    changed_paths.update(_parse_name_status_output(staged.stdout))
    changed_paths.update(_parse_simple_path_output(untracked.stdout))
    return sorted(changed_paths)


def get_ref_range_changed_paths(
    base_ref: str,
    head_ref: str,
    repo_root: Path | None = None,
) -> list[str]:
    """Collect changed paths between two refs."""

    resolved_root = discover_repo_root(repo_root)
    completed = _run_git_command(
        resolved_root,
        [*GIT_DIFF_NAME_STATUS_ARGS, base_ref, head_ref],
    )
    return sorted(_parse_name_status_output(completed.stdout))


def get_active_domains(
    config: FeatureDomainConfig,
    changed_paths: Sequence[str],
) -> set[str]:
    """Return the domain names touched by the provided changed paths."""

    changed_set = {
        path.strip().replace("\\", "/").strip("/")
        for path in changed_paths
        if path.strip()
    }
    return {
        domain.name
        for domain in config.domains
        if any(domain.matches_changed_path(path) for path in changed_set)
    }


def get_domains_for_test_path(
    relative_path: str,
    config: FeatureDomainConfig,
) -> set[str]:
    """Infer domain names from a test path."""

    normalized = relative_path.strip().replace("\\", "/").strip("/")
    return {
        domain.name for domain in config.domains if domain.matches_test_path(normalized)
    }


def normalize_relative_path(path_value: str | Path, repo_root: Path) -> str | None:
    """Normalize a path or node path to a repo-relative POSIX string."""

    raw_value = str(path_value).strip()
    if not raw_value:
        return None
    node_path = raw_value.split("::", 1)[0].strip()
    candidate = Path(node_path)
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(repo_root).as_posix()
        except ValueError:
            return None

    normalized = node_path.replace("\\", "/").strip("/")
    if not normalized or normalized.startswith("-"):
        return None
    return normalized


def get_explicitly_requested_domains(
    args: Sequence[str],
    config: FeatureDomainConfig,
) -> set[str]:
    """Detect domains that were explicitly targeted on the pytest command line."""

    requested: set[str] = set()
    for arg in args:
        normalized = normalize_relative_path(arg, config.repo_root)
        if not normalized:
            continue
        requested.update(get_domains_for_test_path(normalized, config))
    return requested


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect asky feature-domain activation.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    ref_range = subparsers.add_parser(
        "domain-active",
        help="Exit 0 when a feature domain is active for the given ref range, else 1.",
    )
    ref_range.add_argument("--domain", required=True)
    ref_range.add_argument("--base", required=True)
    ref_range.add_argument("--head", required=True)
    ref_range.add_argument("--repo-root", default=".")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for shell scripts that need shared domain checks."""

    parser = _build_cli_parser()
    args = parser.parse_args(argv)
    config = load_feature_domain_config(Path(args.repo_root))
    domain = config.get_domain(args.domain)
    if domain is None:
        parser.error(f"Unknown feature domain: {args.domain!r}")
    changed_paths = get_ref_range_changed_paths(
        base_ref=args.base,
        head_ref=args.head,
        repo_root=config.repo_root,
    )
    active = args.domain in get_active_domains(config, changed_paths)
    return 0 if active else 1


if __name__ == "__main__":
    sys.exit(main())

