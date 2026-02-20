#!/usr/bin/env python3
"""RTM (Requirements Traceability Matrix) checker for autopoiesis.

Parses ``## Verification Criteria`` tables from spec markdown files and
``@pytest.mark.verifies(...)`` decorators from test files (using AST, not
regex), then enforces bidirectional coverage:

  Forward:  every ``must`` criterion must have ≥1 test with a matching
            ``@pytest.mark.verifies`` marker.
  Backward: every ``@pytest.mark.verifies`` marker must reference a
            criterion that exists in a spec.

Exit codes:
  0 — all ``must`` criteria covered, no orphan markers
  1 — any ``must`` criterion uncovered OR marker references nonexistent ID
  2 — parse error (bad table, AST failure, missing file)
"""

from __future__ import annotations

import ast
import re
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Criterion:
    """A single row from a ``## Verification Criteria`` table."""

    id: str
    text: str
    priority: str  # "must" | "should" | "may"
    type: str  # "unit" | "integration" | "e2e" | "security" | "redteam"
    redteam_ids: list[str] = field(default_factory=list)
    source_file: str = ""


@dataclass
class TestMark:
    """A ``@pytest.mark.verifies(...)`` occurrence in a test file."""

    criterion_ids: list[str]
    test_name: str
    source_file: str
    line: int


# ---------------------------------------------------------------------------
# Spec parser
# ---------------------------------------------------------------------------

# Matches a markdown table row with 4 or 5 pipe-separated columns:
#   | ID | Criterion | Priority | Type | [RedTeam] |
_TABLE_ROW_RE = re.compile(
    r"^\|\s*(?P<id>[A-Z][A-Z0-9_-]+-[VS]\d+)\s*"
    r"\|\s*(?P<text>[^|]+?)\s*"
    r"\|\s*(?P<priority>must|should|may)\s*"
    r"\|\s*(?P<type>unit|integration|e2e|security|redteam)\s*"
    r"(?:\|\s*(?P<redteam>[^|]*?)\s*)?"
    r"\|?\s*$",
    re.IGNORECASE,
)

_CRITERIA_SECTION_RE = re.compile(r"^##\s+Verification Criteria\s*$", re.IGNORECASE)


def parse_spec(path: Path) -> list[Criterion]:
    """Extract all Verification Criteria rows from a spec markdown file."""
    criteria: list[Criterion] = []
    in_section = False

    for _lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()

        # Detect section start
        if _CRITERIA_SECTION_RE.match(line):
            in_section = True
            continue

        # Stop at any other H2 (##) heading
        if in_section and re.match(r"^##\s+", line) and not _CRITERIA_SECTION_RE.match(line):
            in_section = False
            continue

        if not in_section:
            continue

        # Skip separator rows like |---|---|...
        if re.match(r"^\|[-|\s:]+\|?\s*$", line):
            continue

        m = _TABLE_ROW_RE.match(line)
        if m:
            redteam_raw = m.group("redteam") or ""
            redteam_ids = [x.strip() for x in redteam_raw.split(",") if x.strip()]
            criteria.append(
                Criterion(
                    id=m.group("id").strip(),
                    text=m.group("text").strip(),
                    priority=m.group("priority").strip().lower(),
                    type=m.group("type").strip().lower(),
                    redteam_ids=redteam_ids,
                    source_file=str(path),
                )
            )

    return criteria


def parse_all_specs(specs_dir: Path) -> dict[str, Criterion]:
    """Parse every *.md in specs_dir and return {id: Criterion}."""
    criteria: dict[str, Criterion] = {}
    for md_path in sorted(specs_dir.glob("*.md")):
        for criterion in parse_spec(md_path):
            if criterion.id in criteria:
                prev = criteria[criterion.id]
                print(
                    f"WARNING: duplicate criterion ID '{criterion.id}' in "
                    f"{criterion.source_file} (first seen in {prev.source_file})",
                    file=sys.stderr,
                )
            criteria[criterion.id] = criterion
    return criteria


