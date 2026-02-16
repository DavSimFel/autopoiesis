#!/usr/bin/env bash
# Autopoiesis test runner — local e2e harness + Harbor benchmarking.
#
# TRUST BOUNDARY: tasks.json setup/validate/teardown commands are executed
# via bash -c. Only run task files you trust (treat them like scripts).
#
# Usage:
#   ./benchmarks/run.sh                          Run all e2e tasks
#   ./benchmarks/run.sh basic_chat file_write    Run specific tasks
#   ./benchmarks/run.sh --harbor                 Run via Harbor + Terminal-Bench
#
# Environment:
#   AI_PROVIDER      — provider (default: anthropic)
#   HARNESS_TIMEOUT  — default per-task timeout in seconds (default: 120)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TASKS_FILE="$SCRIPT_DIR/tasks.json"

cd "$REPO_ROOT"

# ── Load .env if present ─────────────────────────────────────────────
if [ -f "$REPO_ROOT/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$REPO_ROOT/.env"
    set +a
fi

export AI_PROVIDER="${AI_PROVIDER:-anthropic}"
DEFAULT_TIMEOUT="${HARNESS_TIMEOUT:-120}"

# ── Helpers ──────────────────────────────────────────────────────────
red()  { printf '\033[0;31m%s\033[0m\n' "$*"; }
bold() { printf '\033[1m%s\033[0m\n' "$*"; }
log()  { echo -e "\033[1;34m>>>\033[0m $*"; }

check_provider_key() {
    if [ -z "${ANTHROPIC_API_KEY:-}" ] \
        && [ -z "${OPENAI_API_KEY:-}" ] \
        && [ -z "${OPENROUTER_API_KEY:-}" ]; then
        red "Error: No AI provider key set."
        echo "Export one of: ANTHROPIC_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY"
        exit 1
    fi
}

# ── Harbor mode ──────────────────────────────────────────────────────
run_harbor() {
    check_provider_key
    if ! docker info > /dev/null 2>&1; then red "Error: Docker is not running"; exit 1; fi
    if ! command -v harbor &> /dev/null; then red "Error: harbor not found. Install with: uv tool install harbor"; exit 1; fi

    bold "Running autopoiesis via Harbor + Terminal-Bench..."
    cd "$SCRIPT_DIR"
    if [ ! -d .venv ]; then uv venv; fi
    # shellcheck disable=SC1091
    source .venv/bin/activate
    uv pip install -e ".[dev]" --quiet

    harbor run \
        -d terminal-bench@2.0 \
        --agent-import-path autopoiesis_terminal_bench:AutopoiesisAgent \
        --jobs-dir "./results" \
        -n 2 \
        "$@"
}

# ── E2E harness ──────────────────────────────────────────────────────
# No set -e: individual task failures are caught and reported, not fatal.
set -uo pipefail

PASS=0 FAIL=0 SKIP=0 TOTAL=0
RESULTS=()

pass() { echo -e "\033[1;32m[PASS]\033[0m $1 (${2}s)"; ((PASS++)); RESULTS+=("PASS  $1  ${2}s"); }
fail() { echo -e "\033[1;31m[FAIL]\033[0m $1 (${2}s)"; ((FAIL++)); RESULTS+=("FAIL  $1  ${2}s"); }
skip() { echo -e "\033[1;33m[SKIP]\033[0m $1"; ((SKIP++)); RESULTS+=("SKIP  $1"); }

task_field() {
    local val
    val=$(jq -r ".[$1].$2 // empty" "$TASKS_FILE")
    echo "${val:-${3:-}}"
}

run_task() {
    local idx="$1"
    local id instruction timeout expect_fail setup teardown validate
    id=$(task_field "$idx" id)
    instruction=$(task_field "$idx" instruction)
    timeout=$(task_field "$idx" timeout "$DEFAULT_TIMEOUT")
    expect_fail=$(task_field "$idx" expect_failure "false")
    setup=$(task_field "$idx" setup "")
    teardown=$(task_field "$idx" teardown "")
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

    [[ -n "$setup" ]] && bash -c "$setup" 2>/dev/null || true

    log "Running: $id (timeout: ${timeout}s)"
    start=$(date +%s)

    local exit_code=0
    export OUTPUT_FILE="$output" RESULT_FILE="$output"
    python chat.py run --no-approval \
        --task "$instruction" \
        --output "$output" \
        --timeout "$timeout" 2>/dev/null || exit_code=$?

    end=$(date +%s); elapsed=$((end - start))

    local success=false
    if [[ "$expect_fail" == "true" ]]; then
        if [[ $exit_code -ne 0 ]]; then
            success=true
        elif [[ -f "$output" ]] && bash -c "$validate" 2>/dev/null; then
            success=true
        fi
    elif [[ -f "$output" && $exit_code -eq 0 ]]; then
        if [[ -z "$validate" ]]; then
            jq -r .success "$output" 2>/dev/null | grep -q 'true' && success=true
        else
            bash -c "$validate" 2>/dev/null && success=true
        fi
    fi

    [[ -n "$teardown" ]] && bash -c "$teardown" 2>/dev/null || true

    if [[ "$success" == "true" ]]; then
        pass "$id" "$elapsed"
    else
        fail "$id" "$elapsed"
        if [[ -f "$output" ]]; then
            echo "    Output: $(head -5 "$output")"
        else
            echo "    No output file (exit code: $exit_code)"
        fi
    fi
}

run_harness() {
    check_provider_key

    TMPDIR_HARNESS="$(mktemp -d "${TMPDIR:-/tmp}/harness.XXXXXX")"
    trap 'rm -rf "$TMPDIR_HARNESS"' EXIT

    FILTER=("$@")

    echo "═══════════════════════════════════════════════════════"
    echo "  Autopoiesis Test Harness"
    echo "  Provider: $AI_PROVIDER  |  Timeout: ${DEFAULT_TIMEOUT}s"
    echo "═══════════════════════════════════════════════════════"
    echo ""

    local count
    count=$(jq 'length' "$TASKS_FILE")
    for ((i=0; i<count; i++)); do run_task "$i"; done

    echo ""
    echo "═══════════════════════════════════════════════════════"
    echo "  RESULTS: $PASS passed, $FAIL failed, $SKIP skipped (of $TOTAL run)"
    echo "═══════════════════════════════════════════════════════"
    for r in "${RESULTS[@]}"; do echo "  $r"; done
    echo ""

    [[ $FAIL -eq 0 ]]
}

# ── Main ─────────────────────────────────────────────────────────────
case "${1:-}" in
    --harbor) shift; run_harbor "$@" ;;
    --help|-h) head -13 "$0" | tail -12 | sed 's/^# \?//' ;;
    *) run_harness "$@" ;;
esac
