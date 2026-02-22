# Module: security

## Purpose

Documents the security model for shell command execution, including Ed25519
approval signing and tier-based command enforcement.

## Status

- **Last updated:** 2026-02-21 (Issue #221)
- **Source:** `specs/security.md` (full approval model), `src/autopoiesis/infra/command_classifier.py`, `src/autopoiesis/tools/tier_enforcement.py`, `src/autopoiesis/tools/exec_tool.py`

## Ed25519 Approval Model

See `specs/security.md` for the complete approval architecture (R1–R13).
The approval keypair is the root of trust: the CLI requires passphrase
unlock at startup before any side-effecting tool can execute.

## Tier-Based Command Enforcement

Shell commands are classified into four tiers by `command_classifier.classify()`:

| Tier | Examples | Behavior |
|------|----------|----------|
| **FREE** | `ls`, `cat`, `echo`, `grep`, `git status` | Always allowed |
| **REVIEW** | `pip install`, `git commit`, `python -c ...`, `tmux new -d ...` | Requires approval unlock |
| **APPROVE** | `rm`, `curl`, `git push` | Requires approval unlock |
| **BLOCK** | `sudo`, `su`, `doas` | Always denied |

### Enforcement rules

Tier enforcement is applied by `tools/tier_enforcement.py` and used by
`exec_tool.py` (`execute()` / `execute_pty()`). Commands are always classified
by `command_classifier.classify()` before execution.

1. **Without approval unlock** (`--no-approval` or batch mode): only FREE-tier
   commands are permitted. REVIEW and APPROVE commands return a blocked
   `ToolReturn` with an informative error message.
2. **With approval unlock** (normal interactive mode): FREE, REVIEW, and
   APPROVE commands are permitted. The deferred-tool approval flow (envelope
   signing) still applies for side-effecting PydanticAI tools.
3. **BLOCK tier**: always denied regardless of approval state.

### Docker/container exception

When the execution backend is a Docker or container-based sandbox, all tiers
(except BLOCK) are permitted without approval unlock. The container **is** the
sandbox — the host is not at risk. This exception is evaluated at the backend
level, not inside the tool call itself. Container backends pass
`approval_unlocked=True` when invoking execution tools.

### `--no-approval` flag

The `--no-approval` CLI flag allows startup without passphrase unlock. This is
**not** a full security bypass — it restricts execution to FREE-tier commands
only. It enables development and read-only workflows without key material.

## Invariants

- BLOCK-tier commands are never executed.
- Without approval unlock, only FREE-tier commands run.
- Tier classification is determined by `command_classifier.classify()` and
  covers chained commands (pipes, `&&`, `||`, `;`) — the worst tier wins.

## Change Log

- 2026-02-21: Added FastMCP skill hardening components:
  `PathValidationTransform`, `ApprovalGateTransform`, and
  `SandboxedSkillProvider`. (Issue #221)
- 2026-02-21: Increased default subprocess process cap to 512 and refined
  RLIMIT behavior so only `RLIMIT_NPROC` preserves inherited soft limits.
  `RLIMIT_FSIZE` and `RLIMIT_CPU` continue enforcing strict caps. (Issue #221)
- 2026-02-18: Removed legacy `shell_tool` references, documented
  `python`/`python3`/`tmux` as REVIEW-tier commands, and aligned enforcement
  docs to `tier_enforcement.py` + `exec_tool.py`. (Issue #170)

## Security Hardening (#213-#217)
- PathValidator: validates file paths against sandbox boundaries
- TaintTracker: marks external content as tainted for sanitization
- SubprocessSandboxManager: enforces preexec_fn in PTY/exec calls

## FastMCP Skill Security Hardening (Issue #221, Phase 3)

### PathValidationTransform

`src/autopoiesis/skills/skill_transforms.py` adds `PathValidationTransform`,
a runtime FastMCP tool transform that targets tools exposing path-like string
arguments (`path`, `file_path`, `directory`).

Execution behavior:

- Path args are resolved through `PathValidator.resolve_path()`.
- Valid paths are normalized to absolute resolved paths before tool execution.
- Escaping paths are blocked and return a blocked `ToolResult`.

### ApprovalGateTransform

`src/autopoiesis/skills/auth_middleware.py` adds `ApprovalGateTransform`, a
runtime FastMCP tool transform for approval-tier gating.

Tier sources (precedence order):

1. `skill.yaml` per-tool overrides.
2. Tool metadata (`approval_tier`, including nested `security` and `autopoiesis` blocks).
3. Tool tags (`tier:<value>` or `approval:<value>`).

Enforcement behavior:

- `approve` tier (or stricter) requires an active approval unlock.
- If unlocked, tool execution passes through.
- If not unlocked, tool execution is blocked with an approval-required message.

### SandboxedSkillProvider

`src/autopoiesis/skills/sandboxed_provider.py` introduces
`SandboxedSkillProvider`, which runs skill tools in a dedicated stdio child
process and exposes them to the parent server via `ProxyProvider`.

Controls:

- Child process limits are applied through `SandboxLimits` +
  `SubprocessSandboxManager`.
- `RLIMIT_NPROC`, `RLIMIT_FSIZE`, and `RLIMIT_CPU` are enforced before serving.
- Skill module path is validated via `PathValidator`.

## Subprocess Sandbox Limits

`SubprocessSandboxManager` applies RLIMIT caps in its pre-exec hook:

- `RLIMIT_NPROC`: default target is `512`; inherited soft limit is never
  lowered below the existing value.
- `RLIMIT_FSIZE`: capped to configured sandbox value.
- `RLIMIT_CPU`: capped to configured sandbox value.

The non-lowering behavior is specific to process-count limits, while CPU and
file-size safeguards remain strict caps.
