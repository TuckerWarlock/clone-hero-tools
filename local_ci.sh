#!/usr/bin/env bash
# local_ci.sh — Run the full local CI pipeline (format → lint → test)
#
# Usage:
#   ./local_ci.sh          # run everything
#   ./local_ci.sh --fix    # auto-fix formatting before linting
#
# Requires: uv (https://github.com/astral-sh/uv)
# Deps resolved from .venv created by: uv venv --python 3.14 && uv sync

set -euo pipefail

# ── Colour helpers ──────────────────────────────────────────────────────────
BOLD='\033[1m'
CYAN='\033[96m'
GREEN='\033[92m'
RED='\033[91m'
YELLOW='\033[93m'
RESET='\033[0m'

step()   { echo -e "\n${BOLD}${CYAN}▶  $*${RESET}"; }
ok()     { echo -e "${GREEN}✓  $*${RESET}"; }
fail()   { echo -e "${RED}✗  $*${RESET}"; }
warn()   { echo -e "${YELLOW}⚠  $*${RESET}"; }

PASS=0
FAIL=0

run_step() {
    local label="$1"; shift
    step "$label"
    if "$@"; then
        ok "$label passed"
        ((PASS++)) || true
    else
        fail "$label failed"
        ((FAIL++)) || true
    fi
}

# ── Parse flags ─────────────────────────────────────────────────────────────
FIX=false
for arg in "$@"; do
    [[ "$arg" == "--fix" ]] && FIX=true
done

# ── Ensure we're running from repo root ─────────────────────────────────────
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

# ── Check uv is available ───────────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
    echo -e "${RED}uv not found. Install it: https://docs.astral.sh/uv/getting-started/installation/${RESET}"
    exit 1
fi

echo -e "\n${BOLD}Clone Hero Tools — local CI${RESET}"
echo -e "${CYAN}Python: $(uv run python --version 2>&1)${RESET}"
echo -e "${CYAN}Working dir: $REPO_ROOT${RESET}"

# ── 1. Format ────────────────────────────────────────────────────────────────
if $FIX; then
    step "Black (auto-format)"
    uv run black ch-chart-fix.py tests/ && ok "Black formatted" || { fail "Black failed"; ((FAIL++)) || true; }
else
    run_step "Black (check)" uv run black --check --diff ch-chart-fix.py tests/
fi

# ── 2. Ruff (fast linter — replaces most Flake8 rules + isort) ──────────────
if $FIX; then
    step "Ruff (auto-fix)"
    uv run ruff check --fix ch-chart-fix.py tests/ && ok "Ruff fixed" || { fail "Ruff failed"; ((FAIL++)) || true; }
else
    run_step "Ruff (lint)" uv run ruff check ch-chart-fix.py tests/
fi

# ── 3. Flake8 (belt-and-suspenders pass for any gaps Ruff misses) ───────────
# Use python -m flake8 to avoid shell autocorrect prompts on some zsh setups.
run_step "Flake8" uv run python -m flake8 ch-chart-fix.py tests/

# ── 4. Tests ─────────────────────────────────────────────────────────────────
run_step "Pytest" uv run pytest -v

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}─────────────────────────────────${RESET}"
if [[ $FAIL -eq 0 ]]; then
    echo -e "${GREEN}${BOLD}All $PASS steps passed.${RESET}"
else
    echo -e "${RED}${BOLD}$FAIL step(s) failed, $PASS passed.${RESET}"
    echo -e "${YELLOW}Tip: run  ./local_ci.sh --fix  to auto-fix formatting issues.${RESET}"
    exit 1
fi
