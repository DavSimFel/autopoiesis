# Plan System Design

*Research for #131. 2026-02-17. Dense and opinionated.*

---

## Central Design Principle: Hard Verification > Advisory Guardrails

The agent **cannot** mark a step as done. Only the harness can, by running the contract command and checking its exit code. This is not a policy choice — it's the architectural invariant everything else hangs on.

Why: LLMs confabulate. An agent will happily report "tests pass" when they don't. Self-reported status is worthless for anything that matters. The harness runs the contract in a separate process, observes the exit code (and optionally stdout), and that result is the sole source of truth for step completion.

This means:
- Contracts are **shell commands** evaluated by the orchestrator harness, not the executing agent
- The executing agent has no mechanism to advance the plan — it just does work and exits
- Contract evaluation ties directly into the shell tool (#170) infrastructure
- A plan with good contracts is **self-verifying** — you can audit it without trusting any agent

---

## 1. Plan File Format

### Frontmatter (Minimal)

Only what the runtime needs for dispatch and filtering:

```yaml
---
type: plan
status: draft        # draft | verified | approved | in-progress | done | failed
owner: orchestrator  # agent role that owns execution
---
```

Three fields. That's it. Everything else is body content for the orchestrator LLM to read.

Why not put `budget`, `created_at`, `priority` in frontmatter? Because the orchestrator is an LLM — it can read prose. Frontmatter is for the runtime's `grep` and `awk`, not for the agent.

### Body Structure

```markdown
---
type: plan
status: draft
owner: orchestrator
---

# Fix authentication timeout bug (#423)

**Context:** Login requests timeout after 30s on slow connections. Root cause unknown.
**Budget:** max 200k tokens, $1.50, 20 minutes wall clock
**Priority:** high

## Steps

### 1. Analyze the bug

**target:** coder
**subscriptions:**
- file:src/auth/handler.py
- file:src/auth/middleware.py
- topic:fix-auth-timeout

**task:**
Read the auth handler and middleware. Trace the timeout path. Write a root cause
analysis to `docs/analysis-423.md` with the specific code path that causes the timeout.

**contract:**
```shell
test -f docs/analysis-423.md && test "$(wc -l < docs/analysis-423.md)" -gt 10
```
exit_code == 0
**on_fail:** retry(2), then escalate

### 2. Write the fix

**target:** coder
**subscriptions:**
- file:src/auth/handler.py
- file:docs/analysis-423.md

**task:**
Based on the root cause analysis, implement the fix. Do not change the public API.
Add a test for the specific timeout scenario.

**contract:**
```shell
uv run pytest tests/auth/ -x
```
exit_code == 0
**on_fail:** retry(2), then escalate

### 3. Lint and type check

**target:** coder
**subscriptions:**
- file:src/auth/handler.py

**task:**
Fix any lint or type errors introduced by the previous step.

**contract:**
```shell
uv run ruff check src/auth/ && uv run pyright src/auth/
```
exit_code == 0
**on_fail:** retry(1), then escalate

### 4. Create PR

**target:** coder
**subscriptions:**
- topic:fix-auth-timeout

**task:**
Commit the changes on a feature branch, push, and open a PR.

**contract:**
```shell
gh pr view --json state -q '.state' | grep -q OPEN
```
exit_code == 0
**on_fail:** escalate
```

### Parsing Strategy

The orchestrator is an LLM — it reads the plan as markdown. But the harness needs to extract WorkUnits mechanically for contract evaluation. The parser is simple:

1. Split on `### N.` headers → WorkUnit boundaries
2. Extract fenced code blocks after `**contract:**` → shell command
3. Extract `exit_code ==` line → expected result
4. Extract `**target:**` line → agent role for WorkItem dispatch
5. Extract `**subscriptions:**` list → context bindings
6. Extract `**on_fail:**` → retry/escalate policy

This is ~50 lines of Python with regex. No YAML-in-markdown, no custom DSL, no parser generator. If the format drifts slightly (extra whitespace, different heading level), the orchestrator LLM can still read it — only the harness parser needs the structure, and it only needs contracts + targets.

**What NOT to do:** Don't put WorkUnit metadata in sub-frontmatter blocks. Don't invent a schema language. The plan is a briefing document with just enough structure for mechanical extraction.

### More Examples

**Example 2: Multi-file refactor (extract module)**

```markdown
---
type: plan
status: draft
owner: orchestrator
---

# Extract config module from monolith

**Context:** `src/app.py` is 2400 lines. Config handling (lines 45-380) should be its own module.
**Budget:** max 300k tokens, $2.00, 30 minutes

## Steps

### 1. Map dependencies

**target:** coder
**subscriptions:**
- file:src/app.py

**task:**
Identify every function/class in lines 45-380 of app.py and all their imports,
callers, and callees. Write dependency map to `docs/config-deps.md`.

**contract:**
```shell
test -f docs/config-deps.md
```
exit_code == 0
**on_fail:** retry(1), then escalate

### 2. Extract module

**target:** coder
**subscriptions:**
- file:src/app.py
- file:docs/config-deps.md

**task:**
Move config code to `src/config.py`. Update all imports in `src/app.py`.
Do NOT change behavior.

**contract:**
```shell
uv run pytest tests/ -x && uv run ruff check src/
```
exit_code == 0
**on_fail:** retry(2), then escalate

### 3. Review extraction

**target:** reviewer
**subscriptions:**
- file:src/config.py
- file:src/app.py
- file:docs/config-deps.md

**task:**
Verify: no behavior change, all dependencies satisfied, no circular imports,
clean module boundary. Write review to `docs/review-config-extract.md`.

**contract:**
```shell
test -f docs/review-config-extract.md && grep -q "APPROVED\|CHANGES_REQUESTED" docs/review-config-extract.md
```
exit_code == 0
**on_fail:** escalate
```

**Example 3: Codebase-wide migration (sync → async)**

```markdown
---
type: plan
status: draft
owner: orchestrator
---

# Migrate HTTP client from requests to httpx async

**Context:** 47 files use `requests`. Migrate to `httpx` with async. Cannot break existing tests.
**Budget:** max 1M tokens, $8.00, 60 minutes

## Steps

### 1. Inventory all usage

**target:** coder
**subscriptions:**
- file:requirements.txt

**task:**
grep -r for all `import requests` and `from requests` across the codebase.
Categorize by: simple GET/POST, session usage, streaming, auth. Output to `docs/requests-inventory.md`.

**contract:**
```shell
test -f docs/requests-inventory.md && grep -c "^-" docs/requests-inventory.md | awk '{exit ($1 > 0 ? 0 : 1)}'
```
exit_code == 0
**on_fail:** retry(1), then escalate

### 2. Add httpx dependency

**target:** coder
**task:**
Add httpx to pyproject.toml. Run uv sync.

**contract:**
```shell
uv run python -c "import httpx; print(httpx.__version__)"
```
exit_code == 0
**on_fail:** retry(1), then escalate

### 3–N. Migrate file batch (one step per batch of ~5 files)

**target:** coder
**subscriptions:**
- file:docs/requests-inventory.md

**task:**
Migrate files [batch list here]. Replace requests calls with httpx equivalents.
Maintain sync interface where callers are sync; add async where callers are already async.

**contract:**
```shell
uv run pytest tests/ -x --timeout=60
```
exit_code == 0
**on_fail:** retry(2), then escalate

### N+1. Remove requests dependency

**target:** coder
**task:**
Remove `requests` from pyproject.toml. Run uv sync. Verify no remaining imports.

**contract:**
```shell
! grep -r "import requests" src/ && uv run pytest tests/ -x
```
exit_code == 0
**on_fail:** escalate
```

Note: the codebase migration shows that plans can be *generated* with variable step counts. The orchestrator writes the plan after reading the inventory — step 3 through N are templated per batch.

---

## 2. Plan Lifecycle

```
Draft ──→ Verified ──→ Approved ──→ In-Progress ──→ Done
  │          │            │             │              
  │          │            │             └──→ Failed    
  │          │            └── (T1 rejects) ──→ Draft   
  │          └── (verification fails) ──→ Draft        
  └── (T2 writes/edits)                                
```

| Transition | Who | How |
|---|---|---|
| → Draft | T2 (Planner) | Writes the plan file |
| Draft → Verified | Harness | Static checks pass (see §6) |
| Verified → Approved | T1 (Human) or auto-approve policy | Human reviews plan, says "go" |
| Approved → In-Progress | T2 (Orchestrator) | Begins dispatching WorkItems |
| In-Progress → Done | Harness | All contracts pass |
| In-Progress → Failed | Harness | Contract fails after max retries, escalation exhausted |
| Failed → In-Progress | T2 | Resumes from last passing contract |
| Any → Draft | T1 or T2 | Plan needs revision |

**Resumability:** The plan file records which step last passed its contract (the orchestrator updates the step status inline — e.g., changing `### 1. Analyze the bug` to `### 1. ✅ Analyze the bug` or adding a `**status: done**` line). On resume, the orchestrator skips steps with passing contracts and starts from the first non-done step. Simple, visible, grep-able.

---

## 3. Orchestrator Behavior (T2)

The T2 orchestrator is an LLM agent, not a state machine. It reads the plan, understands it, and executes it step by step. But contract evaluation is **not** done by the T2 — it's done by the harness.

### Execution Loop

```
for each WorkUnit in plan:
    1. Parse: extract target, subscriptions, task, contract
    2. Dispatch: create WorkItem {
         agent_id: target,
         type: CODE | REVIEW,
         input: { prompt: task text },
         payload: { subscriptions: [...], plan_id: ..., step: N }
       }
    3. Enqueue WorkItem → work_queue
    4. Wait: poll for WorkItem completion (output != None)
    5. Verify: harness runs contract shell command
       - exit_code matches expectation → step passes
       - exit_code mismatch → retry per on_fail policy
    6. Record: update plan file (mark step done/failed)
    7. Next step or terminate
```

### How the Orchestrator Waits

The orchestrator is a DBOS durable workflow. After dispatching a WorkItem, it `DBOS.sleep()` and polls the work item status. When the worker completes the item (sets `output`), the orchestrator wakes, runs the contract, and proceeds.

Alternative: the worker could publish a completion event to a DBOS topic that the orchestrator subscribes to. But polling is simpler for MVP and DBOS durability means the orchestrator survives restarts.

### On Failure

```
on_fail: retry(N)     → re-enqueue same WorkItem up to N times
on_fail: escalate     → create WorkItem for T1 (human) with failure context
on_fail: abort        → mark plan as Failed, stop
on_fail: retry(N), then escalate  → try N times, then escalate (default)
```

The orchestrator does NOT improvise. If the contract fails and the policy says escalate, it escalates. It does not try a different approach, skip the step, or modify the plan. Plan modification requires going back to Draft status.

---

## 4. WorkUnit → WorkItem Mapping

A WorkUnit in the plan becomes a WorkItem in the queue:

| WorkUnit field | WorkItem field | Notes |
|---|---|---|
| `target` | `agent_id` | Role name resolved to agent instance |
| `task` (body text) | `input.prompt` | The full task description becomes the prompt |
| `subscriptions` | `payload.subscriptions` | List of `file:` and `topic:` refs |
| step number | `payload.step` | For tracking |
| plan file path | `payload.plan_id` | Back-reference |
| (inferred) | `type` | `CODE` for coder, `REVIEW` for reviewer |

### Subscription Activation

When the worker picks up a WorkItem with `payload.subscriptions`, the runtime calls `inject_topic_context()` (already exists in `topic_processor.py:30`) for each `topic:` subscription, and reads + injects file contents for each `file:` subscription.

This is the existing subscription pipeline from #150 — plans just declare which subscriptions each step needs, and the runtime activates them. No new mechanism needed.

### Contract Evaluation

The harness (not the agent) runs the contract:

```python
import subprocess

def evaluate_contract(command: str, expect_exit_code: int = 0) -> bool:
    """Run contract command in workspace. Agent cannot influence this."""
    result = subprocess.run(
        command, shell=True, capture_output=True, timeout=60,
        cwd=workspace_path  # Same workspace the agent worked in
    )
    return result.returncode == expect_exit_code
```

That's it. ~10 lines. The contract runs in the same workspace but in a separate process the agent has no control over. The agent could delete the test files or modify the contract — but it can't, because:
1. The contract is read from the plan file, which the worker agent doesn't have write access to (it's the orchestrator's artifact)
2. The shell tool (#170) security tiers would classify plan file modification as `Approve` tier

---

## 5. Ephemeral T3 Agents

### Lifecycle

Spun up **per WorkUnit**, not per plan. Each step gets a fresh agent with:
- Clean message history (no bleed from previous steps)
- Subscriptions from the WorkUnit (files + topics injected into context)
- The task prompt as its sole instruction
- Access to the shared workspace (same filesystem)

### Workspace: Shared, Not Isolated

T3 agents work in the same workspace as the orchestrator. Why:
- Contracts verify workspace state (file exists, tests pass) — isolated workspaces break this
- Steps build on each other — step 2 needs the files step 1 created
- Branch-per-agent is premature complexity (and git operations are slow)

**Risk:** Two T3 agents running in parallel could clobber each other's files. **Mitigation:** Plans execute sequentially by default. Parallel execution is a future optimization that requires explicit dependency declarations.

### Cleanup

After a WorkUnit completes (contract passes or fails):
- Agent process terminates
- Message history is discarded (it's ephemeral)
- Workspace artifacts remain (they're the output)
- WorkItem output records the agent's final response text

### Result Reporting

The T3 agent doesn't know it's part of a plan. It receives a WorkItem, does work, produces output. The WorkItem's `output.text` field carries the agent's response back. The orchestrator reads it for context but does **not** use it to determine success — only the contract does that.

---

## 6. Plan Verification (Pre-Execution)

A plan can be statically verified before any agent runs. This is the "compiler" analogy from #131.

### What Can Be Checked

| Check | How | Catches |
|---|---|---|
| Contract syntax | Parse shell command, check it's valid bash | Typos, broken commands |
| Contract tools exist | `which pytest`, `which ruff`, etc. | Missing dependencies |
| Subscription targets exist | Check files on disk, topics in topic_manager | References to nonexistent context |
| Step ordering | Build dependency graph from subscriptions — if step N subscribes to a file only created in step N+2, that's wrong | Ordering errors |
| No circular deps | Topological sort of subscription graph | Deadlocks |
| Budget sanity | Token/cost/time estimates vs. step count | Unrealistic budgets |
| Target agents exist | Check agent_id resolution | Dispatch to nonexistent agent |

### What Cannot Be Checked

- Whether the task description is good enough for the agent to succeed
- Whether the contract is the *right* contract (tests pass ≠ bug fixed correctly)
- Whether the budget is sufficient
- Runtime failures (network, disk, crashes)

### Verification as a Step

Verification itself could be a WorkItem sent to a `reviewer` agent: "Here is a plan. Check that the contracts are achievable, subscriptions exist, and steps are ordered correctly." The reviewer's contract: `exit_code == 0` on a plan-lint command.

But for MVP, verification is a Python function the orchestrator calls before transitioning from Draft → Verified:

```python
def verify_plan(plan_path: Path) -> list[str]:
    """Return list of issues. Empty = verified."""
    issues = []
    steps = parse_work_units(plan_path)
    produced_files: set[str] = set()
    
    for step in steps:
        # Check subscriptions reference existing files or files produced by prior steps
        for sub in step.subscriptions:
            if sub.startswith("file:"):
                path = sub.removeprefix("file:")
                if not Path(path).exists() and path not in produced_files:
                    issues.append(f"Step {step.number}: subscribes to {path} which doesn't exist yet")
        
        # Track files this step might produce (heuristic: check contract file refs)
        for ref in extract_file_refs(step.contract):
            produced_files.add(ref)
        
        # Check contract command syntax
        result = subprocess.run(["bash", "-n", "-c", step.contract_command], capture_output=True)
        if result.returncode != 0:
            issues.append(f"Step {step.number}: contract has bash syntax error: {result.stderr}")
    
    return issues
```

---

## 7. Failure Modes & Recovery

### Step fails contract after N retries

The orchestrator has seen the agent's output text (from WorkItem.output) and the contract failure. It can:
1. **Retry** with augmented prompt: "Previous attempt failed. Contract `pytest` returned exit code 1. Stderr: [truncated]. Try again."
2. **Escalate** to T1: create a WorkItem with the failure context for human review.
3. **Abort** the plan: mark as Failed, stop.

Retry prompt augmentation is key — the agent gets the contract's stderr, which is often enough to fix the issue.

### Agent crashes mid-step

DBOS durability handles this. The WorkItem stays in the queue with no output. The orchestrator's poll sees no completion. After a timeout (configurable per step, default 10 minutes), the orchestrator treats it as a failure and applies the on_fail policy.

### Plan references nonexistent file/topic

Caught by verification (§6). If verification is skipped (auto-approved plan), the subscription injection fails gracefully — the agent just doesn't get that context. The contract will likely fail, triggering retry/escalate.

### Two plans competing for same resources

Not handled in MVP. Sequential plan execution (one plan at a time per workspace) eliminates this. Future: file-level locking or branch-per-plan.

### Human intervention needed mid-plan

The escalation WorkItem goes to the T1 queue. The plan status stays In-Progress but the current step is blocked. When the human responds (completes the escalation WorkItem), the orchestrator reads the response and decides: retry the step, modify the plan (→ Draft), or abort.

### Budget exceeded

Checked before each step dispatch. If remaining budget < estimated step cost, escalate to T1 with "budget exceeded, N steps remaining, need $X more."

---

## 8. Prior Art

### Devin (Cognition)

Plan-then-execute. Human reviews plan before execution begins. Key insight they got right: the plan is a **checkpoint artifact** — if something goes wrong, you can see exactly where and why. Key thing they got wrong (or at least, that we should avoid): plans are opaque internal state, not human-editable files.

### OpenAI Codex CLI

Task decomposition into subtasks. Each subtask runs in a sandbox. Verification is test-based. Similar contract-gate pattern but no explicit plan file — the orchestration is implicit in the agent loop. We're making it explicit and persistent.

### SWE-agent

Trajectory-based: records every action as a trace. Good for debugging but the trajectory is a *log*, not a *plan* — you can't verify it before execution, can't resume it, can't hand it to another agent. Our plans are prospective, not retrospective.

### OpenClaw Sub-Agents

`sessions_spawn` with task → auto-announce result. No contracts, no subscriptions, no sequential gating. It's fire-and-forget. Plans add the structure that sub-agents lack: ordered steps, context declaration, hard verification.

### What We're Stealing

| From | What | How |
|---|---|---|
| Devin | Plan as reviewable artifact | Plan file is human-readable markdown |
| Codex | Sandbox + test verification | Contract shell commands in separate process |
| SWE-agent | Action tracing | WorkItem output preserved per step |
| OpenClaw | Sub-agent dispatch | WorkItem queue already exists |
| Silas research | External verification, budget caps | Contracts + budget as first-class |

---

## 9. What's Essential vs. Premature

### Essential (build now)

- Plan file format with markdown WorkUnits
- Frontmatter: type, status, owner (3 fields)
- Contract = shell command + expected exit code, evaluated by harness
- Sequential execution: one step at a time
- WorkUnit → WorkItem mapping
- Subscription declaration per step (using existing inject_topic_context)
- Basic retry + escalate on failure
- Plan verification (syntax + subscription existence)
- Resumability from last passing contract

### Premature (build later)

- Parallel step execution with dependency graph
- `llm_judge` contracts (shell contracts cover 90% of cases)
- Branch-per-agent workspace isolation
- Budget enforcement (needs token counting infrastructure from #145)
- Plan templates / plan generation from issue descriptions
- Multi-plan coordination / resource locking
- Plan diffing and versioning
- Dynamic plan modification mid-execution

---

## 10. Recommended MVP

**Goal:** A T2 orchestrator can read a plan file, dispatch WorkItems to T3 agents sequentially, verify each step's contract, and mark the plan done or failed.

### Components

1. **Plan parser** (~100 LOC)
   - Read markdown, extract WorkUnits by `### N.` headers
   - Extract: target, subscriptions, task body, contract command, on_fail policy
   - No YAML, no schema validation, just regex + string splitting

2. **Contract evaluator** (~30 LOC)
   - `subprocess.run(command, shell=True)` in workspace directory
   - Compare exit code to expectation
   - Capture stderr for retry prompt augmentation

3. **Plan executor** (~200 LOC, DBOS durable workflow)
   - Read plan, iterate WorkUnits
   - For each: create WorkItem, enqueue, poll for completion, run contract
   - On pass: mark step done in plan file, continue
   - On fail: retry or escalate per policy
   - Update plan frontmatter status on completion

4. **Plan verifier** (~80 LOC)
   - Bash syntax check on contracts
   - Subscription file/topic existence check
   - Step ordering validation

5. **CLI command**: `autopoiesis plan run <plan.md>` and `autopoiesis plan verify <plan.md>`

### Dependencies

- #146 Phase A (agent_id on WorkItem) — **required**, already merged or close
- #150 (topic subscriptions) — **needed** for subscription activation, can stub
- #170 (shell tool) — **needed** for T3 agents to do work, can use existing exec_tool

### Not in MVP

- Plan creation by T2 agent (human writes plans for MVP)
- Budget enforcement
- Parallel execution
- LLM-judge contracts
- Auto-approval (all plans require T1 approval)

### Estimated Effort

~400 lines of Python. One PR. The hard part isn't the code — it's getting the plan format right so humans and LLMs both find it natural. The three examples above are the format test: if they read well and parse cleanly, the format is right.
