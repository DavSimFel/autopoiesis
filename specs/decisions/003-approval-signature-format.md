# ADR-003: Approval Signature Format

## Status
Accepted — 2026-02-15

## Context
The approval system needs cryptographic signatures to bind human
authorization to specific tool execution plans. The signature format
must be unambiguous, versioned, and resistant to cross-protocol misuse.

## Decision
Use a canonical signed JSON object with explicit domain separation:

```json
{
    "ctx": "autopoiesis.approval.v1",
    "nonce": "<uuid4 hex>",
    "plan_hash": "<sha256 hex>",
    "key_id": "<public key fingerprint>",
    "decisions": [
        {"tool_call_id": "...", "approved": true},
        ...
    ]
}
```

- **Domain separation:** `ctx` field prevents cross-protocol confusion.
  Verifiers MUST reject unknown context strings.
- **Versioning:** `v1` suffix enables future format migration without
  breaking existing signatures.
- **Canonical serialization:** `json.dumps(obj, sort_keys=True,
  separators=(',', ':'), ensure_ascii=True, allow_nan=False)`
- **Algorithm:** Ed25519 (RFC 8032). No algorithm negotiation.

## Alternatives Considered
- **Concatenation:** `sign(nonce + plan_hash + decisions)` — fragile,
  no domain separation, ambiguous field boundaries.
- **JWS/JWT:** Too heavy for local-only signing. Brings in library
  dependencies and complexity (algorithm headers, base64url encoding)
  that add no value for single-key local verification.
- **Protobuf:** Deterministic serialization is hard to guarantee
  across versions. JSON with sort_keys is sufficient and auditable.

## Consequences
- Signature verification requires JSON parsing (acceptable — payload is small)
- Future format changes require new `ctx` value and migration code
- All signed objects are human-readable in audit logs
