#!/usr/bin/env bash
# =============================================================================
# scripts/run_pr_checks.sh — the PR-tier check ordering from
# pass3-systems.md §8.6, scoped to what M0 actually has.
#
#   ./scripts/run_pr_checks.sh
#
# There is NO hosted CI: this repo has no git remote, so nothing runs on push.
# Run this by hand before landing work. "Blocking" means this script exits
# non-zero — not that a service enforces it. See docs/TRADEBOT_CI.md.
#
# Tiers whose subject matter does not exist yet are listed as explicit no-ops
# rather than silently omitted: a tier that passes without asserting anything
# reads as coverage the repo does not have.
# =============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Resolve the interpreter. `.venv/` is gitignored, so it exists only in the main
# checkout — a linked worktree (mig sessions live in .mig/worktrees/<ID>) has
# none. Fall back to the main worktree's venv, found via --git-common-dir, which
# points at the shared .git no matter which worktree we are standing in. This is
# the same trap .mig/config sidesteps by pinning VERIFY_CMD to an absolute path.
# TRADEBOT_PY overrides both, and lets the failure path be exercised without
# breaking a real test (a script whose non-zero exit is never proven is a script
# that reports green).
_resolve_py() {
  [ -n "${TRADEBOT_PY:-}" ] && { printf '%s\n' "$TRADEBOT_PY"; return; }
  [ -x "$ROOT/.venv/bin/python" ] && { printf '%s\n' "$ROOT/.venv/bin/python"; return; }
  local common main
  common="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || true
  if [ -n "$common" ]; then
    main="$(dirname "$common")"
    [ -x "$main/.venv/bin/python" ] && { printf '%s\n' "$main/.venv/bin/python"; return; }
  fi
  printf '%s\n' "$ROOT/.venv/bin/python"   # report the expected path in the error
}
PY="$(_resolve_py)"
FAILED=0

hr()   { printf '%s\n' "────────────────────────────────────────────────────────"; }
skip() { printf '  SKIP  %-34s %s\n' "$1" "$2"; }

run_tier() {   # <label> <command...>
  local label="$1"; shift
  hr; printf '▶ %s\n' "$label"
  if "$@"; then
    printf '  PASS  %s\n' "$label"
  else
    printf '  FAIL  %s\n' "$label"
    FAILED=1
  fi
}

[ -x "$PY" ] || { echo "no interpreter at $PY — create .venv first" >&2; exit 2; }

# -- tier 1 · unit (§7.1) -----------------------------------------------------
# Deliberately the exact command in .mig/config's VERIFY_CMD, so this script and
# the mig session gate can never disagree about what "green" means.
run_tier "unit (§7.1)" \
  "$PY" -m unittest discover -s tests/unit -p 'test_*.py'

# -- tier 2 · property-based (§7.2) -------------------------------------------
# P4-P8 assert real invariants; P11 is executable groundwork for the pass6
# rounding law. Run separately from tier 1 (which already includes them) so a
# property regression is attributable on sight.
run_tier "property (§7.2 · P4-P8, P11 groundwork)" \
  "$PY" -m unittest tests.unit.test_tradebot_properties -v

# -- tiers not yet wired ------------------------------------------------------
hr; printf '▶ tiers awaiting their subject matter\n'
skip "lint (ruff + mypy)"        "no lint config; needs an agreed rule set + per-dir ratchet"
skip "sim scenarios (§7.3)"      "needs the M1 kernel and M2 risk/execution machinery"
skip "golden parity (§7.5)"      "needs M1's frozen lake AND its committed manifest"
skip "build image"               "no Dockerfile; deployment topology still an open decision"
skip "chaos / kill-9 (§7.4)"     "needs the docker-compose harness built at M1"

hr
if [ "$FAILED" -ne 0 ]; then
  echo "PR checks FAILED"
  exit 1
fi
echo "PR checks passed"
