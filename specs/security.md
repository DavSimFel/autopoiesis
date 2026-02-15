# Security Model — Draft v2

## Purpose

Define the trust boundaries, approval guarantees, and integrity properties
for autopoiesis agent execution. No tool with side effects executes without
verifiable, single-use, unexpired human authorization bound to the exact
plan shown to the human.

## Status
- **Last updated:** 2026-02-15 (design phase — not yet implemented)
- **Threat model:** Single-user CLI today, networked multi-surface later

---

## Threat Model

### What we're protecting against

| Threat | Vector | Current exposure |
|--------|--------|-----------------|
| **Plan tampering** | Modify plan between approval display and execution | Yes — no binding |
| **Approval replay** | Reuse approval for different/repeated action | Yes — no nonce |
| **Approval injection** | Craft `deferred_tool_results_json` with `approved: true` | Yes — trusted without verification |
| **Context drift** | Same tool calls but different execution context (workspace, policy) | Yes — nothing bound |
| **Race condition** | Concurrent execution before nonce is marked consumed | Yes — no atomicity |
| **Audit tampering** | Rewrite audit log after the fact | Yes — no log exists |
| **UI mismatch** | Human sees truncated/modified version of what's hashed | Yes — display truncates args |

### What we're NOT protecting against (yet)

- Compromised host (attacker has local code execution → game over)
- Model-level prompt injection (out of scope — handled by tool scoping)
- Network MITM (not networked yet)

---

## Core Concept: Approval Envelope

The **ApprovalEnvelope** is the central trust anchor. It is:
- Created server-side before the human sees anything
- Persisted in SQLite (same DB as DBOS)
- Immutable after creation
- The ONLY source of truth for verification at execution time

The submitted `deferred_tool_results_json` carries only the nonce and
per-tool decisions. Everything else is verified against the stored envelope.

---

## Requirements

### R1: Approval Envelope (server-side trust anchor)

**R1.1** When the agent produces `DeferredToolRequests`, the system MUST
create and persist an `ApprovalEnvelope` BEFORE presenting anything to the
human. Fields:

| Field | Type | Description |
|-------|------|-------------|
| `envelope_id` | UUID4 | Primary key |
| `work_item_id` | str | The work item this approval belongs to |
| `nonce` | UUID4 | Single-use token |
| `plan_hash` | str | SHA-256 of canonical execution payload |
| `state` | enum | `pending` → `consumed` / `rejected` / `expired` |
| `issued_at` | datetime(UTC) | Creation time |
| `expires_at` | datetime(UTC) | `issued_at + APPROVAL_TTL_SECONDS` |
| `tool_call_ids` | list[str] | Ordered list of tool_call_ids in this envelope |

**R1.2** The `plan_hash` MUST cover the full **execution envelope**, not
just tool call fields:

- `work_item_id`
- For each tool call (in order): `tool_call_id`, `tool_name`, `args`
- `workspace_root` (resolved absolute path)
- `toolset_mode` (e.g. `require_write_approval`)
- `agent_name`

**R1.3** Canonical serialization: `json.dumps(payload, sort_keys=True,
separators=(',', ':'), ensure_ascii=True)` → UTF-8 bytes → SHA-256 hex.
Deterministic. No ambiguity.

**R1.4** At execution time, the system MUST:
1. Look up the envelope by `nonce` (from the submission)
2. Verify `state == 'pending'` (atomic transition — see R2)
3. Verify `now < expires_at`
4. Recompute `plan_hash` from the current execution context
5. Verify computed hash == stored hash (detects context drift)
6. Verify strict bijection: submitted decisions map 1:1 to stored
   `tool_call_ids`, same order, no missing, no extra
7. Only then execute

Failure at any step → reject with explicit error, log to audit.

### R2: Atomic Nonce Consumption

**R2.1** Each approval envelope has a unique `nonce` (UUID4) with a
UNIQUE constraint in SQLite.

**R2.2** State transition MUST be atomic:
```sql
UPDATE approval_envelopes
SET state = 'consumed', consumed_at = ?
WHERE nonce = ? AND state = 'pending' AND expires_at > ?
```
If affected rows == 0 → reject (already consumed, expired, or unknown).
No separate check-then-update.

**R2.3** A consumed nonce is NEVER reusable, regardless of outcome.
If execution fails midway, the nonce stays consumed. Human must re-approve.
(Rationale: partial side effects may have occurred.)

**R2.4** Expired envelopes MAY be pruned after `nonce_retention_period`
(default: 7 days). This is for storage hygiene only — expired envelopes
already fail the `state == 'pending'` check.

**R2.5** Config invariant: `nonce_retention_period >= approval_ttl + skew_margin`.
Enforced at startup. Default skew margin: 60 seconds.

