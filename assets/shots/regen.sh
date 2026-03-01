#!/usr/bin/env bash
# Regenerate GIFs from VHS tape files.
#
# Usage:
#   ./assets/shots/regen.sh                          # regenerate all GIFs
#   ./assets/shots/regen.sh quickstart-first-query   # regenerate one
#   ./assets/shots/regen.sh elephant-remember elephant-recall  # regenerate several
#
# Must be run from the project root so that Output paths resolve correctly.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

ALL_TAPES=(
    quickstart-first-run
    quickstart-no-model
    quickstart-model-add
    quickstart-first-query
    quickstart-web-search
    elephant-remember
    elephant-recall
    document-qa-read
    document-qa-sections
    daemon-start
)

cd "$PROJECT_ROOT"

if [ $# -eq 0 ]; then
    targets=("${ALL_TAPES[@]}")
else
    targets=("$@")
fi

failed=()
for name in "${targets[@]}"; do
    tape="assets/shots/${name}.tape"
    if [ ! -f "$tape" ]; then
        echo "ERROR: tape not found: $tape"
        failed+=("$name")
        continue
    fi
    echo "→ $name"
    if vhs "$tape"; then
        echo "  ✓ assets/shots/${name}.gif"
    else
        echo "  ✗ failed"
        failed+=("$name")
    fi
done

if [ ${#failed[@]} -gt 0 ]; then
    echo ""
    echo "Failed: ${failed[*]}"
    exit 1
fi
