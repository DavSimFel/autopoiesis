"""Key management and signing for approval envelopes."""

from __future__ import annotations

import base64
import getpass
import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict, cast

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat
from cryptography.hazmat.primitives.serialization import NoEncryption as NoPrivateKeyEncryption

from approval_types import SIGNED_OBJECT_CONTEXT, SignedDecision

_PRIVATE_FILE_VERSION = 1
_PUBLIC_FILE_VERSION = 1
_KEYRING_FILE_VERSION = 1
_KEY_AEAD_AD = b"autopoiesis:approval-key:v1"
_KEY_LENGTH = 32

_ARGON2_ITERATIONS = 3
_ARGON2_MEMORY_KIB = 64 * 1024
_ARGON2_LANES = 1
_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1


class KeyringEntry(TypedDict):
    """Stored key metadata used for verification key lookup."""

    key_id: str
    public_key_hex: str
    created_at: str
    retired_at: str | None


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
        key_dir = _resolve_path(key_dir_raw, base_dir)
        private_raw = os.getenv("APPROVAL_PRIVATE_KEY_PATH")
        public_raw = os.getenv("APPROVAL_PUBLIC_KEY_PATH")
        keyring_raw = os.getenv("APPROVAL_KEYRING_PATH")
        private_path = (
            _resolve_path(private_raw, base_dir) if private_raw else key_dir / "approval.key"
        )
        public_path = (
            _resolve_path(public_raw, base_dir) if public_raw else key_dir / "approval.pub"
        )
        keyring_path = (
            _resolve_path(keyring_raw, base_dir) if keyring_raw else key_dir / "keyring.json"
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
        if not passphrase:
            raise SystemExit("Approval signing key passphrase cannot be empty.")
        if self._paths.private_key_path.exists() or self._paths.public_key_path.exists():
            raise SystemExit("Approval key already exists.")
        self._generate_and_store_new_key(passphrase, retire_existing=False)

    def unlock(self, passphrase: str) -> None:
        if not passphrase:
            raise SystemExit("Approval signing key passphrase cannot be empty.")
        private_data = _read_json_file(self._paths.private_key_path)
        private_key = _decrypt_private_key(private_data, passphrase)
        active_public = self._load_active_public_key()
        derived_key_id = _compute_key_id(private_key.public_key())
        if active_public["key_id"] != derived_key_id:
            raise SystemExit("Approval key files are inconsistent: private/public key mismatch.")
        if _kdf_requires_upgrade(cast(dict[str, Any], private_data.get("kdf"))):
            _write_json_file(
                self._paths.private_key_path,
                _encrypt_private_key(private_key, passphrase),
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
        if not new_passphrase:
            raise SystemExit("New approval passphrase cannot be empty.")
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
            return _public_key_from_hex(active_data["public_key_hex"])
        for entry in self._load_keyring_entries():
            if entry["key_id"] == key_id:
                return _public_key_from_hex(entry["public_key_hex"])
        return None

    def signed_object(
        self, *, nonce: str, plan_hash: str, decisions: list[SignedDecision]
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
        public_key_hex = _public_key_hex(public_key)
        key_id = _compute_key_id(public_key)
        encrypted_private = _encrypt_private_key(private_key, passphrase)
        created_at = _utc_now_iso()
        active_public = {
            "version": _PUBLIC_FILE_VERSION,
            "key_id": key_id,
            "public_key_hex": public_key_hex,
            "created_at": created_at,
        }
        self._paths.key_dir.mkdir(parents=True, exist_ok=True)
        _write_json_file(self._paths.private_key_path, encrypted_private)
        _write_json_file(self._paths.public_key_path, active_public)
        _upsert_keyring_entry(
            path=self._paths.keyring_path,
            key_id=key_id,
            public_key_hex=public_key_hex,
            created_at=created_at,
            retire_existing=retire_existing,
        )
        self._private_key = private_key
        self._active_key_id = key_id

    def _load_active_public_key(self) -> dict[str, str]:
        public_data = _read_json_file(self._paths.public_key_path)
        key_id = public_data.get("key_id")
        public_key_hex = public_data.get("public_key_hex")
        if not isinstance(key_id, str) or not key_id:
            raise SystemExit("Approval public key file is invalid (key_id missing).")
        if not isinstance(public_key_hex, str) or not public_key_hex:
            raise SystemExit("Approval public key file is invalid (public_key_hex missing).")
        return {"key_id": key_id, "public_key_hex": public_key_hex}

    def _load_keyring_entries(self) -> list[KeyringEntry]:
        if not self._paths.keyring_path.exists():
            return []
        keyring_data = _read_json_file(self._paths.keyring_path)
        entries = keyring_data.get("keys")
        if not isinstance(entries, list):
            raise SystemExit("Approval keyring file is invalid.")
        normalized: list[KeyringEntry] = []
        entry_items = cast(list[Any], entries)
        for item in entry_items:
            if not isinstance(item, dict):
                raise SystemExit("Approval keyring entry is invalid.")
            entry = cast(dict[str, Any], item)
            key_id = entry.get("key_id")
            public_key_hex = entry.get("public_key_hex")
            created_at = entry.get("created_at")
            retired_at = entry.get("retired_at")
            if not isinstance(key_id, str) or not isinstance(public_key_hex, str):
                raise SystemExit("Approval keyring entry has invalid key material.")
            if not isinstance(created_at, str):
                raise SystemExit("Approval keyring entry has invalid created_at.")
            if retired_at is not None and not isinstance(retired_at, str):
                raise SystemExit("Approval keyring entry has invalid retired_at.")
            normalized.append(
                {
                    "key_id": key_id,
                    "public_key_hex": public_key_hex,
                    "created_at": created_at,
                    "retired_at": retired_at,
                }
            )
        return normalized


def _resolve_path(raw: str, base_dir: Path) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else (base_dir / path)


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Required file missing: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON file: {path}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"Invalid JSON object in file: {path}")
    return cast(dict[str, Any], data)


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def _encrypt_private_key(private_key: Ed25519PrivateKey, passphrase: str) -> dict[str, Any]:
    private_bytes = private_key.private_bytes(
        encoding=Encoding.Raw,
        format=PrivateFormat.Raw,
        encryption_algorithm=NoPrivateKeyEncryption(),
    )
    salt = os.urandom(16)
    encryption_key, kdf_config = _derive_encryption_key(passphrase.encode("utf-8"), salt)
    nonce = os.urandom(12)
    ciphertext = AESGCM(encryption_key).encrypt(nonce, private_bytes, _KEY_AEAD_AD)
    return {
        "version": _PRIVATE_FILE_VERSION,
        "created_at": _utc_now_iso(),
        "kdf": kdf_config,
        "aead": {"name": "aesgcm", "nonce_b64": _b64_encode(nonce)},
        "ciphertext_b64": _b64_encode(ciphertext),
    }


def _decrypt_private_key(payload: dict[str, Any], passphrase: str) -> Ed25519PrivateKey:
    kdf_data = payload.get("kdf")
    aead_data = payload.get("aead")
    ciphertext_b64 = payload.get("ciphertext_b64")
    if not isinstance(kdf_data, dict) or not isinstance(aead_data, dict) or not isinstance(
        ciphertext_b64, str
    ):
        raise SystemExit("Approval private key file is malformed.")
    aead_payload = cast(dict[str, Any], aead_data)
    nonce_b64 = aead_payload.get("nonce_b64")
    if not isinstance(nonce_b64, str):
        raise SystemExit("Approval private key file missing nonce.")
    encryption_key = _derive_encryption_key_from_config(
        passphrase=passphrase.encode("utf-8"),
        kdf_data=cast(dict[str, Any], kdf_data),
    )
    try:
        private_bytes = AESGCM(encryption_key).decrypt(
            _b64_decode(nonce_b64),
            _b64_decode(ciphertext_b64),
            _KEY_AEAD_AD,
        )
        return Ed25519PrivateKey.from_private_bytes(private_bytes)
    except (InvalidTag, ValueError) as exc:
        raise SystemExit("Invalid approval passphrase.") from exc


def _derive_encryption_key(passphrase: bytes, salt: bytes) -> tuple[bytes, dict[str, Any]]:
    argon2_key = _derive_argon2_key(passphrase, salt)
    if argon2_key is not None:
        return argon2_key, {
            "name": "argon2id",
            "salt_b64": _b64_encode(salt),
            "iterations": _ARGON2_ITERATIONS,
            "lanes": _ARGON2_LANES,
            "memory_kib": _ARGON2_MEMORY_KIB,
            "length": _KEY_LENGTH,
        }
    key = Scrypt(
        salt=salt,
        length=_KEY_LENGTH,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
    ).derive(passphrase)
    return key, {
        "name": "scrypt",
        "salt_b64": _b64_encode(salt),
        "n": _SCRYPT_N,
        "r": _SCRYPT_R,
        "p": _SCRYPT_P,
        "length": _KEY_LENGTH,
    }


def _derive_encryption_key_from_config(passphrase: bytes, kdf_data: dict[str, Any]) -> bytes:
    name = kdf_data.get("name")
    salt_b64 = kdf_data.get("salt_b64")
    if not isinstance(name, str) or not isinstance(salt_b64, str):
        raise SystemExit("Approval private key file has invalid KDF config.")
    salt = _b64_decode(salt_b64)
    if name == "argon2id":
        return _derive_argon2_key_from_config(passphrase, kdf_data, salt)
    if name == "scrypt":
        return Scrypt(
            salt=salt,
            length=int(kdf_data["length"]),
            n=int(kdf_data["n"]),
            r=int(kdf_data["r"]),
            p=int(kdf_data["p"]),
        ).derive(passphrase)
    raise SystemExit(f"Unsupported KDF in approval private key file: {name}")


def _derive_argon2_key(passphrase: bytes, salt: bytes) -> bytes | None:
    try:
        from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
    except ImportError:
        return None
    return Argon2id(
        salt=salt,
        length=_KEY_LENGTH,
        iterations=_ARGON2_ITERATIONS,
        lanes=_ARGON2_LANES,
        memory_cost=_ARGON2_MEMORY_KIB,
    ).derive(passphrase)


def _derive_argon2_key_from_config(
    passphrase: bytes, kdf_data: dict[str, Any], salt: bytes
) -> bytes:
    try:
        from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
    except ImportError as exc:
        raise SystemExit("Argon2id private key requires cryptography Argon2 support.") from exc
    return Argon2id(
        salt=salt,
        length=int(kdf_data["length"]),
        iterations=int(kdf_data["iterations"]),
        lanes=int(kdf_data["lanes"]),
        memory_cost=int(kdf_data["memory_kib"]),
    ).derive(passphrase)


def _kdf_requires_upgrade(kdf_data: dict[str, Any]) -> bool:
    name = kdf_data.get("name")
    if name == "argon2id":
        return (
            int(kdf_data.get("iterations", 0)) < _ARGON2_ITERATIONS
            or int(kdf_data.get("memory_kib", 0)) < _ARGON2_MEMORY_KIB
            or int(kdf_data.get("lanes", 0)) < _ARGON2_LANES
            or int(kdf_data.get("length", 0)) != _KEY_LENGTH
        )
    if name == "scrypt":
        return (
            int(kdf_data.get("n", 0)) < _SCRYPT_N
            or int(kdf_data.get("r", 0)) < _SCRYPT_R
            or int(kdf_data.get("p", 0)) < _SCRYPT_P
            or int(kdf_data.get("length", 0)) != _KEY_LENGTH
        )
    return True


def _compute_key_id(public_key: Ed25519PublicKey) -> str:
    return hashlib.sha256(
        public_key.public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)
    ).hexdigest()


def _public_key_hex(public_key: Ed25519PublicKey) -> str:
    return public_key.public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw).hex()


def _public_key_from_hex(public_key_hex: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))


def _upsert_keyring_entry(
    *, path: Path, key_id: str, public_key_hex: str, created_at: str, retire_existing: bool
) -> None:
    existing: dict[str, Any] = {"version": _KEYRING_FILE_VERSION, "keys": []}
    if path.exists():
        existing = _read_json_file(path)
    keys_raw = existing.get("keys")
    keys = cast(list[dict[str, Any]], keys_raw) if isinstance(keys_raw, list) else []
    if retire_existing:
        retired_at = _utc_now_iso()
        for item in keys:
            if item.get("retired_at") is None:
                item["retired_at"] = retired_at
    keys.append(
        {
            "key_id": key_id,
            "public_key_hex": public_key_hex,
            "created_at": created_at,
            "retired_at": None,
        }
    )
    _write_json_file(path, {"version": _KEYRING_FILE_VERSION, "keys": keys})


def _b64_encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64_decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"))


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
