#!/usr/bin/env bash
# Local test harness for autopoiesis via batch mode.
# Exercises core features end-to-end with real LLM calls.
#
# Usage:
#   ./benchmarks/harness/run.sh                    # run all tasks
#   ./benchmarks/harness/run.sh basic_chat file_write  # run specific tasks
#
# Environment:
#   AI_PROVIDER      — provider (default: anthropic)
#   HARNESS_TIMEOUT  — default per-task timeout in seconds (default: 120)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TASKS_FILE="$SCRIPT_DIR/tasks.json"

cd "$REPO_ROOT"

# Load .env if present
if [ -f "$REPO_ROOT/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$REPO_ROOT/.env"
    set +a
fi

export AI_PROVIDER="${AI_PROVIDER:-anthropic}"
DEFAULT_TIMEOUT="${HARNESS_TIMEOUT:-120}"

TMPDIR_HARNESS="$(mktemp -d "${TMPDIR:-/tmp}/harness.XXXXXX")"
trap 'rm -rf "$TMPDIR_HARNESS"' EXIT

PASS=0 FAIL=0 SKIP=0 TOTAL=0
RESULTS=()

# ── helpers ──────────────────────────────────────────────────────────

log()  { echo -e "\033[1;34m>>>\033[0m $*"; }
pass() { echo -e "\033[1;32m[PASS]\033[0m $1 (${2}s)"; ((PASS++)); RESULTS+=("PASS  $1  ${2}s"); }
fail() { echo -e "\033[1;31m[FAIL]\033[0m $1 (${2}s)"; ((FAIL++)); RESULTS+=("FAIL  $1  ${2}s"); }
skip() { echo -e "\033[1;33m[SKIP]\033[0m $1"; ((SKIP++)); RESULTS+=("SKIP  $1"); }

task_field() {
    # task_field <index> <field> [default]
    local val
    val=$(jq -r ".[$1].$2 // empty" "$TASKS_FILE")
    echo "${val:-${3:-}}"
}

task_count() { jq 'length' "$TASKS_FILE"; }

run_task() {
    local idx="$1"
    local id timeout expect_fail setup teardown instruction
    id=$(task_field "$idx" id)
    instruction=$(task_field "$idx" instruction)
    timeout=$(task_field "$idx" timeout "$DEFAULT_TIMEOUT")
    expect_fail=$(task_field "$idx" expect_failure "false")
    setup=$(task_field "$idx" setup "")
    teardown=$(task_field "$idx" teardown "")
    local validate
    validate=$(task_field "$idx" validate "")

    # Filter check
    if [[ ${#FILTER[@]} -gt 0 ]]; then
        local found=0
        for f in "${FILTER[@]}"; do [[ "$f" == "$id" ]] && found=1; done
        if [[ $found -eq 0 ]]; then skip "$id"; return; fi
    fi

    ((TOTAL++))
    local output="$TMPDIR_HARNESS/${id}.json"
    local start end elapsed

    # Setup
    if [[ -n "$setup" ]]; then
        eval "$setup" 2>/dev/null || true
    fi

    log "Running: $id (timeout: ${timeout}s)"
    start=$(date +%s)

    # Run batch mode
    local exit_code=0
    export OUTPUT_FILE="$output"
    export RESULT_FILE="$output"
    python chat.py run --no-approval \
        --task "$instruction" \
        --output "$output" \
        --timeout "$timeout" 2>/dev/null || exit_code=$?

    end=$(date +%s)
    elapsed=$((end - start))

    # Evaluate
    local success=false
    if [[ "$expect_fail" == "true" ]]; then
        # For expected failures: either non-zero exit or success=false in JSON
        if [[ $exit_code -ne 0 ]]; then
            success=true
        elif [[ -f "$output" ]]; then
            if eval "$validate" 2>/dev/null; then
                success=true
            fi
        fi
    else
        if [[ -f "$output" && $exit_code -eq 0 ]]; then
            if [[ -z "$validate" ]]; then
                # No validation — just check success field
                if jq -r .success "$output" 2>/dev/null | grep -q 'true'; then
                    success=true
                fi
            else
                if eval "$validate" 2>/dev/null; then
                    success=true
                fi
            fi
        fi
    fi

    # Teardown
    if [[ -n "$teardown" ]]; then
        eval "$teardown" 2>/dev/null || true
    fi

    if [[ "$success" == "true" ]]; then
        pass "$id" "$elapsed"
    else
        fail "$id" "$elapsed"
        # Show output on failure for debugging
        if [[ -f "$output" ]]; then
            echo "    Output: $(cat "$output" | head -5)"
        else
            echo "    No output file (exit code: $exit_code)"
        fi
    fi
}

# ── main ─────────────────────────────────────────────────────────────

FILTER=("${@}")

echo "═══════════════════════════════════════════════════════"
echo "  Autopoiesis Test Harness"
echo "  Provider: $AI_PROVIDER  |  Timeout: ${DEFAULT_TIMEOUT}s"
echo "  Tasks: $TASKS_FILE"
echo "═══════════════════════════════════════════════════════"
echo ""

count=$(task_count)
for ((i=0; i<count; i++)); do
    run_task "$i"
done

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  RESULTS: $PASS passed, $FAIL failed, $SKIP skipped (of $TOTAL run)"
echo "═══════════════════════════════════════════════════════"
for r in "${RESULTS[@]}"; do
    echo "  $r"
done
echo ""

[[ $FAIL -eq 0 ]]
