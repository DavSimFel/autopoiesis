# ADR-004: Key Rotation & Historical Verification

## Status
Accepted — 2026-02-15

## Context
Ed25519 keypairs must be rotatable (compromised passphrase, periodic
hygiene). After rotation, historical audit entries and old envelope
signatures must remain verifiable for forensic purposes.

## Decision
- Each key is identified by `key_id`: SHA-256 fingerprint of the
  public key bytes (full 64-char hex digest).
- `key_id` is stored on every `ApprovalEnvelope` and every audit log
  entry.
- On rotation (`autopoiesis rotate-key`):
  1. Old public key + metadata archived to keyring
     (`$APPROVAL_KEYRING_PATH`, default:
     `$APPROVAL_KEY_DIR/keyring.json`)
  2. New keypair generated, encrypted with new passphrase
     at `$APPROVAL_PRIVATE_KEY_PATH` (default:
     `$APPROVAL_KEY_DIR/approval.key`)
  3. All pending envelopes invalidated (state → `expired`)
  4. Old private key securely discarded (zeroed)
- Keyring is append-only. Old public keys are never removed.
- Verification of historical entries: look up `key_id` in keyring,
  verify signature against that public key.

## Alternatives Considered
- **No keyring (discard old keys):** Historical signatures become
  unverifiable. Unacceptable for audit forensics.
- **Key wrapping (re-encrypt old private keys):** Unnecessary — only
  the public key is needed for verification. Keeping old private keys
  increases attack surface.
- **Certificate chain:** Overkill for single-user local system.

## Consequences
- Keyring file grows monotonically (one entry per rotation — negligible)
- Old signatures remain verifiable indefinitely
- Rotation invalidates all pending approvals (human must re-approve)
- `key_id` adds 64 hex chars to each envelope and audit entry
