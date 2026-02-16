#!/bin/bash
# End-to-end test harness for autopoiesis Terminal-Bench adapter.
#
# Usage:
#   ./run.sh              Run e2e tests (local, no Docker)
#   ./run.sh --harbor     Run via Harbor + Terminal-Bench dataset
#   ./run.sh --task NAME  Run a single e2e test by name
#
# Requires:
#   - AI provider key (ANTHROPIC_API_KEY, OPENAI_API_KEY, or OPENROUTER_API_KEY)
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
green() { printf '\033[0;32m%s\033[0m\n' "$*"; }
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

    # Ensure the adapter package is installed.
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

# ── Mode: Local e2e tests ────────────────────────────────────────────
run_local() {
    check_provider_key

    bold "Running local e2e tests for autopoiesis..."
    cd "$SCRIPT_DIR"

    # Set up venv if needed.
    if [ ! -d .venv ]; then
        uv venv
    fi
    # shellcheck disable=SC1091
    source .venv/bin/activate
    uv pip install -e ".[dev]" --quiet

    # Also ensure autopoiesis itself is installed.
    uv pip install -e "$REPO_ROOT" --quiet 2>/dev/null || true

    local pytest_args=(-v --tb=short)

    # Filter to a single task if --task was given.
    if [ -n "${TASK_NAME:-}" ]; then
        pytest_args+=(-k "$TASK_NAME")
    fi

    python -m pytest tests/test_e2e.py "${pytest_args[@]}"
}

# ── Main ─────────────────────────────────────────────────────────────
main() {
    case "${1:-}" in
        --harbor)
            shift
            run_harbor "$@"
            ;;
        --task)
            TASK_NAME="${2:?'Missing task name after --task'}"
            shift 2
            run_local "$@"
            ;;
        --help|-h)
            head -8 "$0" | tail -7 | sed 's/^# \?//'
            ;;
        *)
            run_local "$@"
            ;;
    esac
}

main "$@"
