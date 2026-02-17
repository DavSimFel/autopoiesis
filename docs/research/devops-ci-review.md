# DevOps & CI/CD Review for Autopoiesis

> Research date: 2026-02-17
> Thesis: When AI agents write the code, tests and CI are the only real quality gate.
> Status: Current CI is functional but insufficient for agent-written code at scale.

---

## 1. Current State Audit

### CI Pipeline (`.github/workflows/ci.yml`)

Five parallel jobs, triggered on PRs to `main` only:

| Job | What it does | Runtime |
|-----|-------------|---------|
| **lint** | `ruff check` + `ruff format --check` | ~30s |
| **typecheck** | `pyright` (strict mode) | ~45s |
| **test** | `pytest -v --tb=short` | ~60s |
| **security** | `pip-audit` + `bandit -r . -s B101` | ~45s |
| **spec-check** | Verifies changed `.py` files have corresponding spec updates | ~15s |

**What's good:**
- Strict Pyright (`typeCheckingMode = "strict"`) — this catches a lot. Most Python projects don't do this.
- Ruff with a solid rule set (bugbear, simplify, comprehensions, complexity cap at 10).
- The spec-check is novel — forces documentation parity with code changes. This is especially valuable when agents write code, since they'll update specs if forced.
- `bandit -s B101` correctly skips assert warnings in test code.

**What's missing:**
- No caching. Every job runs `uv sync` from scratch. That's 4 redundant dependency installs.
- No coverage enforcement. Tests run with `--cov` locally (via `pyproject.toml` addopts) but CI doesn't use `--cov-fail-under`.
- No coverage reporting to PRs (no Codecov, no coverage comment).
- No job dependencies — lint and typecheck should gate test runs (fail fast, save compute).
- Only triggers on PRs to `main`. No CI on `dev` branch, no nightly runs, no post-merge checks.
- No Python version matrix. Only runs on whatever `ubuntu-latest` ships.
- No artifact uploads (test results, coverage reports).

### Test Infrastructure

- **34 test files**, ~4,270 lines total. Decent for a v0.1.0.
- **conftest.py** provides 5 fixtures: `workspace` (tmp_path), `mock_deps` (LocalBackend), `key_manager`, `approval_store`, `history_db`. All use `tmp_path` — good isolation.
- **async support**: `asyncio_mode = "auto"` — all async tests just work.
- **No test markers** (no `@pytest.mark.slow`, `@pytest.mark.integration`). Everything runs in one undifferentiated blob.
- **No parallel execution** (no `pytest-xdist`). Tests are sequential.
- **Coverage at ~79%** — respectable but not enforced. No coverage floor means it can silently regress.
- **Issue #154** plans 38 integration tests — these will need proper isolation and marking.

### Tooling (`pyproject.toml`)

- `ruff >=0.9` — good, fast linter/formatter
- `pyright >=1.1` — strict mode, great
- `pytest >=8.0` + `pytest-asyncio >=0.24` + `pytest-cov >=6.0` — solid test stack
- `pip-audit` + `bandit` — basic security
- **Missing**: `pytest-xdist` (parallelism), `hypothesis` (property-based), `mutmut`/`cosmic-ray` (mutation testing)

---

## 2. Gap Analysis for Agent-Written Code

### The Core Problem

When Codex or Claude writes code on a feature branch and opens a PR, the current CI catches:
- ✅ Syntax errors, import issues (ruff)
- ✅ Type errors, incorrect signatures (pyright strict)
- ✅ Test regressions (pytest)
- ✅ Known vulnerability introductions (pip-audit)
- ✅ Common security patterns (bandit)
- ✅ Spec drift (spec-check)

What it **doesn't** catch:
- ❌ **Semantic correctness** — tests pass but behavior is subtly wrong
- ❌ **Coverage regression** — agent deletes tests or adds untested code
- ❌ **Test quality** — agent writes tests that assert nothing meaningful
- ❌ **Performance regression** — code is correct but 10x slower
- ❌ **Unnecessary complexity** — agent adds 200 lines where 20 would do
- ❌ **Dependency bloat** — agent adds a new dep for one function

### Mutation Testing

**What**: Introduce small code changes (mutations) and verify tests catch them. If a mutation survives (tests still pass), your tests are weak.

**Verdict**: Add it, but not in CI. Run `mutmut` nightly or weekly. Mutation testing is slow (minutes to hours) and noisy. Use it as a diagnostic, not a gate.

**What serious projects do**: Pydantic runs mutation testing periodically. CPython doesn't (too large). For autopoiesis's size (~4K test lines), `mutmut` would complete in 5-15 minutes — manageable as a nightly job.

### Property-Based Testing (Hypothesis)

**What**: Generate random inputs and verify invariants hold. Catches edge cases no human would think to test.

**Verdict**: Add for specific modules. The approval system (cryptographic operations), history store (SQLite operations), and topic manager (state machines) are prime candidates. Don't blanket-apply it — property tests are only useful when you can express meaningful properties.

