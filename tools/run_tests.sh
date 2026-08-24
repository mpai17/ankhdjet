#!/usr/bin/env bash
# Run the entire Ankhdjet regression suite and write a timestamped log.
# Per-test full stdout is always captured (gzipped) for later debugging.
#
# Logs land in build/logs/<UTC-timestamp>/ :
#   summary.log              one-line pass/fail per test (also tee'd to console)
#   <test_name>.stdout.gz    full captured stdout per test
#
# Exit code is 0 only if every test passes and reports no FAIL/MISMATCH.

set -u
cd "$(dirname "$0")/.."

# Tier: --fast runs only the quick tests/test_*.py (Verilator + PyTorch
# bridge); the default (full) also runs the heavy component SPICE suites.
MODE="full"
[ "${1:-}" = "--fast" ] && MODE="fast"

# All invocations go through uv with the project pinned, so per-suite
# `cd` does not change which environment runs.
REPO="$(pwd)"
PY="uv run --project $REPO python"
ts=$(date -u +%Y%m%dT%H%M%SZ)
log_dir="build/logs/$ts"
mkdir -p "$log_dir"
summary="$log_dir/summary.log"

# Header
{
    echo "Ankhdjet regression run (${MODE} tier)"
    echo "  timestamp (UTC): $ts"
    echo "  commit         : $(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
    echo "  host           : $(hostname)"
    echo "  python         : $($PY --version 2>&1)"
    echo
    printf '%-45s %s\n' "test" "result"
    echo "------------------------------------------------------------------"
} | tee "$summary"

exit_code=0

for t in tests/test_*.py; do
    name=$(basename "$t" .py)
    out_file="$log_dir/${name}.stdout"
    out=$($PY "$t" 2>&1)
    rc=$?
    printf "%s\n" "$out" > "$out_file"

    if [ $rc -ne 0 ]; then
        result="FAIL (rc=$rc)"
        exit_code=1
    elif echo "$out" | grep -qE "FAIL|MISMATCH|Traceback"; then
        result="FAIL (mismatch in output)"
        exit_code=1
    else
        last=$(echo "$out" | grep -E "^\[ok\]|^All cases|^Round-trip|^Verilator" | tail -1)
        result="ok  ${last:0:100}"
    fi
    printf '%-45s %s\n' "${name}.py" "$result" | tee -a "$summary"

    gzip -f "$out_file"
done

# Heavy component SPICE suites -- full tier only (--fast skips these). Each
# suite's own runners already write a timestamped summary log to their
# build_*/ dir; here we record only the pytest pass/fail headline.
if [ "$MODE" = "full" ]; then
    PYTEST_SUITES=(
        "cell/sky130/bitcell_v4/sim"
        "cell/sky130/precharge/sim"
        "cell/sky130/strongarm/sim"
        "macro/sky130/sim"
    )
    for suite in "${PYTEST_SUITES[@]}"; do
        out=$(cd "$suite" && $PY -m pytest -q 2>&1)
        rc=$?
        if [ $rc -ne 0 ]; then
            result="FAIL (rc=$rc)"
            exit_code=1
        else
            summary_ln=$(echo "$out" | grep -E "passed|failed|error" | tail -1)
            result="ok  ${summary_ln:0:100}"
        fi
        printf '%-45s %s\n' "$suite" "$result" | tee -a "$summary"
    done
fi

{
    echo
    if [ $exit_code -eq 0 ]; then
        echo "All tests passed."
    else
        echo "FAILURES detected. Inspect ${log_dir}/<test>.stdout.gz for details."
    fi
    echo "Log: $summary"
} | tee -a "$summary"

exit $exit_code
