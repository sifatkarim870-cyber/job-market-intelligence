#!/usr/bin/env bash
# ============================================================================
# bootstrap.sh — one-command environment setup for a new developer.
#
# What it does:
#   1. Verifies uv is installed (installs it if missing, with confirmation).
#   2. Creates the virtual environment and installs base + dev + test deps.
#   3. Copies .env.example -> .env if .env doesn't already exist.
#   4. Installs pre-commit hooks.
#   5. Runs the environment verification script.
#
# Usage:
#   ./scripts/bootstrap.sh
# ============================================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "==> Job Market Intelligence Platform — environment bootstrap"
echo "    Project root: $PROJECT_ROOT"
echo

# --- 1. Verify / install uv --------------------------------------------------
if ! command -v uv &> /dev/null; then
    echo "==> 'uv' not found."
    read -r -p "    Install uv now via the official installer? [y/N] " reply
    if [[ "$reply" =~ ^[Yy]$ ]]; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.cargo/bin:$PATH"
    else
        echo "    Aborting. Install uv manually: https://docs.astral.sh/uv/"
        exit 1
    fi
else
    echo "==> uv found: $(uv --version)"
fi

# --- 2. Create venv + install dependencies -----------------------------------
echo "==> Creating virtual environment and installing dependencies (base + dev + test)..."
uv venv
uv sync --extra dev --extra test

# --- 3. Set up .env -----------------------------------------------------------
if [[ ! -f ".env" ]]; then
    echo "==> Creating .env from .env.example (fill in real values before running anything)."
    cp .env.example .env
else
    echo "==> .env already exists — leaving it untouched."
fi

# --- 4. Install pre-commit hooks ----------------------------------------------
if [[ -f ".pre-commit-config.yaml" ]]; then
    echo "==> Installing pre-commit hooks..."
    uv run pre-commit install
else
    echo "==> No .pre-commit-config.yaml yet — skipping hook installation."
fi

# --- 5. Verify environment -----------------------------------------------------
echo "==> Running environment verification..."
uv run python scripts/verify_env.py || true

echo
echo "==> Bootstrap complete."
echo "    Next steps:"
echo "      1. Edit .env with real database credentials."
echo "      2. Re-run: uv run python scripts/verify_env.py"
echo "      3. Activate the venv manually if needed: source .venv/bin/activate"
