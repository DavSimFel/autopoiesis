"""Filesystem and serialization helpers for approval key material."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict, cast
from uuid import uuid4

_KEYRING_FILE_VERSION = 1


class KeyringEntry(TypedDict):
    """Stored key metadata used for verification key lookup."""

    key_id: str
    public_key_hex: str
    created_at: str
    retired_at: str | None


def resolve_path(raw: str, base_dir: Path) -> Path:
    """Resolve absolute paths directly and relative paths from a base directory."""
    path = Path(raw)
    return path if path.is_absolute() else (base_dir / path)


def read_json_file(path: Path) -> dict[str, Any]:
    """Read and validate a JSON object from disk."""
    if not path.exists():
        raise SystemExit(f"Required file missing: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON file: {path}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"Invalid JSON object in file: {path}")
    return cast(dict[str, Any], data)


def write_json_file(path: Path, payload: dict[str, Any], *, file_mode: int = 0o644) -> None:
    """Atomically write JSON content to disk with explicit mode bits."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    encoded = json.dumps(payload, indent=2, ensure_ascii=True).encode("utf-8")
    fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, file_mode)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, file_mode)
        os.replace(temp_path, path)
        os.chmod(path, file_mode)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def upsert_keyring_entry(
    *,
    path: Path,
    key_id: str,
    public_key_hex: str,
    created_at: str,
    retire_existing: bool,
) -> None:
    """Add a keyring entry and optionally retire currently active entries."""
    existing: dict[str, Any] = {"version": _KEYRING_FILE_VERSION, "keys": []}
    if path.exists():
        existing = read_json_file(path)
    keys_raw = existing.get("keys")
    keys = cast(list[dict[str, Any]], keys_raw) if isinstance(keys_raw, list) else []
    if retire_existing:
        retired_at = utc_now_iso()
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
    write_json_file(path, {"version": _KEYRING_FILE_VERSION, "keys": keys})


def utc_now_iso() -> str:
    """Return an ISO8601 UTC timestamp string."""
    return datetime.now(UTC).isoformat()
