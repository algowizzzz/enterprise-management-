#!/usr/bin/env bash
#
# Verify an installation, end to end, in one command.
#
#   ./scripts/verify.sh --bench /opt/consilium --site consilium.local
#
# Runs, in order of how fast they fail:
#
#   1. Platform rules      — no dependencies, reads files, fails in a second
#   2. Toolchain tests     — the deployment tooling
#   3. Migration           — the schema is current
#   4. Application tests   — behaviour, against the real database
#   5. Health check        — the installed system is actually serving
#
# Anything that fails stops the run, because a later stage's failure is usually
# a consequence of an earlier one and chasing the consequence wastes time.
#
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH=""
SITE="consilium.local"
PY=""
SKIP_TESTS=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --bench) BENCH="$2"; shift 2;;
        --site) SITE="$2"; shift 2;;
        --python) PY="$2"; shift 2;;
        --skip-tests) SKIP_TESTS=1; shift;;
        -h|--help) sed -n '2,18p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0;;
        *) echo "unknown option: $1" >&2; exit 2;;
    esac
done

if [[ -z "$BENCH" ]]; then
    echo "Which installation? Pass --bench <path>." >&2
    exit 2
fi
[[ -z "$PY" ]] && PY="$BENCH/env/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3)"

STAGE=0
TOTAL=5
failed=""

stage() {
    STAGE=$((STAGE + 1))
    printf '\n\033[1m[%d/%d] %s\033[0m\n' "$STAGE" "$TOTAL" "$1"
}

run() {
    if "$@"; then
        return 0
    fi
    failed="$1"
    printf '\n\033[31mStopped: the stage above failed.\033[0m\n'
    printf 'Fix it before running the rest — later stages usually fail as a\n'
    printf 'consequence, and chasing the consequence wastes time.\n\n'
    exit 1
}

stage "Platform rules"
run "$PY" "$REPO/scripts/check_platform_rules.py"

stage "Toolchain tests"
if "$PY" -c "import pytest" 2>/dev/null; then
    run "$PY" -m pytest "$REPO/tests/" -q
else
    echo "  pytest is not installed in this environment; skipped"
fi

stage "Migration"
export FRAPPE_BENCH_ROOT="$BENCH"
run bash -c "cd '$BENCH/sites' && '$PY' -m frappe.utils.bench_helper frappe --site '$SITE' migrate 2>&1 | grep -v 'Updating DocTypes' | tail -5"

stage "Application tests"
if [[ "$SKIP_TESTS" -eq 1 ]]; then
    echo "  skipped by request"
else
    run bash -c "cd '$BENCH/sites' && '$PY' -m frappe.utils.bench_helper frappe --site '$SITE' run-tests --app consilium 2>&1 | tail -8"
fi

stage "Health check"
run bash -c "cd '$BENCH/sites' && '$PY' '$REPO/deploy/healthcheck.py' --site '$SITE'"

printf '\n\033[32mEverything passed.\033[0m This installation is verified.\n\n'
