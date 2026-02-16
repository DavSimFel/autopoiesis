# Security Model

## Purpose

Define the trust boundaries, approval guarantees, and integrity properties
for autopoiesis agent execution. No tool with side effects executes without
cryptographically signed, single-use, unexpired human authorization bound
to the exact execution context shown to the human.

## Status
- **Last updated:** 2026-02-16 (Phase 1 implemented: R1-R7, R9-R11)
- **Revision:** v3
- **Threat model:** Single-user CLI today, networked multi-surface later

---

## Threat Model

### What we're protecting against

| Threat | Vector | Current exposure |
|--------|--------|-----------------|
| **Plan tampering** | Modify plan between approval display and execution | Yes — no binding |
| **Approval replay** | Reuse approval for different/repeated action | Yes — no nonce |
| **Approval injection** | Craft `deferred_tool_results_json` with `approved: true` | Yes — trusted without verification |
| **Unauthorized caller** | Any process with the nonce can authorize execution | Yes — bearer-token style |
| **Context drift** | Same tool calls but different execution context | Yes — nothing bound |
| **Race condition** | Concurrent execution before nonce is marked consumed | Yes — no atomicity |
| **Scope escalation** | Approval for narrow action used to authorize broader one | Yes — no scope model |
| **Audit tampering** | Rewrite audit log after the fact | Yes — no log exists |
| **UI mismatch** | Human sees truncated/modified version of what's hashed | Yes — display truncates args |

### What we're NOT protecting against (yet)

- Compromised host (attacker has local code execution → game over)
- Model-level prompt injection (out of scope — handled by tool scoping)
- Network MITM (not networked yet)

---

## Core Concepts

### Identity Keypair

An Ed25519 keypair is the root of trust for human identity.

- **Generated once** at setup (`autopoiesis init` or first run)
- **Key directory** at `$APPROVAL_KEY_DIR` (default: `data/keys`)
- **Private key** encrypted with a user-chosen passphrase at
  `$APPROVAL_PRIVATE_KEY_PATH` (default:
  `$APPROVAL_KEY_DIR/approval.key`)
- **Public key** at `$APPROVAL_PUBLIC_KEY_PATH` (default:
  `$APPROVAL_KEY_DIR/approval.pub`)
- **Keyring** for historical public keys at `$APPROVAL_KEYRING_PATH`
  (default: `$APPROVAL_KEY_DIR/keyring.json`)
- **Session unlock:** CLI startup prompts for passphrase, decrypts private
  key, holds it in memory for the process lifetime
- **Future unlock mechanisms:** WebAuthn/fingerprint in PWA, hardware
  token — these are alternative key-unlock methods, not a new architecture

The private key never leaves the process. The passphrase never touches disk.

### Approval Envelope

The **ApprovalEnvelope** is the central trust anchor. It is:
- Created server-side before the human sees anything
- Persisted in SQLite (same DB as DBOS)
- Immutable after creation
- The ONLY source of truth for verification at execution time

### Approval Scope

The **ApprovalScope** defines what an approval authorizes. It is:
- Part of the envelope (hashed and signed)
- Extensible via new fields
- Default-deny per field: `None` means "not authorized"
- Narrowing only: child scopes can restrict, never widen

---

## Requirements

### R1: Identity & Signing

**R1.1** At setup, the system MUST generate an Ed25519 keypair.
The private key MUST be encrypted with a user-provided passphrase
using Argon2id (minimum: 3 iterations, 64 MiB memory, 1 parallelism)
or scrypt (minimum: N=2^15, r=8, p=1) as fallback. KDF parameters
MUST be stored alongside the encrypted key. If future OWASP minimums
increase, the system MUST re-derive on next unlock with upgraded params.

**R1.2** At CLI startup, the system MUST prompt for the passphrase,
decrypt the private key, and hold it in memory. Failed decryption
→ exit. No fallback to unsigned mode.

**R1.3** The system MUST NOT start agent execution without an unlocked
signing key. This is the "proof of human" for Phase 1.

**R1.4** Key rotation: the system MUST support re-keying via
`python chat.py rotate-key` by generating a NEW keypair, encrypting the
new private key with the new passphrase, and switching active signing
to the new `key_id`. Outstanding pending envelopes are invalidated on
rotation.

**R1.5** Keyring retention: on rotation, the old public key MUST be
retained in `$APPROVAL_KEYRING_PATH` with its `key_id`, `created_at`,
and `retired_at`. This enables
verification of historical audit entries and old envelope signatures.
The old private key is securely discarded.

### R2: Approval Scope (extensible authorization)

**R2.1** Every approval envelope contains an `ApprovalScope` that
defines exactly what is authorized:

