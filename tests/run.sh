#!/usr/bin/env bash
# Run every test file; exit non-zero if any fails.
#   tests/run.sh                 all of them
#   tests/run.sh worker auth     only files whose name contains one of these
#   HUMINT_SKIP_NATIVE=1         leave out the native app's (tests/test_native_*),
#                                which CI runs on their own Python (3.12)
# On GitHub Actions each failing file is also an annotation carrying the end
# of its output, so the failure can be read from the run's summary.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2
failed=()
out="$(mktemp)"
trap 'rm -f "$out"' EXIT
for t in tests/test_*.py; do
    case "$t" in tests/test_native_*) [ -n "${HUMINT_SKIP_NATIVE:-}" ] && continue ;; esac
    if [ $# -gt 0 ]; then
        hit=0; for w in "$@"; do case "$t" in *"$w"*) hit=1;; esac; done
        [ $hit = 1 ] || continue
    fi
    echo "=== $t"
    if ! python3 "$t" 2>&1 | tee "$out"; then
        failed+=("$t")
        if [ -n "${GITHUB_ACTIONS:-}" ]; then
            # The annotation's text: the last lines, newlines as %0A.
            msg="$(grep -v '^PASS ' "$out" | tail -25 | sed 's/%/%25/g; s/\r//g' | awk 'BEGIN{ORS="%0A"} {print}')"
            echo "::error title=$t::$msg"
        fi
    fi
done
echo
if [ ${#failed[@]} -gt 0 ]; then
    echo "FAILED: ${failed[*]}"; exit 1
fi
echo "All test files passed."