# ---------------------------------------------------------------------------
# Test parser (AST-based)
# ---------------------------------------------------------------------------


def _extract_verifies_ids(decorator: ast.expr) -> list[str] | None:
    """
    Return the list of string args if *decorator* is a ``verifies(...)`` call,
    else return None.

    Accepted forms:
      @pytest.mark.verifies("X", "Y")
      @mark.verifies("X")
      @verifies("X")
    """
    # Must be a Call
    if not isinstance(decorator, ast.Call):
        return None

    func = decorator.func

    # Extract the attribute name (last component)
    if isinstance(func, ast.Attribute):
        if func.attr != "verifies":
            return None
    elif isinstance(func, ast.Name):
        if func.id != "verifies":
            return None
    else:
        return None

    # Extract positional string arguments
    ids: list[str] = []
    for arg in decorator.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            ids.append(arg.value)
        else:
            # Non-string arg — can't resolve statically, skip
            return None

    return ids if ids else None


def _collect_marks_from_funcdef(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    source_path: str,
) -> list[TestMark]:
    marks: list[TestMark] = []
    for decorator in node.decorator_list:
        ids = _extract_verifies_ids(decorator)
        if ids is not None:
            marks.append(
                TestMark(
                    criterion_ids=ids,
                    test_name=node.name,
                    source_file=source_path,
                    line=node.lineno,
                )
            )
    return marks


def parse_test_file(path: Path) -> list[TestMark]:
    """Extract all @pytest.mark.verifies markers from a Python test file."""
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        print(f"ERROR: syntax error in {path}: {exc}", file=sys.stderr)
        sys.exit(2)

    marks: list[TestMark] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            marks.extend(_collect_marks_from_funcdef(node, str(path)))

    return marks


def parse_all_tests(tests_dir: Path) -> list[TestMark]:
    """Parse every test_*.py / *_test.py under tests_dir recursively."""
    marks: list[TestMark] = []
    for py_path in sorted(tests_dir.rglob("*.py")):
        if py_path.name.startswith("test_") or py_path.name.endswith("_test.py"):
            marks.extend(parse_test_file(py_path))
    return marks


# ---------------------------------------------------------------------------
# Analysis & reporting
# ---------------------------------------------------------------------------


