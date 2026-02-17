#!/usr/bin/env python3
"""Generate a human-readable change narrative for a PR from git diff stats."""

import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass

# Modules considered high-risk when modified
HIGH_RISK_PATHS = ("infra/approval/", "server/", "approval/")
# Paths that are low-risk by themselves
LOW_RISK_PATHS = ("tests/", "docs/", "specs/", "benchmarks/", ".md")

_EXPECTED_NUMSTAT_COLS = 3


@dataclass
class FileStat:
    """Per-file diff statistics."""

    path: str
    added: int
    removed: int


def run(cmd: str) -> str:
    """Run a shell command and return stripped stdout."""
    return subprocess.check_output(cmd, shell=True, text=True).strip()


def get_diff_stats(base: str) -> list[FileStat]:
    """Get per-file diff stats: additions, deletions, filepath."""
    raw = run(f"git diff --numstat {base}...HEAD")
    files: list[FileStat] = []
    for line in raw.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != _EXPECTED_NUMSTAT_COLS:
            continue
        added_s, removed_s, path = parts
        files.append(
            FileStat(
                path=path,
                added=int(added_s) if added_s != "-" else 0,
                removed=int(removed_s) if removed_s != "-" else 0,
            )
        )
    return files


def classify_module(path: str) -> str:
    """Extract the top-level module/directory from a file path."""
    if "/" in path:
        return path.split("/")[0]
    return "(root)"


def _is_low_risk_path(path: str) -> bool:
    return any(path.startswith(lr) or path.endswith(lr) for lr in LOW_RISK_PATHS)


def _detect_new_imports(module_names: set[str]) -> list[str]:
    """Detect new external imports in the diff."""
    try:
        diff_text = run("git diff HEAD~1...HEAD -- '*.py' 2>/dev/null || true")
        return [
            line
            for line in diff_text.splitlines()
            if line.startswith("+")
            and not line.startswith("+++")
            and ("import " in line)
            and not any(
                line.strip().startswith(f"+from {m}") or line.strip().startswith(f"+import {m}")
                for m in module_names
            )
        ]
    except Exception:
        return []


def _check_high_risk(paths: list[str]) -> tuple[str, str] | None:
    """Return high-risk result if any path matches, else None."""
    for p in paths:
        for hr in HIGH_RISK_PATHS:
            if p.startswith(hr):
                return (
                    "\U0001f534 **High risk**",
                    f"Changes to `{hr.rstrip('/')}` \u2014 review carefully",
                )
    return None


def _assess_risk_level(
    files: list[FileStat],
    modules: dict[str, list[FileStat]],
) -> tuple[str, str]:
    """Return (emoji+level, explanation)."""
    paths = [f.path for f in files]
    total_added = sum(f.added for f in files)
    total_removed = sum(f.removed for f in files)

    high_risk = _check_high_risk(paths)
    if high_risk is not None:
        return high_risk

    new_imports = _detect_new_imports(set(modules.keys()))
    all_low = all(_is_low_risk_path(p) for p in paths)

    # Low-risk: only tests/docs or net removal without new deps
    if all_low or (total_removed > total_added and not new_imports):
        reason = (
            "Only tests/docs/specs changed" if all_low else "Net code removal, no new dependencies"
        )
        return "\U0001f7e2 **Low risk**", reason

    if new_imports:
        return "\U0001f7e1 **Medium risk**", "New external imports detected"

    if total_added > total_removed * 2:
        return "\U0001f7e1 **Medium risk**", "Significant new code added"

    # Check if modifying existing behavior
    non_test_files = [f for f in files if not _is_low_risk_path(f.path)]
    if non_test_files:
        return "\U0001f7e1 **Medium risk**", "Modifies existing behavior"

    return "\U0001f7e2 **Low risk**", "Minor changes"


def build_narrative(base: str) -> str:
    """Build a markdown change narrative from diff against *base*."""
    files = get_diff_stats(base)
    if not files:
        return "## \U0001f4cb Change Narrative\n\nNo changes detected."

    modules: dict[str, list[FileStat]] = defaultdict(list)
    for f in files:
        modules[classify_module(f.path)].append(f)

    total_added = sum(f.added for f in files)
    total_removed = sum(f.removed for f in files)
    net = total_added - total_removed

    risk_level, risk_reason = _assess_risk_level(files, modules)

    lines = ["## \U0001f4cb Change Narrative", ""]

    lines.append("### What changed")
    for mod in sorted(modules):
        mod_files = modules[mod]
        added = sum(f.added for f in mod_files)
        removed = sum(f.removed for f in mod_files)
        count = len(mod_files)
        suffix = "s" if count != 1 else ""
        lines.append(f"- **{mod}/**: {count} file{suffix} changed (+{added}/-{removed} lines)")
    lines.append("")

    lines.append("### Risk assessment")
    lines.append(f"{risk_level} \u2014 {risk_reason}")
    lines.append("")

    lines.append("### Module impact")
    lines.append("| Module | Files changed | Lines \u00b1 |")
    lines.append("|--------|--------------|---------|")
    for mod in sorted(modules):
        mod_files = modules[mod]
        added = sum(f.added for f in mod_files)
        removed = sum(f.removed for f in mod_files)
        lines.append(f"| {mod} | {len(mod_files)} | +{added} -{removed} |")
    lines.append("")

    lines.append("### Stats")
    lines.append(f"- **Files:** {len(files)} changed")
    lines.append(f"- **Lines:** +{total_added} -{total_removed}")
    if net < 0:
        lines.append(f"- **Net:** {net} lines (code reduction \u2713)")
    elif net == 0:
        lines.append("- **Net:** 0 lines (no size change)")
    else:
        lines.append(f"- **Net:** +{net} lines")

    return "\n".join(lines)


if __name__ == "__main__":
    base_ref = sys.argv[1] if len(sys.argv) > 1 else "origin/main"
    print(build_narrative(base_ref))
