"""Allowlist-based path validation for agent workspace file operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


def _dedupe_paths(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    deduped: list[Path] = []
    for path in paths:
        if path not in deduped:
            deduped.append(path)
    return tuple(deduped)


@dataclass(frozen=True)
class PathValidator:
    """Validate paths against an explicit allowlist rooted in one workspace."""

    workspace_root: Path
    allowed_roots: tuple[Path, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        workspace = self.workspace_root.expanduser().resolve()
        extras = tuple(path.expanduser().resolve() for path in self.allowed_roots)
        normalized = _dedupe_paths((workspace, *extras))
        object.__setattr__(self, "workspace_root", workspace)
        object.__setattr__(self, "allowed_roots", normalized)

    def resolve_path(self, path: str | Path, *, base_dir: Path | None = None) -> Path:
        """Resolve *path* and reject values that escape the allowlist."""
        candidate = Path(path).expanduser()
        base = self.workspace_root if base_dir is None else self._resolve_base_dir(base_dir)
        resolved = candidate.resolve() if candidate.is_absolute() else (base / candidate).resolve()
        if not self.is_allowed(resolved):
            raise ValueError(f"Path escapes allowed roots: {path}")
        return resolved

    def ensure_file(self, path: str | Path, *, base_dir: Path | None = None) -> Path:
        """Resolve *path* and require it to be an existing file."""
        resolved = self.resolve_path(path, base_dir=base_dir)
        if not resolved.is_file():
            raise ValueError(f"Path is not a file: {path}")
        return resolved

    def ensure_directory(self, path: str | Path, *, base_dir: Path | None = None) -> Path:
        """Resolve *path* and require it to be an existing directory."""
        resolved = self.resolve_path(path, base_dir=base_dir)
        if not resolved.is_dir():
            raise ValueError(f"Path is not a directory: {path}")
        return resolved

    def is_allowed(self, path: Path) -> bool:
        """Return whether *path* stays under one of the allowlist roots."""
        resolved = path.expanduser().resolve()
        return any(resolved.is_relative_to(root) for root in self.allowed_roots)

    def _resolve_base_dir(self, base_dir: Path) -> Path:
        resolved = base_dir.expanduser().resolve()
        if not self.is_allowed(resolved):
            raise ValueError(f"Base directory escapes allowed roots: {base_dir}")
        return resolved
