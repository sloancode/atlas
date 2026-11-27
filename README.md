# ATLAS

Paper trading bot dashboard and market research, for one person on their own computer.

- **Trading bot**: an autonomous news + price-pattern bot that trades an Alpaca **paper** account
  (simulated money): stocks long and short during market hours, crypto around the clock. Fixed
  rules and risk limits in code decide every order
  ([docs/TRADING_BOT.md](docs/TRADING_BOT.md)).
- **Bot dashboard** (home page): live account, positions with their protective stops, open and
  recent orders, the guardrails (daily loss cap, drawdown, exposure), and a dry run of the
  position checks.
- **Research**: US stock/ETF research pages, a rules-based scanner and watchlists.

The website is read-only: it never places, changes or cancels orders. Orders are placed only by
the scheduled bot run, exactly as the planner prints them. ATLAS only talks to Alpaca's paper
host and refuses non-paper accounts; there is no live-trading code.

## Layout

```
backend/    FastAPI + SQLAlchemy + Alembic + pandas (Python 3.13, uv)
  app/core/              config (env-only secrets), log redaction, provenance types
  app/providers/         alpaca.py (paper, read-only), market/ (Massive, FMP, SEC EDGAR)
  app/services/trading/  bot rules, risk limits, planner, CLI
  app/api/routes/        bot, markets, system
  migrations/            Alembic
  tests/
frontend/   Next.js 15 + TypeScript + Tailwind (dark terminal UI)
docs/       TRADING_BOT.md, INTEGRATIONS.md
PROJECT_STATUS.md   what works, what doesn't, what's needed
```

## Run on a Chromebook (or any Debian/Ubuntu Linux)

1. Turn on Linux: **Settings → About ChromeOS → Developers → Linux development environment → Turn on**
   (allow at least 10 GB of disk). Then open the **Terminal** app and choose **penguin**.
2. Install git and download ATLAS (if you already have it: `cd atlas && git pull`):
   ```bash
   sudo apt-get update && sudo apt-get install -y git
   git clone https://github.com/sloancode/atlas && cd atlas
   ```
3. Run the setup (safe to re-run; keeps your existing `backend/.env` and adds the Alpaca lines):
   ```bash
   ./scripts/setup-linux.sh
   ```
4. Create **paper** API keys: alpaca.markets → switch to **Paper Trading** → **API Keys** →
   **Generate**. Add them yourself — never paste them into a chat:
   ```bash
   nano backend/.env
   ```
   Fill in `ALPACA_API_KEY_ID=` and `ALPACA_API_SECRET_KEY=`, then **Ctrl+O, Enter, Ctrl+X**.
5. Start ATLAS (leave the Terminal window open; **Ctrl+C** stops it):
   ```bash
   ./scripts/run.sh
   ```
6. Open **http://localhost:3000** in Chrome. **Settings → Run live connection check** should show
   Alpaca as Connected.

## Run locally (macOS / other)

Prerequisites: Python 3.13 + [uv](https://docs.astral.sh/uv/), Node 22 + pnpm, PostgreSQL 16 (or Docker).

```bash
docker compose up -d db                 # or use a local Postgres
cd backend
cp .env.example .env                    # fill in keys (never commit .env)
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --port 8000
```

```bash
cd frontend
pnpm install
pnpm dev                                # http://localhost:3000
```

The frontend reads the backend URL from `ATLAS_API_URL` (default `http://127.0.0.1:8000`).

## Tests

```bash
cd backend && uv run pytest && uv run ruff check .
cd frontend && pnpm lint && pnpm build
```
