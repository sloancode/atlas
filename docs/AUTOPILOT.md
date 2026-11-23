# Shopify Autopilot

An AI agent (Claude, `claude-opus-5-5`) that runs a **digital-products** Shopify store within
limits you set. Owner decisions: digital products only; fully autonomous within limits; you
attach each download file in Shopify (Shopify offers no API for that).

## What it does each run

1. Reads ATLAS data: 30-day sales KPIs, products with opportunity scores, its own recent actions.
2. Decides on a few actions, in priority order: publish products whose file you confirmed →
   improve existing products (descriptions, tags, SEO, price) → create a new product when the
   catalog is thin.
3. New product = original content written by the agent → rendered to a PDF on your machine
   (`backend/data/products/`, git-ignored) → DRAFT Shopify listing (digital: no shipping, no
   inventory tracking).
4. Ends with a plain-language summary (Autopilot page → Runs).

## Your part

- Turn it on (Autopilot page). It's **off by default**.
- When a product appears under **Needs you**: download the PDF, skim it (this is your review),
  attach it to the draft product in Shopify with the Digital Downloads / Digital Products app,
  then click **File attached**. The agent publishes it on its next run.

## Guardrails (enforced in code, not by the AI)

| Guardrail | Default |
|---|---|
| On/off switch | off |
| **STOP** button (overrides everything; checked before every step and every change) | — |
| Allowed store operations | create draft product, update description/tags/SEO, set price, publish/unpublish, create discount code — nothing else (allow-list checked twice) |
| Products it can touch | only ones it created (`shopify.autopilot_products`) |
| Publish | only after you confirm the file is attached; can be disabled |
| Price range | $3–$49 |
| Max price change per edit | 30% |
| Discounts | ≤ 20%, ≤ 14 days, codes 4–20 letters/digits |
| Store changes per day / new products per day | 15 / 2 |
| Steps per run / run interval | 25 / every 24 h |
| Daily AI budget (estimated from tokens at list price) | $1.00 |

Never: deletes, orders, refunds, customers, inventory, payments, themes, or your own products.
Every attempt — executed, blocked or failed — is logged with its stated reason and before/after
values (Autopilot page → Action log). Analytics and sync keep a read path that rejects all writes.

## Setup checklist

1. Dev Dashboard → your ATLAS app → new version with scopes `write_products`, `write_discounts`,
   `read_publications`, `write_publications` (plus the existing read scopes). Release and approve.
2. Settings → **Run live connection check** → "Autopilot write scopes granted".
3. Install Shopify's free **Digital Downloads** (or **Digital Products**) app.
4. `ANTHROPIC_API_KEY` in `backend/.env`.
5. Settings → **Store mode**: "This store sells only digital products".
6. Pick a paid Shopify plan before expecting sales (the store is on a trial).
7. Autopilot page: review limits → enable → **Run now** to watch the first run.

## Honest expectations

The agent can produce and manage listings; it cannot create demand. Sales depend on traffic
(SEO takes months; ads cost money and are not automated here). The Traffic & conversion panel on
the Shopify page shows whether visitors are arriving and converting.