**Effort**: 1-2 days to add `hypothesis` and write 10-15 property tests for the highest-risk modules.

### Integration Test Isolation

Current tests use `tmp_path` — good. But the planned 38 integration tests (Issue #154) will likely need:
- Database isolation (separate SQLite per test)
- Filesystem isolation (already handled by `tmp_path`)
- No shared mutable state between tests

**Can tests run in parallel?** Probably yes, if every test uses `tmp_path` for state. Add `pytest-xdist` and verify. If anything breaks under `-n auto`, fix it — it means you have hidden shared state.

### Flaky Test Detection

No flaky test infrastructure exists. For now, this is fine — 34 test files with no network calls shouldn't be flaky. But once integration tests hit (Issue #154), add:
- `pytest-rerunfailures` with `--reruns 2` for integration tests only
- Track flake rate over time (GitHub Actions has this data in run history)

### Test Execution Budget

Current: ~60s for all tests. Comfortable. The budget should be:
- **PR checks**: <5 minutes total (all jobs). Currently ~2 min. Fine.
- **Nightly**: <15 minutes. Room for mutation testing, property tests, full integration suite.
- **Alert threshold**: If PR checks exceed 5 minutes, investigate.

---

## 3. CI Pipeline Architecture

### Job Dependency Graph

Current: all 5 jobs run in parallel. This wastes compute when lint fails.

**Recommended structure:**
```
lint ──┐
       ├──> test ──> coverage-check
typecheck ─┘
security (parallel, independent)
spec-check (parallel, independent)
```

Lint + typecheck are fast (~30s each). If either fails, skip the expensive test job. Security and spec-check are independent — run them in parallel with everything.

### Caching

Add uv cache. This is trivial and saves 15-30s per job:

```yaml
- uses: astral-sh/setup-uv@v4
  with:
    enable-cache: true
```

That's it. One line. No excuse not to have it.

### Matrix Testing

**Python versions**: Only 3.12 is supported (`requires-python = ">=3.12"`). Don't matrix test 3.13 yet unless you actively want to support it. One Python version is fine for now.

**OS**: Only Linux matters for CI. The project is a CLI agent, not a desktop app. Skip Windows/macOS matrix.

### PR vs Merge vs Nightly

| Trigger | What runs | Why |
|---------|-----------|-----|
| **PR to main/dev** | lint, typecheck, test, security, spec-check | Gate all changes |
| **Push to dev** | Same + coverage report | Track coverage trends |
| **Push to main** | Same + release readiness | Final verification |
| **Nightly (cron)** | All + mutation testing + full integration suite | Catch slow-burn issues |
| **Weekly** | Dependency audit (pip-audit with fresh index) | Catch newly disclosed CVEs |

Currently only PR to `main` triggers CI. **Add `dev` branch** — that's where most work lands.

### Branch Protection

Enforce in GitHub settings:
- **main**: Require all CI checks passing + 1 approving review + no direct pushes
- **dev**: Require all CI checks passing + no direct pushes (0 approvals OK per AGENTS.md)

This is already documented in AGENTS.md but may not be enforced in GitHub. Verify and enforce.

---

## 4. Security in Agent Workflows

### Current State

- `pip-audit`: Checks installed packages against vulnerability databases. Good.
- `bandit`: Static analysis for common Python security issues. Good but limited.
- Both run on every PR. Adequate baseline.

### Supply Chain Security

**Lockfile verification**: The project uses `uv.lock`. CI should verify the lockfile is up-to-date:
```yaml
- name: Verify lockfile
  run: uv lock --check
```
This prevents agents from modifying `pyproject.toml` without updating the lockfile (or vice versa).

**SLSA/Sigstore**: Overkill for now. This matters when you publish packages. Autopoiesis is a CLI tool, not a library. **NEVER** for current phase.

### Agent-Introduced Dependencies

This is the real risk. An agent could add `import some_package` and update `pyproject.toml`. The `pip-audit` job catches known vulns, but:
- New packages might not have vulnerability data yet
- Transitive dependencies could be problematic

**Recommendation**: Add a PR check that flags new dependencies. A simple diff on `pyproject.toml` dependencies with a comment "New dependency added: X — review needed" is enough. This is a 10-line shell script.

### Secrets in CI

Current CI has no secrets (no API keys needed for tests). Keep it this way as long as possible. When integration tests need API access:
- Use GitHub Actions secrets
- Never expose in logs (`--no-print-directory`, mask outputs)
- Consider mock/replay for API-dependent tests (VCR.py or similar)

---

## 5. Observability & Feedback Loops

### Test Result Reporting

Current: Test failures show as red checks on the PR. That's the minimum.

**For agent-written PRs**, failures need to be actionable. If Codex opens a PR and tests fail:
- The failure message must be clear enough for the agent to self-correct
- `--tb=short` is fine for humans, but agents benefit from `--tb=long` with full tracebacks

**Recommendation**: Use `--tb=long` in CI (it's only read by machines anyway) and add `pytest --junitxml=results.xml` for structured reporting.

### Coverage Trends

No coverage tracking exists. Options:
- **Codecov** (free for OSS): Coverage comments on PRs, trend graphs, configurable thresholds. **Recommended.**
- **coveralls**: Similar, slightly less popular.
- **DIY**: `coverage json` + GitHub Actions artifact. Works but more maintenance.

Set a coverage floor at 75% (below current 79%) and ratchet up over time. Never let it drop.

### Performance Regression Detection

Not needed yet. The test suite runs in ~60s. When it hits 3+ minutes, add `pytest-benchmark` for critical paths. **LATER**.

### CI Analytics

GitHub Actions provides run duration and pass/fail history natively. No additional tooling needed. If CI starts failing >10% of runs, investigate. Track informally for now.

---

## 6. Recommendations

### NOW (This Week)

| # | What | Why | Effort |
|---|------|-----|--------|
| 1 | **Add uv caching** to all CI jobs | Saves 15-30s per job, one-line change | 10 min |
| 2 | **Add `--cov-fail-under=75`** to pytest in CI | Prevent coverage regression | 10 min |
| 3 | **Add `uv lock --check`** to CI | Catch lockfile drift | 10 min |
| 4 | **Trigger CI on PRs to `dev`** too | Most work lands on dev, not main | 5 min |
| 5 | **Add job dependencies** (lint+typecheck gate test) | Fail fast, save compute | 15 min |
| 6 | **Add `pytest-xdist`** and run tests with `-n auto` | Parallel tests, catch shared state bugs | 30 min |

Total: ~90 minutes. All high-value, low-risk.

### SOON (This Month)

| # | What | Why | Effort |
|---|------|-----|--------|
| 7 | **Codecov integration** | Coverage trends, PR comments, coverage gates | 1 hour |
| 8 | **New dependency detection** in PRs | Flag when agents add packages | 1 hour |
| 9 | **Test markers** (`@pytest.mark.integration`, `@pytest.mark.slow`) | Separate fast unit tests from slow integration tests | 2 hours |
| 10 | **Nightly workflow** with extended checks | Mutation testing, full integration suite | 2 hours |
| 11 | **Property-based tests** (hypothesis) for approval/crypto/store modules | Catch edge cases in critical paths | 1-2 days |
| 12 | **`--tb=long` + JUnit XML** in CI | Better failure diagnostics for agents | 15 min |

### LATER (When Needed)

| # | What | When | Why |
|---|------|------|-----|
| 13 | **Mutation testing** (mutmut) as nightly job | When test count > 100 | Validate test quality |
| 14 | **pytest-benchmark** for performance tracking | When test suite > 3 min | Catch perf regressions |
| 15 | **Docker/container scanning** | When Dockerfile is added | Supply chain for containers |
| 16 | **API mock/replay** (VCR.py) | When integration tests need external APIs | Deterministic API tests |
| 17 | **Flaky test rerun** (`pytest-rerunfailures`) | When flake rate > 5% | Reduce noise |

### NEVER (For This Project)

| What | Why Not |
|------|---------|
| **SLSA/Sigstore** | Not publishing packages. Zero value. |
| **Multi-OS matrix** | CLI agent, Linux-only CI is fine. |
| **DAST scanning** | No deployed web surface to scan (server is local). |
| **SonarQube/SonarCloud** | Ruff + Pyright + Bandit already cover this. Adding SonarQube is complexity for marginal gain. |
| **Full SAST pipeline** (Snyk, Semgrep, etc.) | Bandit + pip-audit is sufficient. The codebase is small. Don't add enterprise security tooling to a CLI agent. |

---

## Appendix: Concrete CI Diff

Here's what the improved `ci.yml` should look like for the NOW items:

```yaml
name: CI
on:
  pull_request:
    branches: [main, dev]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with:
          enable-cache: true
      - run: uv sync
      - run: uv run ruff check . --output-format=github
      - run: uv run ruff format --check .

  typecheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with:
          enable-cache: true
      - run: uv sync
      - run: uv run pyright

  test:
    needs: [lint, typecheck]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with:
          enable-cache: true
      - run: uv sync
      - run: uv run pytest -v --tb=long --cov-fail-under=75 -n auto --junitxml=results.xml
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: test-results
          path: results.xml

  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with:
          enable-cache: true
      - run: uv sync
      - run: uv run pip-audit
      - run: uv run bandit -r . -s B101 --exclude ./.venv,./tests

  spec-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Verify lockfile
        run: |
          pip install uv
          uv lock --check
      - name: Check spec freshness
        run: |
          # ... (existing spec-check script unchanged)
```

Note: `pytest-xdist` needs to be added to dev dependencies in `pyproject.toml`.

---

## Key Takeaway

The current CI is a solid foundation — better than most v0.1.0 projects. The critical gaps are all cheap to fix (caching, coverage floor, dev branch triggers, job dependencies). The expensive stuff (mutation testing, property tests, Codecov) can wait until the integration test suite (Issue #154) lands. Don't over-engineer the pipeline — autopoiesis died once as Silas from exactly that mistake.
