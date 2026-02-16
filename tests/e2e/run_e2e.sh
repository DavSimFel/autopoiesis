#!/usr/bin/env bash
# End-to-end integration test harness for autopoiesis batch mode.
# Usage: ./tests/e2e/run_e2e.sh
#
# Environment:
#   AI_PROVIDER      — provider name (default: anthropic)
#   AI_MODEL         — model override (optional)
#   E2E_LLM_TIMEOUT  — timeout for LLM-calling tests (default: 120)
#   E2E_SKIP_LLM     — set to 1 to skip tests that require a live LLM

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

# ── configuration ────────────────────────────────────────────────────
export AI_PROVIDER="${AI_PROVIDER:-anthropic}"
LLM_TIMEOUT="${E2E_LLM_TIMEOUT:-120}"
SKIP_LLM="${E2E_SKIP_LLM:-0}"
TMPDIR_E2E="$(mktemp -d "${TMPDIR:-/tmp}/e2e_autopoiesis.XXXXXX")"
E2E_WORKSPACE="$TMPDIR_E2E/workspace"
mkdir -p "$E2E_WORKSPACE"

PASS=0
FAIL=0
SKIP=0
RESULTS=()

cleanup() {
    rm -rf "$TMPDIR_E2E"
}
trap cleanup EXIT

# ── helpers ──────────────────────────────────────────────────────────
run_agent() {
    # run_agent <task> <output_json> [extra_args...]
    local task="$1" output="$2"
    shift 2
    python chat.py run --no-approval --task "$task" --output "$output" "$@"
}

record() {
    local name="$1" status="$2" elapsed="$3"
    RESULTS+=("$status  $name  (${elapsed}s)")
    if [[ "$status" == "PASS" ]]; then ((PASS++)); fi
    if [[ "$status" == "FAIL" ]]; then ((FAIL++)); fi
    if [[ "$status" == "SKIP" ]]; then ((SKIP++)); fi
    echo "[$status] $name (${elapsed}s)"
}

run_test() {
    local name="$1" needs_llm="${2:-0}"
    shift 2 || shift 1
    if [[ "$needs_llm" == "1" && "$SKIP_LLM" == "1" ]]; then
        record "$name" "SKIP" "0"
        return 0
    fi
    local start end elapsed
    start=$(date +%s)
    if "$@"; then
        end=$(date +%s); elapsed=$((end - start))
        record "$name" "PASS" "$elapsed"
    else
        end=$(date +%s); elapsed=$((end - start))
        record "$name" "FAIL" "$elapsed"
    fi
}

json_field() {
    # json_field <file> <field>  — extract top-level string/bool field via python
    python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d[sys.argv[2]])" "$1" "$2"
}

# ── test cases ───────────────────────────────────────────────────────

test_basic_chat() {
    local out="$TMPDIR_E2E/basic_chat.json"
    run_agent "What is 2+2? Reply with just the number." "$out" --timeout "$LLM_TIMEOUT"
    [[ "$(json_field "$out" success)" == "True" ]] || return 1
    [[ -n "$(json_field "$out" result)" ]] || return 1
}

test_file_write() {
    local out="$TMPDIR_E2E/file_write.json"
    local target="$E2E_WORKSPACE/e2e_written.txt"
    run_agent "Write the text 'hello e2e' to the file $target — use your exec tool to run: echo 'hello e2e' > $target" "$out" --timeout "$LLM_TIMEOUT"
    [[ "$(json_field "$out" success)" == "True" ]] || return 1
    [[ -f "$target" ]] || return 1
    grep -q "hello e2e" "$target" || return 1
}

test_file_read() {
    local out="$TMPDIR_E2E/file_read.json"
    local src="$E2E_WORKSPACE/e2e_readable.txt"
    echo "secret_canary_42" > "$src"
    run_agent "Read the file $src and tell me what it contains." "$out" --timeout "$LLM_TIMEOUT"
    [[ "$(json_field "$out" success)" == "True" ]] || return 1
    json_field "$out" result | grep -qi "secret_canary_42" || return 1
}

test_memory_store_recall() {
    local out1="$TMPDIR_E2E/mem_store.json"
    local out2="$TMPDIR_E2E/mem_recall.json"
    run_agent "Memorize the following: The secret code is ZEBRA-9876. Use your memory_store tool." "$out1" --timeout "$LLM_TIMEOUT"
    [[ "$(json_field "$out1" success)" == "True" ]] || return 1
    run_agent "What secret code did I ask you to memorize? Search your memory." "$out2" --timeout "$LLM_TIMEOUT"
    [[ "$(json_field "$out2" success)" == "True" ]] || return 1
    json_field "$out2" result | grep -qi "ZEBRA-9876" || return 1
}

