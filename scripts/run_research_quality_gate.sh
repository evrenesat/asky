#!/usr/bin/env bash

set -euo pipefail

base_ref="HEAD~1"
head_ref="HEAD"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --base requires a value." >&2
        exit 1
      fi
      base_ref="$2"
      shift 2
      ;;
    --head)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --head requires a value." >&2
        exit 1
      fi
      head_ref="$2"
      shift 2
      ;;
    --help|-h)
      cat <<'EOF'
Usage:
  ./scripts/run_research_quality_gate.sh [--base <git-ref>] [--head <git-ref>]

Runs mandatory research quality checks only when research-related paths changed.
This script enforces nothing unless called (for example from pre-push or CI).
Docs: docs/research_testing_strategy.md
EOF
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument '$1'." >&2
      exit 1
      ;;
  esac
done

mapfile -t changed_files < <(git diff --name-only "${base_ref}" "${head_ref}")
if [[ "${#changed_files[@]}" -eq 0 ]]; then
  echo "No changed files detected between ${base_ref}..${head_ref}; skipping gate."
  exit 0
fi

research_scope_pattern='^(src/asky/research/|src/asky/api/(client|preload|session|types)\.py|src/asky/cli/(chat|main|section_commands)\.py|tests/integration/cli_recorded/|tests/integration/cli_live/|tests/fixtures/research_corpus/|scripts/refresh_cli_cassettes\.sh|scripts/run_research_quality_gate\.sh|docs/research_mode\.md|docs/document_qa\.md|docs/testing_recorded_cli\.md|docs/research_testing_strategy\.md|ARCHITECTURE\.md|tests/AGENTS\.md|pyproject\.toml)$'

research_changed=0
for file_path in "${changed_files[@]}"; do
  if [[ "${file_path}" =~ ${research_scope_pattern} ]]; then
    research_changed=1
    break
  fi
done

if [[ "${research_changed}" -eq 0 ]]; then
  echo "No research-scoped changes detected; skipping research quality gate."
  exit 0
fi

echo "Research-scoped changes detected. Running mandatory quality checks..."
echo "1/3 fake recorded replay"
uv run pytest tests/integration/cli_recorded -q \
  -o addopts='-n0 --record-mode=none' \
  -m "recorded_cli and not real_recorded_cli"

echo "2/3 real recorded replay"
ASKY_CLI_REAL_PROVIDER=1 uv run pytest tests/integration/cli_recorded -q \
  -o addopts='-n0 --record-mode=none' \
  -m "real_recorded_cli"

echo "3/3 live research checks"
if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
  echo "ERROR: OPENROUTER_API_KEY is required for live research gate checks." >&2
  exit 1
fi
uv run pytest tests/integration/cli_live -q -o addopts='-n0 -m live_research'

echo "Research quality gate passed."
