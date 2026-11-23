#!/usr/bin/env bash
# Start ATLAS (database, API on :8000, web app on :3000). Ctrl+C stops everything.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
export PATH="$HOME/.local/bin:$PATH"

$SUDO service postgresql start >/dev/null 2>&1 || true

cd "$ROOT/backend"
uv run alembic upgrade head >/dev/null
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 &
API_PID=$!
trap 'kill $API_PID 2>/dev/null' EXIT INT TERM

for _ in $(seq 1 40); do
  curl -sf http://127.0.0.1:8000/api/health >/dev/null && break
  sleep 0.5
done

cd "$ROOT/frontend"
echo
echo "ATLAS is starting. Open http://localhost:3000 in Chrome. Press Ctrl+C here to stop."
echo
pnpm dev --hostname 127.0.0.1 --port 3000
