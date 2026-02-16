"""Key management and signing for approval envelopes."""

from __future__ import annotations

import getpass
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from approval_crypto import (
    compute_key_id,
    decrypt_private_key,
    encrypt_private_key,
    kdf_requires_upgrade,
    public_key_from_hex,
    public_key_hex,
    validate_new_passphrase,
)
from approval_key_files import (
    KeyringEntry,
    read_json_file,
    resolve_path,
    upsert_keyring_entry,
    utc_now_iso,
    write_json_file,
)
from approval_types import SIGNED_OBJECT_CONTEXT, SignedDecision

_PUBLIC_FILE_VERSION = 1


@dataclass(frozen=True)
class KeyPaths:
    """Filesystem locations for approval signing keys."""

    key_dir: Path
    private_key_path: Path
    public_key_path: Path
    keyring_path: Path


class ApprovalKeyManager:
    """Creates, unlocks, rotates, and verifies Ed25519 approval keys."""

    def __init__(self, paths: KeyPaths) -> None:
        self._paths = paths
        self._private_key: Ed25519PrivateKey | None = None
        self._active_key_id: str | None = None

    @classmethod
    def from_env(cls, *, base_dir: Path) -> ApprovalKeyManager:
        key_dir_raw = os.getenv("APPROVAL_KEY_DIR", "data/keys")
        key_dir = resolve_path(key_dir_raw, base_dir)
        private_raw = os.getenv("APPROVAL_PRIVATE_KEY_PATH")
        public_raw = os.getenv("APPROVAL_PUBLIC_KEY_PATH")
        keyring_raw = os.getenv("APPROVAL_KEYRING_PATH")
        private_path = (
            resolve_path(private_raw, base_dir) if private_raw else key_dir / "approval.key"
        )
        public_path = resolve_path(public_raw, base_dir) if public_raw else key_dir / "approval.pub"
        keyring_path = (
            resolve_path(keyring_raw, base_dir) if keyring_raw else key_dir / "keyring.json"
        )
        return cls(
            KeyPaths(
                key_dir=key_dir,
                private_key_path=private_path,
                public_key_path=public_path,
                keyring_path=keyring_path,
            )
        )

    def ensure_unlocked_interactive(self) -> None:
        if not self._paths.private_key_path.exists() or not self._paths.public_key_path.exists():
            self._create_initial_key_interactive()
        passphrase = getpass.getpass("Approval signing key passphrase: ")
        self.unlock(passphrase)

    def create_initial_key(self, passphrase: str) -> None:
        validate_new_passphrase(passphrase, "Approval signing key passphrase")
        if self._paths.private_key_path.exists() or self._paths.public_key_path.exists():
            raise SystemExit("Approval key already exists.")
        self._generate_and_store_new_key(passphrase, retire_existing=False)

    def unlock(self, passphrase: str) -> None:
        if not passphrase:
            raise SystemExit("Approval signing key passphrase cannot be empty.")
        private_data = read_json_file(self._paths.private_key_path)
        private_key = decrypt_private_key(private_data, passphrase)
        active_public = self._load_active_public_key()
        derived_key_id = compute_key_id(private_key.public_key())
        if active_public["key_id"] != derived_key_id:
            raise SystemExit("Approval key files are inconsistent: private/public key mismatch.")

        kdf_data = private_data.get("kdf")
        if isinstance(kdf_data, dict) and kdf_requires_upgrade(cast(dict[str, Any], kdf_data)):
            write_json_file(
                self._paths.private_key_path,
                encrypt_private_key(private_key, passphrase),
                file_mode=0o600,
            )

        self._private_key = private_key
        self._active_key_id = derived_key_id

    def rotate_key(
        self,
        *,
        current_passphrase: str,
        new_passphrase: str,
        expire_pending_envelopes: Callable[[], None],
    ) -> None:
        if not current_passphrase:
            raise SystemExit("Current approval passphrase cannot be empty.")
        validate_new_passphrase(new_passphrase, "New approval passphrase")
        self.unlock(current_passphrase)
        self._private_key = None
        self._active_key_id = None
        self._generate_and_store_new_key(new_passphrase, retire_existing=True)
        expire_pending_envelopes()

    def rotate_key_interactive(self, expire_pending_envelopes: Callable[[], None]) -> None:
        current_passphrase = getpass.getpass("Current approval passphrase: ")
        new_passphrase = getpass.getpass("New approval passphrase: ")
        confirm_passphrase = getpass.getpass("Confirm new approval passphrase: ")
        if new_passphrase != confirm_passphrase:
            raise SystemExit("Passphrases do not match.")
        self.rotate_key(
            current_passphrase=current_passphrase,
            new_passphrase=new_passphrase,
            expire_pending_envelopes=expire_pending_envelopes,
        )

    def current_key_id(self) -> str:
        if self._active_key_id is None:
            raise RuntimeError("Approval key is not unlocked.")
        return self._active_key_id

    def sign_payload(self, payload: str) -> str:
        if self._private_key is None:
            raise RuntimeError("Approval key is not unlocked.")
        signature = self._private_key.sign(payload.encode("utf-8"))
        return signature.hex()

    def verify_signature(self, key_id: str, payload: str, signature_hex: str) -> bool:
        public_key = self.resolve_public_key(key_id)
        if public_key is None:
            return False
        try:
            public_key.verify(bytes.fromhex(signature_hex), payload.encode("utf-8"))
            return True
        except (InvalidSignature, ValueError):
            return False

    def resolve_public_key(self, key_id: str) -> Ed25519PublicKey | None:
        active_data = self._load_active_public_key()
        if active_data["key_id"] == key_id:
            return public_key_from_hex(active_data["public_key_hex"])
        for entry in self._load_keyring_entries():
            if entry["key_id"] == key_id:
                return public_key_from_hex(entry["public_key_hex"])
        return None

    def signed_object(
        self,
        *,
        nonce: str,
        plan_hash: str,
        decisions: list[SignedDecision],
    ) -> dict[str, Any]:
        return {
            "ctx": SIGNED_OBJECT_CONTEXT,
            "nonce": nonce,
            "plan_hash": plan_hash,
            "key_id": self.current_key_id(),
            "decisions": decisions,
        }

    def _create_initial_key_interactive(self) -> None:
        print("No approval key found. Creating a new approval signing key.")
        passphrase = getpass.getpass("Create approval passphrase: ")
        confirm_passphrase = getpass.getpass("Confirm approval passphrase: ")
        if passphrase != confirm_passphrase:
            raise SystemExit("Passphrases do not match.")
        self.create_initial_key(passphrase)

    def _generate_and_store_new_key(self, passphrase: str, *, retire_existing: bool) -> None:
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()
        public_key_hex_value = public_key_hex(public_key)
        key_id = compute_key_id(public_key)
        encrypted_private = encrypt_private_key(private_key, passphrase)
        created_at = utc_now_iso()
        active_public = {
            "version": _PUBLIC_FILE_VERSION,
            "key_id": key_id,
            "public_key_hex": public_key_hex_value,
            "created_at": created_at,
        }
        self._paths.key_dir.mkdir(parents=True, exist_ok=True)
        write_json_file(self._paths.private_key_path, encrypted_private, file_mode=0o600)
        write_json_file(self._paths.public_key_path, active_public)
        upsert_keyring_entry(
            path=self._paths.keyring_path,
            key_id=key_id,
            public_key_hex=public_key_hex_value,
            created_at=created_at,
            retire_existing=retire_existing,
        )
        self._private_key = private_key
        self._active_key_id = key_id

    def _load_active_public_key(self) -> dict[str, str]:
        public_data = read_json_file(self._paths.public_key_path)
        key_id = public_data.get("key_id")
        public_key_hex_value = public_data.get("public_key_hex")
        if not isinstance(key_id, str) or not key_id:
            raise SystemExit("Approval public key file is invalid (key_id missing).")
        if not isinstance(public_key_hex_value, str) or not public_key_hex_value:
            raise SystemExit("Approval public key file is invalid (public_key_hex missing).")
        return {"key_id": key_id, "public_key_hex": public_key_hex_value}

    def _load_keyring_entries(self) -> list[KeyringEntry]:
        if not self._paths.keyring_path.exists():
            return []
        keyring_data = read_json_file(self._paths.keyring_path)
        entries = keyring_data.get("keys")
        if not isinstance(entries, list):
            raise SystemExit("Approval keyring file is invalid.")

        normalized: list[KeyringEntry] = []
        for item in cast(list[Any], entries):
            if not isinstance(item, dict):
                raise SystemExit("Approval keyring entry is invalid.")
            entry = cast(dict[str, Any], item)
            key_id = entry.get("key_id")
            public_key_hex_value = entry.get("public_key_hex")
            created_at = entry.get("created_at")
            retired_at = entry.get("retired_at")
            if not isinstance(key_id, str) or not isinstance(public_key_hex_value, str):
                raise SystemExit("Approval keyring entry has invalid key material.")
            if not isinstance(created_at, str):
                raise SystemExit("Approval keyring entry has invalid created_at.")
            if retired_at is not None and not isinstance(retired_at, str):
                raise SystemExit("Approval keyring entry has invalid retired_at.")
            normalized.append(
                {
                    "key_id": key_id,
                    "public_key_hex": public_key_hex_value,
                    "created_at": created_at,
                    "retired_at": retired_at,
                }
            )
        return normalized
