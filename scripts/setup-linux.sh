#!/usr/bin/env bash
# One-time ATLAS setup for Debian/Ubuntu Linux, including the ChromeOS
# Linux development environment (Crostini). Safe to re-run.
#
# Installs: PostgreSQL, Node 22 + pnpm, uv (which provides Python 3.13).
# Creates a local database, a backend/.env from the template (if missing),
# installs dependencies and applies migrations.
#
# It never asks for, prints or stores your Alpaca keys: you add them to
# backend/.env yourself.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
step() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }

step "Installing system packages (PostgreSQL, curl, git)"
$SUDO apt-get update -qq
$SUDO apt-get install -y -qq curl ca-certificates git postgresql >/dev/null

step "Starting PostgreSQL"
$SUDO service postgresql start >/dev/null
for _ in $(seq 1 30); do
  $SUDO -u postgres pg_isready -q 2>/dev/null && break
  sleep 1
done

step "Creating local database 'atlas' (local-only credentials)"
$SUDO -u postgres psql -qtAc "SELECT 1 FROM pg_roles WHERE rolname='atlas'" | grep -q 1 \
  || $SUDO -u postgres psql -qc "CREATE ROLE atlas LOGIN PASSWORD 'atlas_dev_local'"
$SUDO -u postgres psql -qtAc "SELECT 1 FROM pg_database WHERE datname='atlas'" | grep -q 1 \
  || $SUDO -u postgres psql -qc "CREATE DATABASE atlas OWNER atlas"

step "Installing Node 22 and pnpm"
if ! command -v node >/dev/null || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 22 ]; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | $SUDO bash - >/dev/null
  $SUDO apt-get install -y -qq nodejs >/dev/null
fi
command -v pnpm >/dev/null || $SUDO npm install -g --silent pnpm@10
echo "node $(node --version), pnpm $(pnpm --version)"

step "Installing uv (Python manager)"
if ! command -v uv >/dev/null && [ ! -x "$HOME/.local/bin/uv" ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
fi
export PATH="$HOME/.local/bin:$PATH"
echo "$(uv --version)"

step "Creating backend/.env"
cd "$ROOT/backend"
if [ -f .env ]; then
  echo "backend/.env already exists; keeping your values."
  if ! grep -q '^ALPACA_API_KEY_ID=' .env; then
    printf '\n# Alpaca PAPER trading keys (added by setup)\nALPACA_API_KEY_ID=\nALPACA_API_SECRET_KEY=\nALPACA_DATA_FEED=iex\n' >> .env
    echo "Added empty ALPACA_* lines to backend/.env for you to fill in."
  fi
else
  cp .env.example .env
  chmod 600 .env
  echo "Created backend/.env."
fi

step "Installing backend dependencies and applying migrations"
uv sync --quiet
uv run alembic upgrade head

step "Installing frontend dependencies"
cd "$ROOT/frontend"
CI=1 pnpm install --silent --frozen-lockfile

cat <<EOF

$(printf '\033[1;32m')Setup complete.$(printf '\033[0m')

Next:
  1. Add your Alpaca PAPER keys (only you should see these):
       nano $ROOT/backend/.env
     Fill in ALPACA_API_KEY_ID= and ALPACA_API_SECRET_KEY=, then Ctrl+O, Enter, Ctrl+X.
  2. Start ATLAS:
       $ROOT/scripts/run.sh
  3. Open http://localhost:3000 in Chrome.
EOF