def _truncate(text: str, max_len: int = 52) -> str:
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def run_check(specs_dir: Path, tests_dir: Path, *, strict_orphan_markers: bool = True) -> int:  # noqa: C901, PLR0915, PLR0912
    """
    Run the RTM check and print the coverage matrix.

    Returns the exit code: 0 = pass, 1 = fail.
    """
    # Parse
    criteria = parse_all_specs(specs_dir)
    all_marks = parse_all_tests(tests_dir)

    if not criteria:
        print("WARNING: no Verification Criteria found in any spec.", file=sys.stderr)
        return 0

    # Build coverage map: criterion_id → list of TestMark
    coverage: dict[str, list[TestMark]] = {cid: [] for cid in criteria}
    orphan_markers: list[TestMark] = []

    for mark in all_marks:
        for cid in mark.criterion_ids:
            if cid in criteria:
                coverage[cid].append(mark)
            else:
                orphan_markers.append(
                    TestMark(
                        criterion_ids=[cid],
                        test_name=mark.test_name,
                        source_file=mark.source_file,
                        line=mark.line,
                    )
                )

    # Determine uncovered must criteria
    must_uncovered = [
        cid for cid, c in criteria.items() if c.priority == "must" and not coverage[cid]
    ]

    # -----------------------------------------------------------------------
    # Report
    # -----------------------------------------------------------------------
    sep = "─" * 90
    print()
    print("RTM Coverage Report")
    print("=" * 90)
    print()

    must_total = sum(1 for c in criteria.values() if c.priority == "must")
    must_covered = must_total - len(must_uncovered)
    total_covered = sum(1 for cid, tests in coverage.items() if tests)

    print(f"  Spec criteria parsed :  {len(criteria)}")
    print(f"  Tests with markers   :  {len(all_marks)}")
    print(f"  must covered         :  {must_covered} / {must_total}")
    print(f"  Total covered        :  {total_covered} / {len(criteria)}")
    print()

    print("COVERAGE MATRIX")
    print(sep)
    print(f"  {'ID':<12} {'Pri':<7} {'Type':<12} {'Criterion':<54} Tests")
    print(sep)

    for cid, criterion in sorted(criteria.items()):
        tests_for = coverage[cid]
        status_prefix = "✓" if tests_for else ("✗" if criterion.priority == "must" else "·")
        short_text = _truncate(criterion.text)
        if tests_for:
            first_test = tests_for[0].test_name
            extra = f" (+{len(tests_for) - 1} more)" if len(tests_for) > 1 else ""
            test_str = f"{first_test}{extra}"
        else:
            test_str = f"(uncovered — {criterion.priority})"

        print(
            f"  {status_prefix} {cid:<11} {criterion.priority:<7} {criterion.type:<12} "
            f"{short_text:<54} {test_str}"
        )

    print(sep)
    print()

    # Orphan must criteria
    if must_uncovered:
        print("ORPHAN CRITERIA (must, uncovered) — CI FAIL:")
        for cid in must_uncovered:
            c = criteria[cid]
            print(f"  ✗ {cid}: {c.text}")
            print(f"      (defined in {c.source_file})")
        print()

    # Orphan markers
    if orphan_markers:
        severity = "CI FAIL" if strict_orphan_markers else "WARNING"
        print(f"ORPHAN MARKERS (reference unknown criterion ID) — {severity}:")
        for mark in orphan_markers:
            short_path = Path(mark.source_file).name
            for cid in mark.criterion_ids:
                if cid not in criteria:
                    print(
                        f"  ⚠ {short_path}:{mark.line} {mark.test_name}() → '{cid}' not in any spec"
                    )
        print()

    # Final verdict
    failed = bool(must_uncovered) or (strict_orphan_markers and bool(orphan_markers))

    if failed:
        reasons: list[str] = []
        if must_uncovered:
            reasons.append(f"{len(must_uncovered)} must criterion uncovered")
        if strict_orphan_markers and orphan_markers:
            reasons.append(f"{len(orphan_markers)} orphan marker(s) reference unknown IDs")
        print(f"❌ RTM check FAILED: {'; '.join(reasons)}")
        return 1
    else:
        may_skipped = sum(
            1 for cid, tests in coverage.items() if not tests and criteria[cid].priority != "must"
        )
        note = f" ({may_skipped} non-must uncovered — OK)" if may_skipped else ""
        print(f"✅ RTM check passed ({must_covered}/{must_total} must criteria covered{note})")
        return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description=textwrap.dedent("""\
            Requirements Traceability Matrix checker.

            Parses Verification Criteria tables from spec markdown files and
            @pytest.mark.verifies markers from test files, then reports coverage
            and enforces that all 'must' criteria have at least one test.
        """),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--specs",
        type=Path,
        default=Path("specs/modules"),
        help="Directory containing spec markdown files (default: specs/modules)",
    )
    parser.add_argument(
        "--tests",
        type=Path,
        default=Path("tests"),
        help="Root directory for test files (default: tests)",
    )
    parser.add_argument(
        "--no-strict-orphans",
        action="store_true",
        default=False,
        help="Downgrade orphan marker errors to warnings (don't exit 1 on orphans)",
    )

    args = parser.parse_args(argv)

    if not args.specs.is_dir():
        print(f"ERROR: specs directory not found: {args.specs}", file=sys.stderr)
        return 2
    if not args.tests.is_dir():
        print(f"ERROR: tests directory not found: {args.tests}", file=sys.stderr)
        return 2

    return run_check(
        specs_dir=args.specs,
        tests_dir=args.tests,
        strict_orphan_markers=not args.no_strict_orphans,
    )


if __name__ == "__main__":
    sys.exit(main())
