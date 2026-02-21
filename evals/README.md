# Autopoiesis Evals

Inspect AI evaluation foundation for the Autopoiesis batch CLI.

## Prerequisites

- Autopoiesis repo checked out and configured (`.env` created at repo root)
- `autopoiesis` CLI available on `PATH`
- Python 3.12+

## Run Locally

```bash
cd evals/
pip install -e .
inspect eval tasks/core_capabilities.py
```

## What This Includes

- `tasks/core_capabilities.py`: 7 baseline capability tasks
- `solvers/autopoiesis_solver.py`: subprocess solver that runs `autopoiesis --no-approval run ...`
- `scorers/basic_scorer.py`: pass/fail scoring plus structured run metrics

## Notes

- The solver reads structured batch JSON output from Autopoiesis and stores parsed metrics in Inspect state for scoring.
- Token usage, tool calls, and cost are extracted when present in batch JSON and left null/zero when unavailable.
