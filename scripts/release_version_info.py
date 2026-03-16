#!/usr/bin/env python3
"""Inspect package versions and emit release metadata for GitHub Actions."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_CURRENT_PATH = Path("pyproject.toml")
DEFAULT_TAG_PREFIX = "v"
GITHUB_OUTPUT_ENV_VAR = "GITHUB_OUTPUT"


@dataclass(frozen=True)
class ReleaseVersionInfo:
    """Version comparison result for release automation."""

    should_release: bool
    version: str
    previous_version: str | None
    tag: str

    def github_outputs(self) -> dict[str, str]:
        """Return GitHub Actions-friendly output strings."""
        return {
            "should_release": str(self.should_release).lower(),
            "version": self.version,
            "previous_version": self.previous_version or "",
            "tag": self.tag,
        }


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _extract_version(data: dict[str, Any], *, source: Path) -> str:
    project = data.get("project", {})
    if isinstance(project, dict):
        version = project.get("version")
        if isinstance(version, str) and version.strip():
            return version.strip()

    tool = data.get("tool", {})
    if isinstance(tool, dict):
        poetry = tool.get("poetry", {})
        if isinstance(poetry, dict):
            version = poetry.get("version")
            if isinstance(version, str) and version.strip():
                return version.strip()

    raise ValueError(
        f"Unable to find a package version in {source}. "
        "Expected [project].version or [tool.poetry].version."
    )


def load_version(path: Path) -> str:
    """Load the package version from a TOML file."""
    return _extract_version(_read_toml(path), source=path)


def build_release_version_info(
    *,
    current_path: Path,
    previous_path: Path | None,
    tag_prefix: str,
) -> ReleaseVersionInfo:
    """Compare current and previous versions and derive release outputs."""
    current_version = load_version(current_path)
    previous_version = load_version(previous_path) if previous_path else None
    should_release = previous_version is None or previous_version != current_version
    return ReleaseVersionInfo(
        should_release=should_release,
        version=current_version,
        previous_version=previous_version,
        tag=f"{tag_prefix}{current_version}",
    )


def _write_github_output(path: Path, info: ReleaseVersionInfo) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for key, value in info.github_outputs().items():
            handle.write(f"{key}={value}\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare package versions and emit release metadata.",
    )
    parser.add_argument(
        "--current",
        type=Path,
        default=DEFAULT_CURRENT_PATH,
        help="Path to the current project metadata file.",
    )
    parser.add_argument(
        "--previous",
        type=Path,
        help="Path to the previous project metadata file.",
    )
    parser.add_argument(
        "--tag-prefix",
        default=DEFAULT_TAG_PREFIX,
        help="Prefix to prepend to the version when building a tag name.",
    )
    parser.add_argument(
        "--github-output",
        type=Path,
        help="Optional explicit path for GitHub Actions outputs.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    output_path = args.github_output
    if output_path is None:
        github_output = os.environ.get(GITHUB_OUTPUT_ENV_VAR, "").strip()
        output_path = Path(github_output) if github_output else None

    info = build_release_version_info(
        current_path=args.current,
        previous_path=args.previous,
        tag_prefix=args.tag_prefix,
    )
    if output_path is not None:
        _write_github_output(output_path, info)

    json.dump(asdict(info), sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
