# Autopoiesis Terminal-Bench Adapter

Harbor agent adapter for running [autopoiesis](https://github.com/DavSimFel/autopoiesis) in [Terminal-Bench](https://tbench.ai/) evaluations via the [Harbor framework](https://github.com/laude-institute/harbor).

## Installation

```bash
# Install harbor
uv tool install harbor

# Install this adapter (for development)
cd benchmarks
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

## Prerequisites

- Docker running
- API key for your provider:

```bash
export ANTHROPIC_API_KEY="..."
# or
export OPENAI_API_KEY="..."
# or
export OPENROUTER_API_KEY="..."
```

## Usage

### Run Terminal-Bench evaluation

```bash
harbor run \
  -d terminal-bench@2.0 \
  --agent-import-path autopoiesis_terminal_bench:AutopoiesisAgent \
  -n 4
```

### Run a single task for testing

```bash
harbor run \
  -d terminal-bench@2.0 \
  --agent-import-path autopoiesis_terminal_bench:AutopoiesisAgent \
  --task-ids <task-id>
```

### Validate setup with oracle

```bash
harbor run -d terminal-bench@2.0 -a oracle
```

### Run on cloud (Daytona)

```bash
export DAYTONA_API_KEY="..."
harbor run \
  -d terminal-bench@2.0 \
  --agent-import-path autopoiesis_terminal_bench:AutopoiesisAgent \
  --env daytona \
  -n 32
```

## Architecture

This adapter follows the **Installed Agent** pattern from Harbor:

1. **Install phase** (`install-autopoiesis.sh.j2`): Clones the repo, creates a venv, installs dependencies inside the Docker container.
2. **Run phase** (`agent.py`): Invokes `python chat.py run --task "..." --output result.json --timeout 300` for each benchmark task.
3. **Post-run** (`populate_context_post_run`): Parses the batch result JSON and populates `AgentContext.metadata` with success status, elapsed time, and approval rounds.

### Batch output format

The batch mode (`agent/batch.py`) outputs:

```json
{
  "success": true,
  "result": "...",
  "error": null,
  "approval_rounds": 3,
  "elapsed_seconds": 42.5
}
```

## End-to-end test harness

The `run.sh` script provides a local e2e test runner that exercises autopoiesis capabilities through the same batch-mode interface the Harbor adapter uses.

### Quick start

```bash
cd benchmarks
export ANTHROPIC_API_KEY="..."  # or OPENAI_API_KEY, OPENROUTER_API_KEY
./run.sh
```

### Test cases

| Name | Category | What it tests |
|------|----------|---------------|
| `basic_greeting` | chat | Simple instruction following |
| `reasoning` | chat | Basic arithmetic reasoning |
| `file_create` | file_ops | Creating and writing files |
| `file_read` | file_ops | Reading existing files |
| `memory_store` | memory | Storing data in memory |
| `knowledge_search` | knowledge | Querying the knowledge base |
| `topic_activation` | topics | Listing/activating topics |
| `forced_timeout` | timeout | Timeout handling (5s limit) |

### Run a single test

```bash
./run.sh --task basic_greeting
```

### Run via Harbor (requires Docker)

```bash
./run.sh --harbor
```

### Run with pytest directly

```bash
cd benchmarks
python -m pytest tests/test_e2e.py -v -k "file_ops"
```

## Known limitations

- Token usage and cost are not yet reported (autopoiesis batch mode doesn't emit them). `AgentContext.n_input_tokens` etc. remain `None`.
- The `--model` flag from Harbor is not yet forwarded to autopoiesis (would require `chat.py run` to accept a model override).

## Reference

- [pi-terminal-bench](https://github.com/badlogic/pi-terminal-bench) — reference adapter implementation
- [Harbor BaseInstalledAgent](https://github.com/laude-institute/harbor/blob/main/src/harbor/agents/installed/base.py) — base class
