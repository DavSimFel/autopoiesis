# Benchmarks

Autopoiesis evaluation suite built on [Inspect AI](https://inspect.ai-safety-institute.org.uk/).

## Quick Start

```bash
# Run all benchmark tasks (requires OPENAI_API_KEY or ANTHROPIC_API_KEY)
uv run inspect eval benchmarks/tasks/tool_use.py benchmarks/tasks/knowledge.py

# Run a single task
uv run inspect eval benchmarks/tasks/tool_use.py

# View results
uv run inspect view
```

## Structure

```
benchmarks/
├── tasks/
│   ├── tool_use.py     # Tool selection accuracy
│   └── knowledge.py    # Knowledge retrieval from files
└── scorers/
    └── custom.py       # Evaluation mode scorers (exact|contains|llm_judge|metric_threshold)
```

## Evaluation Modes

Scorers follow the taxonomy from our benchmarking research:

| Mode | Description | Use case |
|------|-------------|----------|
| `exact` | String equality | CLI output, file contents |
| `contains` | Substring match | Partial output validation |
| `llm_judge` | LLM grades response | Open-ended quality |
| `metric_threshold` | Numeric >= threshold | Performance benchmarks |

## CI

Benchmarks run via `.github/workflows/benchmarks.yml`:
- **Manual trigger**: `workflow_dispatch`
- **Nightly**: 03:00 UTC daily

Results are uploaded as workflow artifacts.
