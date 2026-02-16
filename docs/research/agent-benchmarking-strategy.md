# Benchmarking & Optimization Strategy for Autopoiesis

> Research date: 2026-02-16 | Target: [autopoiesis](https://github.com/DavSimFel/autopoiesis) — PydanticAI + DBOS durable CLI agent with tool use, cryptographic approval, and skill self-creation

---

## Table of Contents

1. [SWE-bench](#1-swe-bench)
2. [Terminal-Bench](#2-terminal-bench)
3. [GAIA](#3-gaia)
4. [Benchmark Comparison](#4-benchmark-comparison)
5. [Benchmarking Strategy for Autopoiesis](#5-benchmarking-strategy-for-autopoiesis)
6. [Tuning & Optimization](#6-tuning--optimization)
7. [Practical Recommendations](#7-practical-recommendations)

---

## 1. SWE-bench

### How It Works

**SWE-bench** evaluates whether AI systems can resolve real-world GitHub issues. Each task instance provides:
- A **codebase** (Python repos like Django, scikit-learn, sympy, etc.)
- An **issue description** (the GitHub issue text)

The agent must produce a **git patch** that resolves the issue. Evaluation runs the repo's test suite in Docker:
- **FAIL_TO_PASS tests**: Tests that should now pass after the fix
- **PASS_TO_PASS tests**: Existing tests that must not break

The agent never sees the tests — it must infer what to fix from the issue description alone.

**Key links:**
- Repo: https://github.com/SWE-bench/SWE-bench
- Leaderboard: https://www.swebench.com/
- Paper: https://arxiv.org/abs/2310.06770
- Dataset: `princeton-nlp/SWE-bench` on HuggingFace

### Dataset Variants

| Variant | Size | Description |
|---------|------|-------------|
| **SWE-bench Full** | 2,294 | Original full dataset |
| **SWE-bench Lite** | 300 | Curated subset, easier to run |
| **SWE-bench Verified** | 500 | Human-confirmed solvable (with OpenAI Preparedness) |
| **SWE-bench Multimodal** | ~100+ | Visual/UI issues |
| **SWE-bench Bash Only** | 500 | Agent can only use bash commands |
| **SWE-bench Pro** | New | Harder, contamination-resistant (GPL repos) |

**Verified vs Full**: Verified is a curated 500-problem subset where software engineers confirmed each problem is solvable and unambiguous. It's the standard benchmark for agent comparison. Full has noise — some problems may be unsolvable or ambiguous.

### Current SOTA (Feb 2026, SWE-bench Verified)

| Agent/Model | Score |
|-------------|-------|
| Claude Opus 4.5 | ~80.9% |
| Claude Opus 4.6 | ~80.8% |
| MiniMax M2.5 | ~80.2% |
| GPT-5.2 | ~80.0% |
| GLM-5 | ~77.8% |
| Verdent + Claude Sonnet 4.5 | Surpasses Claude Code |
| Claude Opus 4.6 (Thinking) | ~79.2% (vals.ai) |

On **SWE-bench Pro**, scores drop dramatically: GPT-5 and Claude Opus 4.1 score only ~23%.

### How Top Agents Approach SWE-bench

**Devin (Cognition):** Fully autonomous agent — doesn't receive file hints. Uses its own file discovery, planning, and iterative editing. Operates "unassisted" (no oracle file list).

**SWE-agent:** The reference scaffold from the SWE-bench team. Provides the LLM with a custom shell interface (ACI — Agent-Computer Interface) with commands for searching, viewing, and editing files. Open source: https://swe-agent.com/

**Claude Code / Codex:** Use tool-augmented agents with bash execution, file editing, and search. Strong system prompts emphasize reading tests, understanding the codebase before editing, and iterative test-driven development.

**Common patterns:**
1. Locate relevant files (search, grep, repo structure analysis)
2. Understand the issue and existing tests
3. Plan the fix
4. Implement with precise edits
5. Run tests iteratively until passing

### Integrating a Custom Agent

Your agent needs to produce a **predictions file** — a JSONL where each line is:
```json
{"instance_id": "django__django-12345", "model_patch": "diff --git a/..."}
```

**Integration approach:**
1. Load the dataset from HuggingFace
2. For each instance: set up the repo at the correct commit, give your agent the issue text
3. Let your agent work (browse files, edit, run commands)
4. Capture the git diff as the patch
5. Run the SWE-bench evaluation harness:

```bash
python -m swebench.harness.run_evaluation \
  --dataset_name princeton-nlp/SWE-bench_Verified \
  --predictions_path predictions.jsonl \
  --max_workers 8 \
  --run_id my-agent-v1
```

**Or use cloud evaluation:**
- **Modal**: `--modal true` flag
- **sb-cli**: AWS-based evaluation tool from the SWE-bench team

### Hardware & Cost

| Resource | Requirement |
|----------|-------------|
| Machine | x86_64, 120GB+ disk, 16GB RAM, 8+ CPU cores |
| Docker | Required, with sufficient virtual disk |
| Workers | Recommended: `min(0.75 * cpu_count, 24)` |
| API cost per instance | ~$0.30–$2.00 depending on model and agent complexity |
| Full Verified run (500 instances) | ~$150–$1,000 in API costs |
| Time | 4–12 hours depending on concurrency |

---

## 2. Terminal-Bench

### How It Works

**Terminal-Bench** (Stanford × Laude Institute) evaluates AI agents on hard, realistic terminal tasks. Unlike SWE-bench (which focuses on code patches), Terminal-Bench tests end-to-end task completion in real terminal environments.

Each task includes:
- An **instruction** in English (e.g., "Install Windows XP in QEMU", "Play Zork to max score", "Reshard this dataset")
- A **test script** that programmatically verifies success
- An **oracle solution** (reference implementation)

Tasks run in **Docker containers** with full terminal access. The agent interacts via bash.

**Key links:**
- Website: https://www.tbench.ai/
- Repo: https://github.com/laude-institute/terminal-bench
- Paper: https://arxiv.org/abs/2601.11868
- Harbor framework: https://github.com/laude-institute/harbor

### Task Categories

| Category | Examples |
|----------|---------|
| Software Engineering | Compile code, fix build systems, manage dependencies |
| System Administration | Install OS in VMs, configure servers, manage services |
| Data Processing | Reshard datasets, ETL pipelines, data transformations |
| Games | Play Zork to max score, solve terminal games |
| ML/AI | Cache models for offline use, train models |
| Debugging | Find and fix system-level issues |

**Key difference from SWE-bench:** Terminal-Bench tasks are broader — not just "fix this issue" but "accomplish this complex terminal task end-to-end." Tasks are designed to be hard to pattern-match from training data.

### Current SOTA (Feb 2026, Terminal-Bench Hard)

| Agent/Model | Score |
|-------------|-------|
| Claude Opus 4.6 (Non-reasoning) | 48.5% |
| GPT-5.2 (xhigh) | 47.0% |
| Claude Opus 4.5 (Reasoning) | 47.0% |
| Frontier models | <65% on core benchmark |

No agent scores above 50% on the hard subset — this is a genuinely difficult benchmark.

### Terminal-Bench 2.0 & Harbor

Terminal-Bench 2.0 (Nov 2025) introduced **Harbor**, a new framework for evaluating agents:
- Supports cloud-deployed containers (Daytona)
- Unified interface for multiple benchmarks (SWE-bench, LiveCodeBench, etc.)
- Simple agent integration via Python classes

### Integrating a Custom Agent

**Option A: Terminal-Bench native (tb CLI)**
```bash
pip install terminal-bench

tb run \
  --agent your-agent \
  --model anthropic/claude-sonnet-4-5 \
  --dataset-name terminal-bench-core \
  --dataset-version 0.1.1 \
  --n-concurrent 8
```

**Option B: Harbor framework (recommended for custom agents)**

Create a Python agent class:
```python
# my_agent.py
from harbor import Agent

class AutopoiesisAgent(Agent):
    async def run(self, task_instruction: str, shell) -> None:
        # Your agent logic here
        # Use shell.execute("command") to run terminal commands
        # The agent reads the task instruction and works to complete it
        pass
```

Run with Harbor:
```bash
harbor run \
  -d terminal-bench@2.0 \
  --agent-import-path my_agent:AutopoiesisAgent \
  -m anthropic/claude-sonnet-4-5 \
  -n 4
```

See example: https://github.com/badlogic/pi-terminal-bench (Harbor agent adapter reference)

### Relevance to Autopoiesis

**HIGH relevance.** Autopoiesis is a terminal-native agent with:
- Shell execution (directly maps to Terminal-Bench tasks)
- File operations (needed for most tasks)
- Tool use and planning (required for complex multi-step tasks)

Terminal-Bench is the **most natural fit** for autopoiesis.

---

## 3. GAIA

### How It Works

**GAIA** (General AI Assistants) tests whether AI agents can handle real-world questions that are simple for humans but require multi-step reasoning, tool use, and web interaction.

- **466 curated questions** with unambiguous, factual answers
- Answers are short: a number, a few words, or a comma-separated list
- Evaluation: **quasi exact match** against ground truth
- Questions require: web browsing, file analysis, code execution, multi-modal reasoning

**Key links:**
- Paper: https://arxiv.org/abs/2311.12983
- Leaderboard (HF): https://huggingface.co/spaces/gaia-benchmark/leaderboard
- Leaderboard (HAL/Princeton): https://hal.cs.princeton.edu/gaia
- Dataset: `gaia-benchmark/GAIA` on HuggingFace

### Difficulty Levels

| Level | Description | Human Performance | Best AI |
|-------|-------------|-------------------|---------|
| **Level 1** | Simple, should be solvable by good LLMs | ~95% | ~82% |
| **Level 2** | Moderate, requires multi-step reasoning + tools | ~93% | ~73% |
| **Level 3** | Hard, requires long-term planning + sophisticated tool use | ~88% | ~65% |
| **Overall** | All levels | ~92% | ~75% |

### Current SOTA (Feb 2026, HAL Leaderboard)

| Agent | Model | Accuracy | Cost |
|-------|-------|----------|------|
| HAL Generalist Agent | Claude Sonnet 4.5 (Sep 2025) | **74.55%** | $178 |
| HAL Generalist Agent | Claude Sonnet 4.5 High | 70.91% | $180 |
| HAL Generalist Agent | Claude Opus 4.1 High | 68.48% | $562 |
| HF Open Deep Research | GPT-5 Medium | 62.80% | $360 |
| h2oGPTe Agent (2025) | Proprietary | ~75% | N/A |

### Running GAIA with a Custom Agent

**Option A: UK Gov Inspect framework**
```bash
pip install inspect-evals
uv run inspect eval inspect_evals/gaia --model openai/gpt-4o
uv run inspect eval inspect_evals/gaia_level1 --model openai/gpt-4o
```

**Option B: Direct integration**
1. Load dataset: `datasets.load_dataset("gaia-benchmark/GAIA")`
2. For each task: give your agent the question (+ any attached files)
3. Agent uses tools (web search, file analysis, code execution) to find the answer
4. Collect answers as JSONL:
```json
{"task_id": "task_001", "model_answer": "42", "reasoning_trace": "..."}
```
5. Submit to HuggingFace leaderboard or self-evaluate on validation split

**System prompt (recommended by GAIA):**
> "You are a general AI assistant. Report your thoughts, and finish your answer with: FINAL ANSWER: [YOUR FINAL ANSWER]."

### Relevance to Autopoiesis

**MODERATE relevance.** GAIA tests general-purpose tool use and reasoning — areas where autopoiesis has capabilities. However:
- GAIA requires **web browsing** (autopoiesis may not have this)
- GAIA requires **file/image analysis** (PDF, spreadsheets, audio)
- Less focused on terminal/coding skills

GAIA is better as a secondary benchmark to validate general intelligence capabilities.

---

## 4. Benchmark Comparison

| Dimension | SWE-bench Verified | Terminal-Bench | GAIA |
|-----------|-------------------|----------------|------|
| **Focus** | Fix GitHub issues (code patches) | Complete terminal tasks end-to-end | Answer real-world questions |
| **Tasks** | 500 | ~100 (beta) | 466 |
| **Evaluation** | Test suite pass/fail | Verification scripts | Exact match |
| **Agent interface** | Produce git diff | Terminal/bash | Free-form + tools |
| **Domain** | Python repos only | Broad (sysadmin, data, ML, games) | General knowledge + tools |
| **SOTA** | ~80% | ~48% | ~75% |
| **Saturation** | Getting saturated | Far from saturated | Approaching saturation |
| **Cost per run** | $150–$1,000 | $50–$500 | $120–$650 |
| **Relevance to autopoiesis** | Medium | **High** | Medium |
| **Setup complexity** | Medium (Docker) | Low (pip + Docker) | Low (HF dataset) |

### Recommendation

**Primary benchmark: Terminal-Bench** — Most aligned with autopoiesis's terminal-native, tool-using design. Far from saturated, so improvements are meaningful.

**Secondary: SWE-bench Verified** — Industry standard, good for credibility and comparison. Well-understood evaluation.

**Tertiary: GAIA** — Tests general reasoning. Useful for validating breadth but requires web browsing capabilities autopoiesis may not have yet.

---

## 5. Benchmarking Strategy for Autopoiesis

### Minimum Viable Benchmarking Setup

**Phase 1: Terminal-Bench (Week 1-2)**

1. Install Terminal-Bench: `pip install terminal-bench`
2. Create a Harbor agent adapter for autopoiesis
3. Run on 5-10 tasks manually to validate integration
4. Run full Terminal-Bench Core (v0.1.1, ~100 tasks)
5. Record baseline score

**Phase 2: SWE-bench Lite (Week 3-4)**

1. Build an inference harness that:
   - Loads SWE-bench instances
   - Gives autopoiesis the issue + repo
   - Captures the git diff
   - Formats as predictions JSONL
2. Run on SWE-bench Lite (300 instances) for faster iteration
3. Graduate to Verified (500) once the harness is stable

### Reproducible Eval Harness Architecture

```
autopoiesis-bench/
├── harness/
│   ├── swebench_runner.py    # Loads instances, runs agent, captures patches
│   ├── tbench_adapter.py     # Harbor Agent class wrapping autopoiesis
│   ├── gaia_runner.py        # Question → agent → answer pipeline
│   └── metrics.py            # Track cost, latency, tokens, tool calls
├── configs/
│   ├── swebench.yaml         # Model, concurrency, dataset variant
│   ├── tbench.yaml
│   └── gaia.yaml
├── results/
│   ├── YYYY-MM-DD_swebench_v1.json
│   └── YYYY-MM-DD_tbench_v1.json
└── scripts/
    ├── run_swebench.sh
    ├── run_tbench.sh
    └── compare_results.py
```

### Metrics Beyond Pass Rate

| Metric | Why It Matters |
|--------|----------------|
| **Pass rate** | Primary success metric |
| **Cost per task** | API spend efficiency |
| **Tokens per task** (input/output/reasoning) | Context efficiency |
| **Tool calls per task** | Agent efficiency |
| **Time per task** | Latency / user experience |
| **Pass@k** | Reliability (pass rate over k attempts) |
| **Error categorization** | Where does the agent fail? (wrong file, wrong fix, timeout, etc.) |
| **Token-normalized pass rate** | Passes per $1 spent |

### Cost & Time Estimates

| Benchmark | Tasks | Est. API Cost | Est. Time (8 workers) |
|-----------|-------|---------------|----------------------|
| Terminal-Bench Core | ~100 | $50–$200 | 2–4 hours |
| SWE-bench Lite | 300 | $100–$600 | 4–8 hours |
| SWE-bench Verified | 500 | $150–$1,000 | 6–12 hours |
| GAIA validation | 165 | $30–$180 | 1–3 hours |

---

## 6. Tuning & Optimization

### How Top Agents Optimize

#### 1. System Prompt Engineering

**SWE-bench optimized prompts typically:**
- Instruct the agent to **read the issue carefully** and understand the full context
- Emphasize **exploring the codebase before editing** (grep, find, read related files)
- Require **running tests** after changes and iterating
- Limit scope: "Make minimal changes to fix the specific issue"
- Include repo-specific hints (directory structure, test commands)

**Terminal-Bench optimized prompts:**
- Emphasize **planning before acting** — decompose the task into steps
- Instruct verification: "Check your work at each step"
- Include common patterns: "If you need a package, install it with apt/pip first"

#### 2. Tool Design Patterns

| Pattern | Description | Impact |
|---------|-------------|--------|
| **Structured file editing** | Use search-and-replace instead of rewriting whole files | Reduces errors, improves precision |
| **Test-driven loops** | Run tests → analyze failures → fix → repeat | +10-20% on SWE-bench |
| **Hierarchical search** | Directory listing → grep → file read (progressive detail) | Reduces token waste |
| **Checkpoint/rollback** | Save state before risky changes, revert on failure | Prevents cascading errors |
| **Tool output summarization** | Truncate/summarize long outputs before feeding back | Saves context window |

#### 3. Context Window Management

- **Progressive disclosure**: Start with high-level repo structure, drill into files on demand
- **Sliding window**: For long files, show relevant sections only
- **Summary caching**: Summarize previously read files, keep summaries in context
- **Token budgeting**: Allocate token budgets per phase (exploration: 30%, editing: 50%, testing: 20%)

#### 4. Retrieval and Planning

- **BM25/embedding retrieval**: For SWE-bench, retrieve relevant files based on issue text similarity
- **Plan-then-execute**: Generate an explicit plan before taking actions. Top agents that plan first score 5-15% higher.
- **Reflection**: After a failed attempt, explicitly reason about what went wrong before retrying

#### 5. Model Selection

| Scenario | Recommended | Why |
|----------|-------------|-----|
| SWE-bench/Terminal-Bench (quality) | Claude Opus 4.5+ / GPT-5+ | Best reasoning, highest scores |
| SWE-bench (cost-efficient) | Claude Sonnet 4.5 / GPT-5-mini | 80-90% of top performance at 10-20% cost |
| GAIA | Reasoning models (high budget) | Multi-step reasoning benefits from extended thinking |
| Rapid iteration/testing | Fast models (Sonnet, GPT-4o) | Quick feedback loops during development |

**Reasoning models** (extended thinking) help most on:
- Complex multi-step problems
- Tasks requiring planning
- GAIA Level 3 tasks

They help least on:
- Simple file edits
- Tasks where execution speed matters
- High-concurrency runs (cost explodes)

#### 6. Cost-Performance Tradeoffs

From HAL GAIA leaderboard data:
- Claude Sonnet 4.5: **74.55% at $178** (best cost-efficiency)
- Claude Opus 4.1 High: **68.48% at $562** (3x cost for -6% accuracy)
- GPT-5 Medium: **62.80% at $360** (2x cost for -12% accuracy)

**Rule of thumb**: Sonnet-class models offer the best accuracy-per-dollar. Use Opus/GPT-5 only when the marginal accuracy matters (competitions, publications).

### Ablation Studies

To measure the impact of individual changes:

1. **Establish a baseline**: Run the full benchmark once with default configuration
2. **Change one variable at a time**: prompt, tool design, model, etc.
3. **Run on a consistent subset**: Use the same 50-100 tasks for ablations (faster, cheaper)
4. **Track all metrics**: Not just pass rate — also cost, tokens, time
5. **Statistical significance**: Run 2-3 times per configuration (agent behavior is non-deterministic)

**Ablation priority order:**
1. Model choice (biggest impact)
2. System prompt
3. Tool design (search, edit, test loop)
4. Context management strategy
5. Planning/reflection steps
6. Retrieval method

---

## 7. Practical Recommendations

### What Autopoiesis Should Implement First

#### Priority 1: Benchmark Adapter Layer (1-2 days)
- Create a **non-interactive mode** for autopoiesis (currently it's a CLI chat agent)
- Accept task instruction as input, produce result as output
- Disable cryptographic approval for benchmark runs (or auto-approve)
- Capture all actions for logging/tracing

#### Priority 2: Terminal-Bench Integration (2-3 days)
- Write a Harbor agent adapter (`AutopoiesisAgent` class)
- Map Terminal-Bench's shell interface to autopoiesis's tool system
- Run on 5 tasks, debug, iterate

#### Priority 3: SWE-bench Integration (3-5 days)
- Build inference pipeline: load instance → run agent → capture diff
- Handle repo setup (checkout correct commit, install dependencies)
- Format output as predictions JSONL
- Run on SWE-bench Lite subset (50 instances)

#### Priority 4: Metrics & Logging (1-2 days)
- Track: tokens (in/out/reasoning), tool calls, wall time, API cost
- Save per-task traces for error analysis
- Build comparison script for before/after runs

#### Priority 5: Optimization Loop (ongoing)
- Analyze failure modes from baseline runs
- Tune system prompt based on error patterns
- Implement test-driven development loop for SWE-bench
- Add planning step before execution

### Realistic Target Scores (First Run)

| Benchmark | Realistic First Run | After Optimization |
|-----------|--------------------|--------------------|
| Terminal-Bench Core | 15-25% | 30-40% |
| SWE-bench Lite | 10-20% | 25-40% |
| SWE-bench Verified | 10-18% | 20-35% |
| GAIA validation | 20-35% | 40-55% |

These assume autopoiesis uses a strong model (Claude Sonnet 4+). The gap to SOTA comes from:
- Scaffold/agent design (accounts for 20-40% of variance)
- Tool design and prompting (accounts for 10-20%)
- Model choice (accounts for 20-30%)

### Continuous Eval Setup

```yaml
# .github/workflows/benchmark.yml
name: Benchmark on Release
on:
  release:
    types: [published]
  workflow_dispatch:

jobs:
  benchmark:
    runs-on: ubuntu-latest  # or self-hosted with Docker
    steps:
      - uses: actions/checkout@v4
      - name: Run Terminal-Bench (subset)
        run: |
          pip install terminal-bench
          tb run \
            --agent autopoiesis_adapter:Agent \
            --model anthropic/claude-sonnet-4-5 \
            --dataset-name terminal-bench-core \
            --dataset-version 0.1.1 \
            --n-concurrent 4 \
            --subset 20  # Run 20 tasks for CI
      - name: Run SWE-bench (subset)
        run: |
          python harness/swebench_runner.py \
            --dataset princeton-nlp/SWE-bench_Lite \
            --limit 30 \
            --run-id "ci-${{ github.sha }}"
      - name: Compare with baseline
        run: python scripts/compare_results.py
      - name: Upload results
        uses: actions/upload-artifact@v4
        with:
          name: benchmark-results
          path: results/
```

**Cost-conscious CI**: Run a 20-30 task subset on PRs (~$10-30), full runs on releases (~$100-500).

### Summary: Action Plan

| Step | Action | Time | Cost |
|------|--------|------|------|
| 1 | Add non-interactive/batch mode to autopoiesis | 1-2 days | $0 |
| 2 | Write Terminal-Bench Harbor adapter | 2-3 days | $0 |
| 3 | Run Terminal-Bench baseline (100 tasks) | 1 day | ~$100 |
| 4 | Analyze failures, tune prompt & tools | 2-3 days | ~$50 |
| 5 | Write SWE-bench inference harness | 3-5 days | $0 |
| 6 | Run SWE-bench Lite baseline (300 tasks) | 1 day | ~$300 |
| 7 | Implement optimization loop (test-driven, planning) | 1 week | ~$200 |
| 8 | Set up CI benchmark pipeline | 1 day | $0 |
| **Total** | | **~3 weeks** | **~$650** |

---

## Appendix: Key Resources

| Resource | URL |
|----------|-----|
| SWE-bench repo | https://github.com/SWE-bench/SWE-bench |
| SWE-bench leaderboard | https://www.swebench.com/ |
| SWE-agent (reference scaffold) | https://swe-agent.com/ |
| mini-SWE-agent | https://mini-swe-agent.com/ |
| Terminal-Bench repo | https://github.com/laude-institute/terminal-bench |
| Terminal-Bench leaderboard | https://www.tbench.ai/leaderboard/terminal-bench/2.0 |
| Harbor framework | https://github.com/laude-institute/harbor |
| Harbor adapter docs | https://harborframework.com/docs/adapters |
| Example Harbor agent | https://github.com/badlogic/pi-terminal-bench |
| GAIA dataset | https://huggingface.co/datasets/gaia-benchmark/GAIA |
| GAIA leaderboard (HF) | https://huggingface.co/spaces/gaia-benchmark/leaderboard |
| GAIA leaderboard (HAL) | https://hal.cs.princeton.edu/gaia |
| GAIA paper | https://arxiv.org/abs/2311.12983 |
| Terminal-Bench paper | https://arxiv.org/abs/2601.11868 |
| SWE-bench paper | https://arxiv.org/abs/2310.06770 |
| SWE-rebench (decontaminated) | https://swe-rebench.com/ |
| SWE-bench Pro (Scale AI) | https://scale.com/leaderboard/swe_bench_pro_public |
| Artificial Analysis TB | https://artificialanalysis.ai/evaluations/terminalbench-hard |