| Field | Type | Phase | Description |
|-------|------|-------|-------------|
| `work_item_id` | str | 1 | The specific work item |
| `scope_schema_version` | int | 1 | Versioned scope schema (starts at 1) |
| `tool_call_ids` | list[str] | 1 | Ordered tool calls authorized |
| `workspace_root` | str | 1 | Resolved absolute workspace path |
| `agent_name` | str | 1 | Agent that produced the request |
| `toolset_mode` | str | 1 | e.g. `require_write_approval` |
| `allowed_paths` | list[str] \| None | Future | Restrict file ops to these paths |
| `max_cost_cents` | int \| None | Future | Budget cap per approval |
| `child_scope` | bool \| None | Future | Allow spawned sub-tasks to inherit |
| `parent_envelope_id` | str \| None | Future | Chain to parent approval |
| `session_id` | str \| None | Future | Bind to specific process/session |
| `scope_tags` | list[str] \| None | Future | Arbitrary policy labels |

**R2.2** Default-deny per field: any field set to `None` means that
capability is not authorized. Adding a new field to the schema MUST
NOT grant permissions to existing envelopes. To enforce this:
- The scope schema MUST be versioned via `scope_schema_version`
- Canonicalization for each schema version MUST materialize every
  defined field (including explicit `None` defaults)
- Verification MUST parse scope according to the envelope's schema
  version, and reject unsupported versions (`scope_schema_unsupported`)

**R2.3** Scope narrowing rule: if a child scope is derived from a
parent (future: `child_scope=True`), every field in the child MUST be
equal to or more restrictive than the parent. Validation at creation
time, not execution time.

**R2.4** The scope object is included in the plan hash (R3) and the
signature (R4). Any scope modification invalidates both.

### R3: Approval Envelope (server-side trust anchor)

**R3.1** When the agent produces `DeferredToolRequests`, the system MUST
create and persist an `ApprovalEnvelope` BEFORE presenting anything to
the human. Fields:

| Field | Type | Description |
|-------|------|-------------|
| `envelope_id` | UUID4 | Primary key |
| `nonce` | UUID4 | Single-use token (UNIQUE constraint) |
| `scope` | ApprovalScope | What this approval authorizes |
| `tool_calls` | list[ToolCall] | Ordered immutable tool call payload |
| `plan_hash` | str | SHA-256 of canonical scope + tool args |
| `key_id` | str | SHA-256 fingerprint (full 64 hex chars) |
| `signature_hex` | str \| null | Ed25519 signature after approval |
| `state` | enum | `pending` → `consumed` / `rejected` / `expired` |
| `issued_at` | datetime(UTC) | Creation time |
| `expires_at` | datetime(UTC) | `issued_at + APPROVAL_TTL_SECONDS` |

**R3.2** The `plan_hash` MUST cover the **full scope object** plus the
tool call arguments:

```
canonical_payload = {
    "scope": <ApprovalScope as dict>,
    "tool_calls": [
        {"tool_call_id": ..., "tool_name": ..., "args": ...},
        ...  # preserved order
    ]
}
```

**R3.3** The envelope MUST record `key_id` — SHA-256 fingerprint of
the signing public key (full 64 hex chars). This enables historical
verification after key rotation.

**R3.4** Canonical serialization:
```python
json.dumps(payload, sort_keys=True, separators=(',', ':'),
           ensure_ascii=True, allow_nan=False)
```
→ UTF-8 bytes → SHA-256 hex. Tool args MUST be strict JSON types
(no NaN, no Infinity, no undefined). Violation → reject at envelope
creation time.

### R4: Cryptographic Signing

**R4.1** When the human approves, the system MUST sign a canonical
**signed object** with the unlocked Ed25519 private key:

```python
signed_object = {
    "ctx": "autopoiesis.approval.v1",
    "nonce": "<uuid4 hex>",
    "plan_hash": "<sha256 hex>",
    "key_id": "<public key fingerprint>",
    "decisions": [
        {"tool_call_id": "...", "approved": true/false},
        ...  # preserved order
    ]
}
```

The signed payload is `canonical_json(signed_object)` (same
serialization as R3.4). The `ctx` field provides domain separation
and versioning — verifiers MUST reject unknown context strings.
`signed_object.key_id` MUST exactly match `envelope.key_id`.

**R4.2** The signature MUST be stored on the envelope before submission
for execution.

**R4.3** At verification time, signature check is the FIRST step — before
any state mutation. Invalid signature → reject, envelope state unchanged,
nonce not consumed.

### R5: Verification Order

**R5.1** Verification MUST follow this exact order. Failure at any step
→ reject with explicit error code, log to audit, stop.