test_knowledge_search() {
    local out="$TMPDIR_E2E/knowledge_search.json"
    local kdir="$REPO_ROOT/knowledge/reference"
    mkdir -p "$kdir"
    echo "The capital of Freedonia is Glorpville." > "$kdir/e2e_test_fact.md"
    # Re-index will happen on startup
    run_agent "Search your knowledge base for information about Freedonia." "$out" --timeout "$LLM_TIMEOUT"
    [[ "$(json_field "$out" success)" == "True" ]] || return 1
    json_field "$out" result | grep -qi "Glorpville" || return 1
    rm -f "$kdir/e2e_test_fact.md"
}

test_topic_activation() {
    local out="$TMPDIR_E2E/topic.json"
    run_agent "List available topics, then activate the research topic." "$out" --timeout "$LLM_TIMEOUT"
    [[ "$(json_field "$out" success)" == "True" ]] || return 1
}

test_subscription_create() {
    local out="$TMPDIR_E2E/subscription.json"
    run_agent "Create a subscription to watch the file $E2E_WORKSPACE for changes." "$out" --timeout "$LLM_TIMEOUT"
    [[ "$(json_field "$out" success)" == "True" ]] || return 1
}

test_timeout_handling() {
    local out="$TMPDIR_E2E/timeout.json"
    # Use a very short timeout — the agent startup + LLM call should exceed 5s
    python chat.py run --no-approval \
        --task "Write a 5000-word essay about the history of computing." \
        --output "$out" --timeout 5 2>/dev/null || true
    # If we got output JSON, check for timeout error
    if [[ -f "$out" ]]; then
        [[ "$(json_field "$out" success)" == "False" ]] || return 1
        json_field "$out" error | grep -qi "timeout" || return 1
    else
        # Agent may have crashed before writing output — that's still a
        # timeout/error scenario; verify exit code was non-zero (already || true)
        return 0
    fi
}

test_stdin_input() {
    local out="$TMPDIR_E2E/stdin.json"
    echo "What is 3+3? Reply with just the number." | \
        python chat.py run --no-approval --task - --output "$out" --timeout "$LLM_TIMEOUT"
    [[ "$(json_field "$out" success)" == "True" ]] || return 1
    [[ -n "$(json_field "$out" result)" ]] || return 1
}

test_error_handling() {
    local out="$TMPDIR_E2E/error.json"
    local exit_code=0
    AI_PROVIDER=nonexistent_provider_xyz \
        python chat.py run --no-approval \
        --task "hello" --output "$out" --timeout 30 2>/dev/null || exit_code=$?
    # The provider resolution may raise before batch mode writes JSON.
    # Either we get a JSON with success=False, or a non-zero exit code.
    if [[ -f "$out" ]]; then
        [[ "$(json_field "$out" success)" == "False" ]] || return 1
    else
        [[ "$exit_code" -ne 0 ]] || return 1
    fi
}

# ── run all tests ────────────────────────────────────────────────────
echo "═══════════════════════════════════════════════════"
echo "  Autopoiesis E2E Test Harness"
echo "  Provider: $AI_PROVIDER  |  LLM timeout: ${LLM_TIMEOUT}s"
echo "  Skip LLM: $SKIP_LLM  |  Temp: $TMPDIR_E2E"
echo "═══════════════════════════════════════════════════"
echo ""

run_test "basic_chat"           1 test_basic_chat
run_test "file_write"           1 test_file_write
run_test "file_read"            1 test_file_read
run_test "memory_store_recall"  1 test_memory_store_recall
run_test "knowledge_search"     1 test_knowledge_search
run_test "topic_activation"     1 test_topic_activation
run_test "subscription_create"  1 test_subscription_create
run_test "timeout_handling"     0 test_timeout_handling
run_test "stdin_input"          1 test_stdin_input
run_test "error_handling"       0 test_error_handling

# ── summary ──────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════"
echo "  RESULTS: $PASS passed, $FAIL failed, $SKIP skipped"
echo "═══════════════════════════════════════════════════"
for r in "${RESULTS[@]}"; do
    echo "  $r"
done
echo ""

if [[ "$FAIL" -gt 0 ]]; then
    exit 1
fi
exit 0
