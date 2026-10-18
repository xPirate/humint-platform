#!/usr/bin/env bash
# Run every test file; exit non-zero if any fails.
#   tests/run.sh                 all of them
#   tests/run.sh worker auth     only files whose name contains one of these
set -uo pipefail
cd "$(dirname "$0")/.."
failed=()
for t in tests/test_*.py; do
    if [ $# -gt 0 ]; then
        hit=0; for w in "$@"; do case "$t" in *"$w"*) hit=1;; esac; done
        [ $hit = 1 ] || continue
    fi
    echo "=== $t"
    python3 "$t" || failed+=("$t")
done
echo
if [ ${#failed[@]} -gt 0 ]; then
    echo "FAILED: ${failed[*]}"; exit 1
fi
echo "All test files passed."