```
1. Look up envelope by nonce
   → fail: unknown_nonce

2. Resolve verification key by `envelope.key_id` (active key or
   historical keyring entry), then verify signature against that key.
   Also verify `signed_object.key_id == envelope.key_id`.
   → fail: invalid_signature (no state mutation)
   → fail: unknown_key_id (no state mutation)

3. Recompute plan_hash from LIVE execution context (current
   workspace_root, agent_name, toolset_mode) + stored tool calls.
   If `scope_schema_version` is unsupported, reject.
   → fail: scope_schema_unsupported (no state mutation)
   Compare against stored plan_hash.
   → fail: context_drift (no state mutation)

4. Verify strict bijection: submitted decisions map 1:1 to
   scope.tool_call_ids, same order, no missing, no extra
   → fail: bijection_mismatch (no state mutation)

5. Atomic nonce consumption (see R6):
   UPDATE ... WHERE nonce=? AND state='pending' AND expires_at > now
   → fail (0 rows): expired_or_consumed

6. Execute approved tool calls, pass denied as ToolDenied
```

**R5.2** Steps 1-4 are read-only. Only step 5 mutates state. This
ensures tampered/unsigned/malformed submissions cannot burn valid
approvals (no DoS via nonce exhaustion).

### R6: Atomic Nonce Consumption

**R6.1** Each approval envelope has a unique `nonce` (UUID4) with a
UNIQUE constraint in SQLite.

**R6.2** State transition MUST be atomic:
```sql
UPDATE approval_envelopes
SET state = 'consumed', consumed_at = ?
WHERE nonce = ? AND state = 'pending' AND expires_at > ?
```
If affected rows == 0 → reject. No separate check-then-update.

**R6.3** A consumed nonce is NEVER reusable, regardless of outcome.
If execution fails midway, the nonce stays consumed. Human must
re-approve. (Rationale: partial side effects may have occurred.)

**R6.4** Expired envelopes MAY be pruned after `nonce_retention_period`
(default: 7 days). Storage hygiene only — expired envelopes already
fail the `state == 'pending'` check.

**R6.5** Config invariant enforced at startup:
`nonce_retention_period >= approval_ttl + skew_margin`.
Default skew margin: 60 seconds.

### R7: Approval Expiry

**R7.1** Each envelope carries `issued_at` and `expires_at` (UTC).
Default TTL: 1 hour.

**R7.2** Expiry is checked atomically in the same UPDATE as nonce
consumption (R6.2). No separate clock check.

**R7.3** `APPROVAL_TTL_SECONDS` configurable via environment variable
(default: 3600).

### R8: Audit Log

**R8.1** Every approval event MUST be logged with:
- Timestamp (UTC ISO-8601)
- `envelope_id`
- `work_item_id`
- `plan_hash`
- `nonce`
- Decision per tool call (`approved` / `denied` + reason)
- Outcome: `executed` / `rejected:invalid_signature` /
  `rejected:unknown_key_id` /
  `rejected:context_drift` / `rejected:expired_or_consumed` /
  `rejected:bijection_mismatch` / `rejected:unknown_nonce` /
  `rejected:scope_schema_unsupported` / `rejected:audit_write_failed`
- Computed plan hash at verification time (for drift detection)
- `key_id` (public key fingerprint used for signing)
- Signature (hex)

For `rejected:unknown_nonce`, `envelope_id`, `work_item_id`,
`plan_hash`, and `key_id` are `null` (nonce still recorded).

**R8.2** Append-only during normal operation. Single-writer policy:
only the main process writes to the audit log. No concurrent writers.

**R8.3** Write durability: each entry MUST be flushed (`fsync`) before
the corresponding tool execution begins. Crash between flush and
execution → audit shows approval but no execution (safe: re-approval
needed due to consumed nonce).

**R8.4** Fail-closed: if the audit append or fsync fails (I/O error,
disk full, permissions), the system MUST reject tool execution. An
unauditable approval MUST NOT proceed. The failure is logged to stderr
with outcome code `rejected:audit_write_failed`, and the nonce remains
consumed (human must re-approve after fixing the audit log).

**R8.5** Hash-chained: each entry includes SHA-256 of
`canonical_json(previous_entry)`. Genesis entry uses
`sha256(b"autopoiesis:audit:genesis")`. Canonical JSON uses the same
serialization as R3.4.

**R8.6** Storage: JSONL at `$AUDIT_LOG_PATH` (default:
`data/audit/approvals.jsonl`).

**R8.7** Periodic anchor: write current chain head hash to
`data/audit/anchor.json` after every N entries (default: 100)
and at clean shutdown.

**R8.8** Tamper-detection scope: the hash chain detects accidental
corruption and casual tampering. It does NOT protect against an
attacker with write access to both the log and anchor file (same
trust domain). External anchoring (e.g. posting chain head to a
remote service) is a future enhancement for networked deployments.

### R9: UI Integrity

**R9.1** The approval UI MUST render tool calls from the same canonical
payload used for hashing. No separate "display" transformation.

