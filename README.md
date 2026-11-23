# ATLAS

Personal business intelligence and market research platform.

- **Shopify engine**: sales, product, profitability and inventory analytics for your store (read-only).
- **Market research engine**: US stock/ETF research, scanner and a *simulated* paper portfolio.
- **eBay module**: architecture prepared; intentionally not connected.

ATLAS is **read-only by design**. It never changes prices, products, inventory,
orders, refunds or customers, never places orders, and never executes trades.

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
docs/       integration notes
PROJECT_STATUS.md   what works, what doesn't, what's needed
```

## Run locally

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
