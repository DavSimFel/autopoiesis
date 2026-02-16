"""Cryptographic helpers for approval signing keys."""

from __future__ import annotations

import base64
import hashlib
import os
from typing import Any, cast

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat
from cryptography.hazmat.primitives.serialization import NoEncryption as NoPrivateKeyEncryption

from approval.key_files import utc_now_iso

_PRIVATE_FILE_VERSION = 1
_KEY_AEAD_AD = b"autopoiesis:approval-key:v1"
_KEY_LENGTH = 32

_ARGON2_ITERATIONS = 3
_ARGON2_MEMORY_KIB = 64 * 1024
_ARGON2_LANES = 1
_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_MIN_PASSPHRASE_LENGTH = 12


def encrypt_private_key(private_key: Ed25519PrivateKey, passphrase: str) -> dict[str, Any]:
    """Encrypt a raw Ed25519 private key with passphrase-derived AEAD key."""
    private_bytes = private_key.private_bytes(
        encoding=Encoding.Raw,
        format=PrivateFormat.Raw,
        encryption_algorithm=NoPrivateKeyEncryption(),
    )
    salt = os.urandom(16)
    encryption_key, kdf_config = derive_encryption_key(passphrase.encode("utf-8"), salt)
    nonce = os.urandom(12)
    ciphertext = AESGCM(encryption_key).encrypt(nonce, private_bytes, _KEY_AEAD_AD)
    return {
        "version": _PRIVATE_FILE_VERSION,
        "created_at": utc_now_iso(),
        "kdf": kdf_config,
        "aead": {"name": "aesgcm", "nonce_b64": b64_encode(nonce)},
        "ciphertext_b64": b64_encode(ciphertext),
    }


def decrypt_private_key(payload: dict[str, Any], passphrase: str) -> Ed25519PrivateKey:
    """Decrypt private key payload and return an Ed25519 key object."""
    kdf_data = payload.get("kdf")
    aead_data = payload.get("aead")
    ciphertext_b64 = payload.get("ciphertext_b64")
    if (
        not isinstance(kdf_data, dict)
        or not isinstance(aead_data, dict)
        or not isinstance(ciphertext_b64, str)
    ):
        raise SystemExit("Approval private key file is malformed.")
    aead_payload = cast(dict[str, Any], aead_data)
    nonce_b64 = aead_payload.get("nonce_b64")
    if not isinstance(nonce_b64, str):
        raise SystemExit("Approval private key file missing nonce.")
    encryption_key = derive_encryption_key_from_config(
        passphrase=passphrase.encode("utf-8"),
        kdf_data=cast(dict[str, Any], kdf_data),
    )
    try:
        private_bytes = AESGCM(encryption_key).decrypt(
            b64_decode(nonce_b64),
            b64_decode(ciphertext_b64),
            _KEY_AEAD_AD,
        )
        return Ed25519PrivateKey.from_private_bytes(private_bytes)
    except (InvalidTag, ValueError) as exc:
        raise SystemExit("Invalid approval passphrase.") from exc


def derive_encryption_key(passphrase: bytes, salt: bytes) -> tuple[bytes, dict[str, Any]]:
    """Derive key material, preferring Argon2id when available."""
    argon2_key = derive_argon2_key(passphrase, salt)
    if argon2_key is not None:
        return argon2_key, {
            "name": "argon2id",
            "salt_b64": b64_encode(salt),
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
        "salt_b64": b64_encode(salt),
        "n": _SCRYPT_N,
        "r": _SCRYPT_R,
        "p": _SCRYPT_P,
        "length": _KEY_LENGTH,
    }


def derive_encryption_key_from_config(passphrase: bytes, kdf_data: dict[str, Any]) -> bytes:
    """Derive key material from persisted KDF configuration."""
    name = kdf_data.get("name")
    salt_b64 = kdf_data.get("salt_b64")
    if not isinstance(name, str) or not isinstance(salt_b64, str):
        raise SystemExit("Approval private key file has invalid KDF config.")
    salt = b64_decode(salt_b64)
    if name == "argon2id":
        return derive_argon2_key_from_config(passphrase, kdf_data, salt)
    if name == "scrypt":
        return Scrypt(
            salt=salt,
            length=int(kdf_data["length"]),
            n=int(kdf_data["n"]),
            r=int(kdf_data["r"]),
            p=int(kdf_data["p"]),
        ).derive(passphrase)
    raise SystemExit(f"Unsupported KDF in approval private key file: {name}")


def derive_argon2_key(passphrase: bytes, salt: bytes) -> bytes | None:
    """Best-effort Argon2id derivation; returns None when unavailable."""
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


def derive_argon2_key_from_config(
    passphrase: bytes,
    kdf_data: dict[str, Any],
    salt: bytes,
) -> bytes:
    """Strict Argon2id derivation from persisted config."""
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


def kdf_requires_upgrade(kdf_data: dict[str, Any]) -> bool:
    """Return True when persisted KDF params are weaker than current policy."""
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


def compute_key_id(public_key: Ed25519PublicKey) -> str:
    """Compute stable key id from raw public bytes."""
    return hashlib.sha256(
        public_key.public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)
    ).hexdigest()


def public_key_hex(public_key: Ed25519PublicKey) -> str:
    """Serialize public key bytes to hex."""
    return public_key.public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw).hex()


def public_key_from_hex(public_key_hex_value: str) -> Ed25519PublicKey:
    """Parse Ed25519 public key from hex."""
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex_value))


def validate_new_passphrase(passphrase: str, field_name: str) -> None:
    """Enforce minimum passphrase requirements for key encryption."""
    if not passphrase:
        raise SystemExit(f"{field_name} cannot be empty.")
    if len(passphrase) < _MIN_PASSPHRASE_LENGTH:
        raise SystemExit(f"{field_name} must be at least {_MIN_PASSPHRASE_LENGTH} characters.")


def b64_encode(value: bytes) -> str:
    """Base64 encode bytes to ASCII string."""
    return base64.b64encode(value).decode("ascii")


def b64_decode(value: str) -> bytes:
    """Base64 decode ASCII string to bytes."""
    return base64.b64decode(value.encode("ascii"))