**R9.2** Long arguments: the UI MUST display the full argument value.
If the terminal cannot display it usefully, the UI MUST offer an
expand/confirm flow (e.g. `[2847 chars — show full? Y/n]`) BEFORE
the human can approve. Approving without seeing full args is not
permitted.

**R9.3** The plan hash (short hex prefix, 8 chars) MUST be displayed
alongside the approval prompt so the human can cross-reference with
the audit log.

### R10: Tool Classification

**R10.1** Tools MUST be classified as `side_effecting` or `read_only`.

**R10.2** Default: **side-effecting**. A tool is read-only ONLY if
explicitly marked at toolset registration time. Unknown/unclassified
tools require approval.

**R10.3** Classification is immutable after registration. No runtime
reclassification.

### R11: Denial Semantics

**R11.1** Denial is per-tool-call. Denying one tool does NOT
automatically deny others in the same batch.

**R11.2** Denied tools are passed back to the agent as `ToolDenied`
with the human's denial message when provided. If no reason is
provided, the default denial text is used. The agent can adjust its plan.

**R11.3** If ALL tools in a batch are denied, the agent receives all
denials and can respond with text or a revised plan.

### R12: Future — Standing Approvals

> **Deferred.** Required when sub-agents can spawn sub-tasks.

**R12.1** A standing approval is an envelope with `child_scope=True`
that authorizes spawned sub-tasks sharing the same `parent_envelope_id`.

**R12.2** Child envelopes MUST satisfy scope narrowing (R2.3).

**R12.3** Standing approvals have a separate TTL
(`STANDING_APPROVAL_TTL_SECONDS`, default: 4 hours) and a
`max_children` limit (default: 10).

### R13: Future — Taint Propagation

> **Deferred.** Required when sub-agents spawn sub-agents.

**R13.1** Work items carry a trust level derived from origin
(human-initiated vs. agent-spawned).

**R13.2** Agent-spawned work items MUST NOT escalate trust beyond
their parent.

---

## Implementation Phases

| Phase | Requirements | Trigger | Est. LOC |
|-------|-------------|---------|----------|
| **1: Integrity + Signing** | R1-R7, R9-R11 | Now | ~500 |
| **2: Audit** | R8 | After Phase 1 | ~200 |
| **3: Standing Approvals** | R12 | When sub-agents exist | ~200 |
| **4: Taint** | R13 | When sub-agents chain | ~200 |

## Non-Requirements

- **Encryption at rest** — local SQLite, same-host key = no value
- **Authentication** — single-user CLI; passphrase unlocks signing key,
  not a login session
- **Authorization levels** — single user = single role, no RBAC
- **Network verification** — deferred; local signing is sufficient for CLI
- **External audit anchoring** — deferred; local chain + anchor file
  matches current threat model

---

## Invariants

### Phase 1 (Integrity + Signing)

1. No side-effecting tool executes without a cryptographically signed,
   verified, unexpired, single-use human approval matched against a
   server-side envelope.
2. The approval is bound to the exact execution scope and tool arguments
   shown to the human — any modification invalidates the signature and
   plan hash.
3. Verification is read-only until the final atomic nonce consumption.
   Invalid submissions cannot burn valid approvals.
4. Nonce consumption is atomic — concurrent attempts are serialized by
   the database.
5. Unclassified tools are treated as side-effecting (default-deny).
6. New scope fields default to `None` (not authorized). Schema extension
   cannot accidentally grant permissions to existing envelopes.
7. Context drift is detected: plan hash is recomputed from live execution
   context at verification time.

### Phase 2 (Audit) — additional invariant

8. Every approval event is recorded in an append-only, hash-chained,
   canonically serialized audit log with single-writer semantics and
   fsync-before-execute durability.

---

## Open Questions (resolved)

| Question | Decision |
|----------|----------|
| How to bind approval to human? | Ed25519 keypair, passphrase-unlocked at CLI start. |
| Consume nonce on attempt or success? | On attempt. Partial side effects may have occurred. |
| Can tampered submissions burn nonces? | No. Signature + hash checks are read-only (steps 1-4). Nonce consumed only at step 5. |
| Session binding? | Deferred — `session_id` field exists in scope but is `None` (not enforced) in Phase 1. |
| Deny semantics? | Per-call skip-and-continue. Agent gets `ToolDenied` per denied call. |
| Scope extensibility? | Default-deny per field. New fields = `None` = not authorized. Hash covers full scope. |
| Audit tamper-resistance? | Honest about scope: detects accidental/casual tampering. Not attacker-with-file-write. |
| NaN/Infinity in JSON? | `allow_nan=False`. Strict JSON types enforced at envelope creation. |
| Concurrent audit writes? | Single-writer policy. No file locking needed. |
| Truncated UI? | Not allowed. Full args shown or expand-and-confirm before approval. |
