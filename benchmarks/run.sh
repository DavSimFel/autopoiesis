#!/bin/bash
# Test runner for autopoiesis benchmarks and e2e tests.
#
# Usage:
#   ./run.sh              Run local e2e harness (batch mode + real LLM)
#   ./run.sh --harbor     Run via Harbor + Terminal-Bench dataset
#   ./run.sh <task_ids>   Run specific tasks only (e.g. basic_chat file_write)
#
# Requires:
#   - AI provider key (set in .env or environment)
#   - For --harbor: Docker running + harbor installed
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Load .env if present ─────────────────────────────────────────────
if [ -f "$REPO_ROOT/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$REPO_ROOT/.env"
    set +a
fi

# ── Helpers ──────────────────────────────────────────────────────────
red()   { printf '\033[0;31m%s\033[0m\n' "$*"; }
bold()  { printf '\033[1m%s\033[0m\n' "$*"; }

check_provider_key() {
    if [ -z "${ANTHROPIC_API_KEY:-}" ] \
        && [ -z "${OPENAI_API_KEY:-}" ] \
        && [ -z "${OPENROUTER_API_KEY:-}" ]; then
        red "Error: No AI provider key set."
        echo "Export one of: ANTHROPIC_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY"
        exit 1
    fi
}

# ── Mode: Harbor ─────────────────────────────────────────────────────
run_harbor() {
    check_provider_key

    if ! docker info > /dev/null 2>&1; then
        red "Error: Docker is not running"
        exit 1
    fi

    if ! command -v harbor &> /dev/null; then
        red "Error: harbor not found. Install with: uv tool install harbor"
        exit 1
    fi

    bold "Running autopoiesis via Harbor + Terminal-Bench..."
    cd "$SCRIPT_DIR"

    if [ ! -d .venv ]; then
        uv venv
    fi
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

# ── Main ─────────────────────────────────────────────────────────────
case "${1:-}" in
    --harbor)
        shift
        run_harbor "$@"
        ;;
    --help|-h)
        head -9 "$0" | tail -8 | sed 's/^# \?//'
        ;;
    *)
        check_provider_key
        exec "$SCRIPT_DIR/harness/run.sh" "$@"
        ;;
esac
