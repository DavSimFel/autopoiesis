#!/usr/bin/env python3
"""Architecture drift detection — validates code against specs/architecture.yaml.

See: https://github.com/DavSimFel/autopoiesis/issues/156
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# YAML parser (minimal, no external deps)
# ---------------------------------------------------------------------------

YamlValue = str | int | list[str] | dict[str, Any]


def parse_yaml(path: Path) -> dict[str, YamlValue]:
    """Minimal YAML subset parser: supports scalars, lists, and flat dicts."""
    lines = path.read_text().splitlines()
    result: dict[str, YamlValue] = {}
    current_key: str | None = None
    for raw in lines:
        stripped = raw.split("#")[0].rstrip()
        if not stripped:
            continue
        indent = len(raw) - len(raw.lstrip())
        if indent == 0 and ":" in stripped:
            key, _, val = stripped.partition(":")
            val = val.strip()
            current_key = key.strip()
            if val:
                result[current_key] = _scalar(val)
            else:
                result[current_key] = {}
            continue
        if indent > 0 and current_key is not None:
            cur = result[current_key]
            if stripped.lstrip().startswith("- "):
                item = stripped.lstrip()[2:].strip()
                if not isinstance(cur, list):
                    result[current_key] = cur = []
                cur.append(_scalar_str(item))
            elif ":" in stripped:
                key, _, val = stripped.partition(":")
                val = val.strip()
                if not isinstance(cur, dict):
                    result[current_key] = cur = {}
                cur[key.strip()] = _parse_list_value(val)
    return result


def _scalar(v: str) -> str | int | list[str]:
    if v.startswith("[") and v.endswith("]"):
        return [x.strip() for x in v[1:-1].split(",") if x.strip()]
    if v.isdigit():
        return int(v)
    return v


def _scalar_str(v: str) -> str:
    """Parse a scalar, coercing to str for list items."""
    return v


def _parse_list_value(v: str) -> str | int | list[str]:
    if v.startswith("[") and v.endswith("]"):
        return [x.strip() for x in v[1:-1].split(",") if x.strip()]
    if v.isdigit():
        return int(v)
    return v


# ---------------------------------------------------------------------------
# Import extraction
# ---------------------------------------------------------------------------

SKIP_DIRS = {".venv", "benchmarks", "__pycache__", ".git", "node_modules"}
_SRC_LAYOUT_MIN_PARTS = 3
_SRC_LAYOUT_APPROVAL_PARTS = 4
_AUTOPOIESIS_APPROVAL_IMPORT_PARTS = 3


def find_py_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for p in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        files.append(p)
    return files


def extract_imports(filepath: Path) -> list[tuple[int, str]]:
    """Return (line_number, top-level module) for each import."""
    try:
        tree = ast.parse(filepath.read_text(), filename=str(filepath))
    except SyntaxError:
        return []
    results: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = _normalize_import_module(alias.name)
                if mod is not None:
                    results.append((node.lineno, mod))
        elif isinstance(node, ast.ImportFrom) and node.module:
            mod = _normalize_import_module(node.module)
            if mod is not None:
                results.append((node.lineno, mod))
    return results


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def module_of(filepath: Path, root: Path) -> str | None:
    """Return architecture module key for a source file path."""
    rel = filepath.relative_to(root)
    parts = rel.parts
    if len(parts) < _SRC_LAYOUT_MIN_PARTS:
        return None
    if parts[0] != "src" or parts[1] != "autopoiesis":
        return None
    if len(parts) == _SRC_LAYOUT_MIN_PARTS:
        return None  # src/autopoiesis/<root-module>.py (unconstrained)
    if parts[2] == "infra" and len(parts) >= _SRC_LAYOUT_APPROVAL_PARTS and parts[3] == "approval":
        return "approval"
    return parts[2]


def _normalize_import_module(module: str) -> str | None:
    """Normalize import string to architecture module keys.

    Returns ``None`` for external imports.
    """
    parts = module.split(".")
    if not parts:
        return None
    if parts[0] != "autopoiesis":
        return parts[0]
    if len(parts) == 1:
        return None
    if (
        parts[1] == "infra"
        and len(parts) >= _AUTOPOIESIS_APPROVAL_IMPORT_PARTS
        and parts[2] == "approval"
    ):
        return "approval"
    return parts[1]


def check_dependencies(
    files: list[Path],
    root: Path,
    deps: dict[str, str | int | list[str]],
    forbidden: list[str],
) -> list[str]:
    violations: list[str] = []
    # Parse forbidden rules
    forbidden_pairs: list[tuple[str, str]] = []
    for rule in forbidden:
        src, _, dst = rule.partition("->")
        forbidden_pairs.append((src.strip(), dst.strip()))

    internal_modules: set[str] = set(deps.keys())

    for fp in files:
        mod = module_of(fp, root)
        if mod is None or mod not in internal_modules:
            continue
        raw_allowed = deps.get(mod, [])
        allowed: set[str] = set(raw_allowed) if isinstance(raw_allowed, list) else set()
        allowed.add(mod)  # module can import from itself
        rel = fp.relative_to(root)

        for lineno, imported in extract_imports(fp):
            # Only check internal modules
            if imported not in internal_modules and imported not in {
                m for pair in forbidden_pairs for m in pair
            }:
                continue
            # Check forbidden
            for src, dst in forbidden_pairs:
                if mod == src and imported == dst:
                    violations.append(
                        f"{rel}:{lineno} imports '{imported}' — "
                        f"forbidden by architecture.yaml ({src} -> {dst})"
                    )
            # Check allowed deps
            if imported in internal_modules and imported not in allowed:
                violations.append(
                    f"{rel}:{lineno} imports '{imported}' — not in allowed dependencies for '{mod}'"
                )
    return violations


def check_max_lines(files: list[Path], root: Path, max_lines: int, exempt: list[str]) -> list[str]:
    violations: list[str] = []
    exempt_set = {Path(e) for e in exempt}
    for fp in files:
        rel = fp.relative_to(root)
        if rel in exempt_set:
            continue
        count = len(fp.read_text().splitlines())
        if count > max_lines:
            violations.append(f"{rel}: {count} lines (max {max_lines})")
    return violations


def check_patterns(files: list[Path], root: Path, patterns: list[str]) -> list[str]:
    violations: list[str] = []
    if not patterns:
        return violations
    for fp in files:
        rel = fp.relative_to(root)
        for i, line in enumerate(fp.read_text().splitlines(), 1):
            for pat in patterns:
                if pat in line:
                    violations.append(f"{rel}:{i} contains forbidden pattern '{pat}'")
    return violations


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _to_str_list(val: YamlValue) -> list[str]:
    """Coerce a YAML value to a list of strings."""
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        return [val]
    return []


def _to_dict(val: YamlValue) -> dict[str, str | int | list[str]]:
    """Coerce a YAML value to a dict."""
    if isinstance(val, dict):
        return val
    return {}


def _to_int(val: YamlValue, default: int) -> int:
    """Coerce a YAML value to an int."""
    if isinstance(val, int):
        return val
    return default


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    spec_path = root / "specs" / "architecture.yaml"
    if not spec_path.exists():
        print("ERROR: specs/architecture.yaml not found")
        return 1

    spec = parse_yaml(spec_path)
    deps = _to_dict(spec.get("dependencies", {}))
    forbidden = _to_str_list(spec.get("forbidden", []))
    max_lines = _to_int(spec.get("max_lines", 300), 300)
    exempt = _to_str_list(spec.get("max_lines_exempt", []))
    patterns = _to_str_list(spec.get("no_globals", []))

    # Only check source files (skip tests, scripts, benchmarks)
    all_files = find_py_files(root)
    source_files = [
        f
        for f in all_files
        if not any(p in f.relative_to(root).parts for p in ("tests", "scripts", "benchmarks"))
    ]

    violations: list[str] = []
    violations.extend(check_dependencies(source_files, root, deps, forbidden))
    violations.extend(check_max_lines(source_files, root, max_lines, exempt))
    violations.extend(check_patterns(source_files, root, patterns))

    if violations:
        print(f"Architecture violations ({len(violations)}):\n")
        for v in violations:
            print(f"  ✗ {v}")
        return 1

    print(f"✓ Architecture check passed ({len(source_files)} files scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
