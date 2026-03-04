#!/usr/bin/env bash

set -e

echo "Refreshing pytest-recording CLI integration cassettes..."

# Explicitly set the environment guard required to write cassettes
export ASKY_CLI_RECORD=1

# Use a deterministic time if needed (already set in conftest, but can override here)
export ASKY_CLI_FIXED_TIME="2024-01-01T12:00:00+00:00"

# Use the canonical model alias
export ASKY_CLI_MODEL_ALIAS="gf"

if [[ "${ASKY_CLI_REAL_PROVIDER:-0}" == "1" ]] && [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
  echo "ERROR: OPENROUTER_API_KEY is required when ASKY_CLI_REAL_PROVIDER=1." >&2
  exit 1
fi

# Run only recorded in-process lane and bypass default marker deselection in pyproject addopts
uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=once' -m "recorded_cli"

echo "Done! Cassettes have been updated."
