#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./scripts/refresh_cli_cassettes.sh [fake|real|all]

Behavior:
  fake: refresh fake recorded lane only
  real: refresh real-provider recorded lane only
  all:  refresh fake lane, then real-provider lane

Defaults:
  If ASKY_CLI_REAL_PROVIDER=1, default mode is "real".
  Otherwise, default mode is "fake".
EOF
}

mode="${1:-}"
if [[ "${mode}" == "--help" ]] || [[ "${mode}" == "-h" ]]; then
  usage
  exit 0
fi

if [[ -z "${mode}" ]]; then
  if [[ "${ASKY_CLI_REAL_PROVIDER:-0}" == "1" ]]; then
    mode="real"
  else
    mode="fake"
  fi
fi

if [[ "${mode}" != "fake" && "${mode}" != "real" && "${mode}" != "all" ]]; then
  echo "ERROR: invalid mode '${mode}'." >&2
  usage >&2
  exit 1
fi

echo "Refreshing pytest-recording CLI integration cassettes (mode=${mode})..."

export ASKY_CLI_RECORD=1
export ASKY_CLI_FIXED_TIME="${ASKY_CLI_FIXED_TIME:-2024-01-01T12:00:00+00:00}"
export ASKY_CLI_MODEL_ALIAS="${ASKY_CLI_MODEL_ALIAS:-gf}"

run_fake_lane() {
  echo "Running fake recorded refresh..."
  ASKY_CLI_REAL_PROVIDER=0 uv run pytest tests/integration/cli_recorded -q \
    -o addopts='-n0 --record-mode=once' \
    -m "recorded_cli and not real_recorded_cli"
}

run_real_lane() {
  if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
    echo "ERROR: OPENROUTER_API_KEY is required to refresh real-provider cassettes." >&2
    exit 1
  fi
  echo "Running real-provider recorded refresh..."
  ASKY_CLI_REAL_PROVIDER=1 uv run pytest tests/integration/cli_recorded -q \
    -o addopts='-n0 --record-mode=once' \
    -m "real_recorded_cli"
}

if [[ "${mode}" == "fake" ]]; then
  run_fake_lane
elif [[ "${mode}" == "real" ]]; then
  run_real_lane
else
  run_fake_lane
  run_real_lane
fi

echo "Done. Requested cassette refresh lane(s) completed."