### R3: Approval Expiry

**R3.1** Each envelope carries `issued_at` and `expires_at` (UTC).
Default TTL: 1 hour.

**R3.2** Expiry is checked atomically in the same UPDATE as nonce
consumption (R2.2). No separate clock check.

**R3.3** `APPROVAL_TTL_SECONDS` configurable via environment variable
(default: 3600).

### R4: Audit Log

**R4.1** Every approval event MUST be logged with:
- Timestamp (UTC ISO-8601)
- `envelope_id`
- `work_item_id`
- `plan_hash`
- `nonce`
- Decision per tool call (`approved` / `denied` + reason)
- Outcome: `executed` / `rejected:tampered` / `rejected:expired` /
  `rejected:replayed` / `rejected:mismatch` / `rejected:bijection`
- Computed plan hash at verification time (for drift detection)

**R4.2** Append-only during normal operation.

**R4.3** Hash-chained: each entry includes SHA-256 of
`canonical_json(previous_entry)`. Genesis entry uses
`sha256(b"autopoiesis:audit:genesis")`.

**R4.4** Canonical JSON for audit entries uses the same serialization
as R1.3.

**R4.5** Storage: JSONL at `$AUDIT_LOG_PATH` (default:
`data/audit/approvals.jsonl`).

**R4.6** Periodic anchor: the system MUST write the current chain head
hash to a separate file (`data/audit/anchor.json`) after every N entries
(default: 100) and at clean shutdown. This enables detecting truncation
attacks.

### R5: UI Integrity

**R5.1** The approval UI MUST render from the same canonical payload
used for hashing. No separate "display" transformation.

**R5.2** If display truncation is needed (long args), the full canonical
payload MUST still be what's hashed. The UI SHOULD indicate truncation
occurred (e.g. `[truncated, 2847 chars]`).

**R5.3** The plan hash SHOULD be displayed to the human (short hex prefix)
so they can cross-reference with the audit log.

### R6: Tool Classification

**R6.1** Tools MUST be classified as `side_effecting` or `read_only`.

**R6.2** Default: **side-effecting**. A tool is read-only ONLY if
explicitly marked. Unknown/unclassified tools require approval.

**R6.3** Classification is set at toolset registration time, not at
call time. No runtime reclassification.

### R7: Denial Semantics

**R7.1** Denial is per-tool-call. Denying one tool does NOT automatically
deny others in the same batch.

**R7.2** Denied tools are passed back to the agent as `ToolDenied` with
the human's denial message. The agent can adjust its plan.

**R7.3** If ALL tools in a batch are denied, the agent receives all
denials and can respond with text or a revised plan.

### R8: Future — Cryptographic Approval Tokens

> **Deferred.** Required when networked or multi-user.

**R8.1** Ed25519-signed tokens binding envelope_id, plan_hash, nonce,
expiry, and scope.

**R8.2** Standing approvals scoped to parent work item ID.

**R8.3** Key generated at first run, stored at `$APPROVAL_KEY_PATH`.

### R9: Future — Taint Propagation

> **Deferred.** Required when sub-agents spawn sub-agents.

**R9.1** Work items carry trust level from origin.

**R9.2** Agent-spawned items cannot escalate trust beyond parent.

---

## Implementation Phases

| Phase | Requirements | Trigger | Est. LOC |
|-------|-------------|---------|----------|
| **1: Integrity** | R1, R2, R3, R5, R6, R7 | Now | ~400 |
| **2: Audit** | R4 | After Phase 1 | ~200 |
| **3: Crypto** | R8 | When networked | ~300 |
| **4: Trust** | R9 | When sub-agents exist | ~200 |

## Non-Requirements

- **Encryption at rest** — local SQLite, same-host key = no value
- **Authentication** — single-user CLI, no login
- **Authorization levels** — single user = single role, no RBAC
- **Session binding** — deferred until networked (process-local is sufficient for CLI)

---

## Invariants

1. No side-effecting tool executes without a verified, unexpired,
   single-use human approval matched against a server-side envelope.
2. The approval is bound to the exact execution context shown to the
   human — any modification between display and execution invalidates it.
3. Nonce consumption is atomic — concurrent attempts are serialized by
   the database.
4. Every approval event is recorded in an append-only, hash-chained,
   canonically serialized audit log.
5. Unclassified tools are treated as side-effecting (default-deny).

---

## Open Questions (resolved)

| Question | Decision |
|----------|----------|
| Consume nonce on attempt or success? | On attempt. Partial side effects may have occurred. |
| Session binding? | Deferred — process-local is sufficient for CLI. |
| Deny semantics? | Per-call skip-and-continue. Agent gets `ToolDenied` per denied call. |
