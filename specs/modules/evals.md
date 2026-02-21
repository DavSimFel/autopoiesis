# Module: evals

## Purpose

`evals/` provides an Inspect AI-based evaluation harness for Autopoiesis batch mode.
It enables repeatable baseline checks for core capabilities without importing runtime internals.

## Status

- **Last updated:** 2026-02-21 (Issue #195)
- **Source:** `evals/`

## Key Concepts

- **Separate project** - `evals/pyproject.toml` defines independent dependencies and install flow.
- **Subprocess solver** - eval execution invokes `autopoiesis --no-approval run ...` via CLI.
- **Metadata-aware scoring** - scorer emits pass/fail and structured execution metrics.

## Architecture

- `tasks/core_capabilities.py` defines baseline samples and wires solver/scorer.
- `solvers/autopoiesis_solver.py` executes the batch CLI and parses output JSON.
- `scorers/basic_scorer.py` applies expectation matching and captures structured metrics.

## API Surface

- Run from `evals/`:
  - `pip install -e .`
  - `inspect eval tasks/core_capabilities.py`

## Functions

- `autopoiesis_solver(timeout_seconds=60)` - solver factory for batch CLI invocation.
- `basic_scorer()` - scorer factory for expectation checks and metric reporting.
- `core_capabilities()` - task entrypoint for the baseline suite.

## Invariants & Rules

- `evals/` remains decoupled from Autopoiesis runtime imports.
- Solver interaction with Autopoiesis occurs only through subprocess CLI calls.
- Missing optional metrics (tokens, cost, tool calls) must not crash scoring.

## Dependencies

- `inspect-ai>=0.3` (declared in `evals/pyproject.toml`)

## Change Log

- 2026-02-21: Added Phase 1 Inspect AI foundation with solver/task/scorer skeleton and baseline task suite. (Issue #195)
