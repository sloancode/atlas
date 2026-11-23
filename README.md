# ATLAS

Personal business intelligence and market research platform.

- **Shopify engine**: sales, product, profitability and inventory analytics for your store (read-only).
- **Market research engine**: US stock/ETF research, scanner and a *simulated* paper portfolio.
- **Shopify Autopilot**: optional AI agent that creates, prices and publishes digital products within your limits.
- **eBay module**: architecture prepared; intentionally not connected.

ATLAS reads your store without changing it, **unless you enable Shopify Autopilot**: an AI agent
that runs a digital-products store within code-enforced limits (see [docs/AUTOPILOT.md](docs/AUTOPILOT.md)).
Even then it never deletes anything, never touches orders, refunds, customers or payments, and
ATLAS never places market trades (the paper portfolio is simulated).

## Layout

```
backend/    FastAPI + SQLAlchemy + Alembic + pandas (Python 3.13, uv)
  app/core/        config (env-only secrets), log redaction, provenance types
  app/providers/   shopify/, market/ (Massive, FMP, SEC EDGAR), ebay/ (stub)
  app/api/         HTTP routes
  app/db/          models (schemas: core, shopify, ebay, market, paper)
  migrations/      Alembic
  tests/
frontend/   Next.js 15 + TypeScript + Tailwind (dark terminal UI)
docs/       integration notes, metric definitions (METRICS.md)
PROJECT_STATUS.md   what works, what doesn't, what's needed
```

## Run on a Chromebook (or any Debian/Ubuntu Linux)

1. Turn on Linux: **Settings → About ChromeOS → Developers → Linux development environment → Turn on**
   (allow at least 10 GB of disk). Then open the **Terminal** app and choose **penguin**.
2. Install git and download ATLAS:
   ```bash
   sudo apt-get update && sudo apt-get install -y git
   git clone https://github.com/sloancode/atlas && cd atlas
   ```
3. Run the one-time setup (installs PostgreSQL, Node, pnpm and uv; takes a few minutes):
   ```bash
   ./scripts/setup-linux.sh
   ```
4. Add your Shopify app's client ID and secret yourself — never paste them into a chat:
   ```bash
   nano backend/.env
   ```
   Fill in `SHOPIFY_CLIENT_ID=` and `SHOPIFY_CLIENT_SECRET=`, then **Ctrl+O, Enter, Ctrl+X**.
   Check them (prints Shopify's answer, never the secret):
   ```bash
   ./scripts/check-shopify.sh
   ```
5. Start ATLAS (leave the Terminal window open; **Ctrl+C** stops it):
   ```bash
   ./scripts/run.sh
   ```
6. Open **http://localhost:3000** in Chrome → **Settings** → **Run live connection check** → **Sync now**.

Next time, just open Terminal and run `cd atlas && ./scripts/run.sh`.

## Run locally (macOS / other)

Prerequisites: Python 3.13 + [uv](https://docs.astral.sh/uv/), Node 22 + pnpm, PostgreSQL 16 (or Docker).

```bash
docker compose up -d db                 # or use a local Postgres
cd backend
cp .env.example .env                    # fill in credentials (never commit .env)
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

## Connecting Shopify

See [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md#shopify). Short version: create an app in the
Shopify Dev Dashboard with read-only scopes, install it on your store, and put the client ID
and secret in `backend/.env`. Then open **Settings → Run live connection check**.
