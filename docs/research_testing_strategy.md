# Research Testing Strategy

This document defines how research-specific testing is expected to be executed and enforced.

## Scope

Research quality protection uses three lanes:

1. Fake recorded replay (`recorded_cli and not real_recorded_cli`)
2. Real-provider recorded replay (`real_recorded_cli`)
3. Live research checks (`live_research`)

Coverage rule:

1. Real-provider recorded and live research assertions must use model-backed `-r <source> <question>` turns.
2. Deterministic `--query-corpus` / `corpus query` checks remain in the fake recorded lane.

## Important Clarification

`scripts/run_research_quality_gate.sh` is an **enforcement script**, not a background daemon.
It only runs when explicitly called.

That means:

1. Nothing is automatically enforced unless you wire this script into your local git hooks and/or CI.
2. Merge protection should be done in CI, not by expectation alone.

## Intended Enforcement Model

Use both:

1. Local developer hook for fast feedback before push.
2. CI required check to block merge when research quality checks fail.

## Local Usage

Manual run:

```bash
./scripts/run_research_quality_gate.sh --base HEAD~1 --head HEAD
```

Recommended local hook: `pre-push` (not `pre-commit`, because live lane is intentionally slow).

Example `.git/hooks/pre-push`:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Compare current branch against its upstream tracking branch when available.
upstream_ref="$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null || true)"
if [[ -z "${upstream_ref}" ]]; then
  # Fallback when no upstream exists yet.
  ./scripts/run_research_quality_gate.sh --base HEAD~1 --head HEAD
  exit 0
fi

merge_base="$(git merge-base HEAD "${upstream_ref}")"
./scripts/run_research_quality_gate.sh --base "${merge_base}" --head HEAD
```

## CI Usage (Merge Gate)

Run the same script in CI and mark the CI job as a required status check for protected branches.

GitHub Actions example job:

```yaml
jobs:
  research-quality-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: astral-sh/setup-uv@v5
      - name: Run research quality gate
        env:
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
        run: |
          BASE_SHA="${{ github.event.pull_request.base.sha }}"
          HEAD_SHA="${{ github.event.pull_request.head.sha }}"
          ./scripts/run_research_quality_gate.sh --base "${BASE_SHA}" --head "${HEAD_SHA}"
```

## Failure Semantics

`run_research_quality_gate.sh` exits non-zero when:

1. Research-scoped files changed and any required lane fails.
2. Live lane is required but `OPENROUTER_API_KEY` is missing.

It exits zero when:

1. No files changed in the provided diff range, or
2. Changed files are outside research-scoped paths, or
3. All required lanes pass.

Research-scoped paths include `pyproject.toml`, because marker registration and default pytest lane exclusions are part of the enforcement contract.

## Related Commands

1. Fake cassette refresh:
   - `./scripts/refresh_cli_cassettes.sh fake`
2. Real cassette refresh:
   - `ASKY_CLI_REAL_PROVIDER=1 ./scripts/refresh_cli_cassettes.sh real`
3. Real replay:
   - `ASKY_CLI_REAL_PROVIDER=1 uv run pytest tests/integration/cli_recorded -q -o addopts='-n0 --record-mode=none' -m real_recorded_cli`
