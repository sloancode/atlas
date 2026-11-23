"""Daily and weekly business reports.

Reports are built ONLY from synced data with deterministic rules, so they are
reproducible and work without any AI provider. An optional AI narrative is
attached separately (app.services.ai) and is always labeled as interpretation.

  daily  : yesterday (last complete day in shop time) vs the day before
  weekly : last complete Monday-Sunday week vs the week before
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Report
from app.services.analytics.context import ShopContext, Window, _window, load_shop_context
from app.services.analytics.products import inventory_report, products_report
from app.services.analytics.profitability import profitability
from app.services.analytics.sales import sales_overview

CHANGE_THRESHOLD_PCT = 20.0
MIN_BASE = {"orders": 3, "units_sold": 3, "net_sales": 50.0, "aov": 10.0, "refunds_total": 25.0}
WATCHED_KPIS = ["net_sales", "orders", "aov", "units_sold", "refunds_total"]
REPORT_VERSION = 1


def report_windows(kind: str, today: date, ctx: ShopContext) -> tuple[Window, Window]:
    if kind == "daily":
        day = today - timedelta(days=1)
        return _window(day, day, ctx.tz), _window(
            day - timedelta(days=1), day - timedelta(days=1), ctx.tz
        )
    if kind == "weekly":
        last_sunday = today - timedelta(days=today.isoweekday() % 7 or 7)
        start = last_sunday - timedelta(days=6)
        return _window(start, last_sunday, ctx.tz), _window(
            start - timedelta(days=7), last_sunday - timedelta(days=7), ctx.tz
        )
    raise ValueError(f"unknown report kind {kind!r}")


def _money(v: float | None, currency: str) -> str:
    return "—" if v is None else f"{currency} {v:,.2f}"


def build_report(s: Session, kind: str, today: date | None = None) -> dict[str, Any]:
    ctx = load_shop_context(s)
    today = today or datetime.now(ctx.tz).date()
    cur, prev = report_windows(kind, today, ctx)
    currency = ctx.currency or "USD"

    ov = sales_overview(s, ctx, cur, prev)
    prods = products_report(s, ctx, cur, prev, today=today)
    inv = inventory_report(s, ctx, today=today)
    pnl = profitability(s, ctx, cur)
    kpi = {k.key: k for k in ov.kpis}
    synced = ov.meta.status != "missing"

    sold = [p for p in prods.products if p.net_sales > 0]
    best = [
        {
            "title": p.title,
            "net_sales": p.net_sales,
            "units": p.units_sold,
            "growth_pct": p.growth_pct,
        }
        for p in sold[:5]
    ]
    weakest = [
        {
            "title": p.title,
            "net_sales": p.net_sales,
            "units": p.units_sold,
            "growth_pct": p.growth_pct,
            "available": p.available,
        }
        for p in sorted(
            (p for p in prods.products if p.in_catalog and p.status == "ACTIVE"),
            key=lambda p: (p.net_sales, -(p.available or 0)),
        )[:5]
    ]
    alerts = [
        {
            "title": v.product_title
            + ("" if v.variant_title == "Default Title" else f" / {v.variant_title}"),
            "status": v.status,
            "available": v.available,
            "days_of_cover": v.days_of_cover,
            "reason": " ".join(v.reasons),
        }
        for v in inv.variants
        if v.status
        in ("out_of_stock", "stockout_risk", "low_stock", "overstock", "no_recent_sales")
    ]
    pm = {m.key: m for m in pnl.metrics}
    profit = {
        "metrics": [
            {
                "key": k,
                "label": pm[k].label,
                "kind": pm[k].kind,
                "value": pm[k].value,
                "status": pm[k].status.value,
            }
            for k in (
                "net_sales",
                "gross_profit",
                "gross_margin",
                "contribution",
                "net_operating_profit",
            )
        ],
        "missing_inputs": pnl.missing_inputs,
        "cogs_coverage_pct": pnl.cogs_coverage_pct,
    }

    # ---- important changes (rule-based, each with its evidence)
    changes: list[dict[str, str]] = []
    if not synced:
        changes.append(
            {
                "text": "No successful Shopify sync yet; nothing to compare.",
                "evidence": "sync status",
            }
        )
    elif kpi["orders"].current == 0 and kpi["orders"].previous == 0:
        changes.append(
            {
                "text": "No orders in this period or the one before.",
                "evidence": f"orders {cur.period.start}–{cur.period.end}: 0; previous: 0",
            }
        )
    for key in WATCHED_KPIS if synced else []:
        k = kpi[key]
        if k.current is None or k.previous is None:
            continue
        base_ok = abs(k.previous) >= MIN_BASE[key] or abs(k.current) >= MIN_BASE[key]
        if k.change_pct is not None and abs(k.change_pct) >= CHANGE_THRESHOLD_PCT and base_ok:
            direction = "up" if k.change_pct > 0 else "down"
            fmt = (lambda v: _money(v, currency)) if k.kind == "money" else (lambda v: f"{v:g}")
            changes.append(
                {
                    "text": f"{k.label} {direction} {abs(k.change_pct):.0f}%.",
                    "evidence": f"{fmt(k.current)} vs {fmt(k.previous)} in the previous period",
                }
            )
        elif key == "refunds_total" and k.previous == 0 and k.current and k.current > 0:
            changes.append(
                {
                    "text": "Refunds appeared after none in the previous period.",
                    "evidence": f"{_money(k.current, currency)} refunded",
                }
            )
    for p in prods.products:
        if p.net_sales > 0 and p.prev_net_sales == 0 and p.in_catalog:
            changes.append(
                {
                    "text": f"{p.title} sold after no sales in the previous period.",
                    "evidence": f"{p.units_sold} units, {_money(p.net_sales, currency)} net",
                }
            )

    # ---- areas to investigate (prioritised candidates with evidence)
    cands: list[tuple[int, dict[str, str]]] = []
    for a in alerts:
        if a["status"] == "out_of_stock" and "sold" in a["reason"]:
            cands.append(
                (
                    100,
                    {
                        "title": f"Restock {a['title']}",
                        "why": "Out of stock while it has been selling.",
                        "evidence": a["reason"],
                    },
                )
            )
        elif a["status"] == "stockout_risk":
            cands.append(
                (
                    90,
                    {
                        "title": f"Stock running out: {a['title']}",
                        "why": "Fewer days of stock than your alert.",
                        "evidence": a["reason"],
                    },
                )
            )
        elif a["status"] in ("overstock", "no_recent_sales"):
            cands.append(
                (
                    55,
                    {
                        "title": f"Slow-moving stock: {a['title']}",
                        "why": "Inventory is tying up cash.",
                        "evidence": a["reason"],
                    },
                )
            )
        elif a["status"] == "low_stock":
            cands.append(
                (
                    70,
                    {
                        "title": f"Low stock: {a['title']}",
                        "why": "At or below your low-stock alert.",
                        "evidence": a["reason"],
                    },
                )
            )
    for c in changes:
        if " down " in f" {c['text']} " and ("Net sales" in c["text"] or "Orders" in c["text"]):
            cands.append(
                (
                    85,
                    {
                        "title": c["text"].rstrip("."),
                        "why": "A meaningful drop versus the previous period.",
                        "evidence": c["evidence"],
                    },
                )
            )
        if c["text"].startswith("Refunds"):
            cands.append(
                (75, {"title": "Review refunds", "why": c["text"], "evidence": c["evidence"]})
            )
    for p in prods.products:
        for f in p.flags:
            if f.key == "losing_momentum":
                cands.append(
                    (
                        80,
                        {
                            "title": f"{p.title} is losing momentum",
                            "why": f.label,
                            "evidence": f.reason,
                        },
                    )
                )
            elif f.key == "accelerating":
                cands.append(
                    (
                        65,
                        {
                            "title": f"{p.title} is gaining momentum",
                            "why": "Check stock and consider promoting it.",
                            "evidence": f.reason,
                        },
                    )
                )
    if synced and pnl.missing_inputs and sold:
        cands.append(
            (
                60,
                {
                    "title": "Enter missing costs to see real profit",
                    "why": "Profit figures are incomplete.",
                    "evidence": "Missing: " + "; ".join(pnl.missing_inputs[:4]),
                },
            )
        )
    if synced and not prods.products:
        cands.append(
            (
                50,
                {
                    "title": "Add products to your store",
                    "why": "No products are synced, so there is nothing to analyze yet.",
                    "evidence": "0 products in the latest sync",
                },
            )
        )
    elif synced and not sold and kpi["orders"].current == 0:
        cands.append(
            (
                45,
                {
                    "title": "No sales in this period",
                    "why": "Investigate traffic and conversion in Shopify.",
                    "evidence": f"0 orders {cur.period.start}–{cur.period.end}",
                },
            )
        )
    seen: set[str] = set()
    investigate = []
    for _, c in sorted(cands, key=lambda x: -x[0]):
        if c["title"] not in seen:
            seen.add(c["title"])
            investigate.append(c)
        if len(investigate) == 3:
            break

    facts: dict[str, Any] = {
        "version": REPORT_VERSION,
        "kind": kind,
        "shop": ctx.name,
        "currency": currency,
        "timezone": ctx.timezone,
        "period": {"start": cur.period.start.isoformat(), "end": cur.period.end.isoformat()},
        "previous_period": {
            "start": prev.period.start.isoformat(),
            "end": prev.period.end.isoformat(),
        },
        "data_status": ov.meta.status.value,
        "as_of": ov.meta.as_of.isoformat() if ov.meta.as_of else None,
        "notes": ov.meta.notes,
        "sections": {
            "revenue": [k.model_dump() for k in ov.kpis],
            "best_products": best,
            "weakest_products": weakest,
            "inventory_alerts": alerts,
            "profitability": profit,
            "changes": changes,
            "investigate": investigate,
        },
    }
    if kind == "weekly":
        facts["sections"]["daily_trend"] = [d.model_dump(mode="json") for d in ov.daily]
        facts["sections"]["movers"] = [
            {"title": p.title, "flag": f.label, "reason": f.reason}
            for p in prods.products
            for f in p.flags
            if f.key in ("accelerating", "losing_momentum")
        ]
    return facts


def save_report(s: Session, facts: dict[str, Any]) -> Report:
    """Store a report, replacing an earlier one for the same kind and period."""
    start = date.fromisoformat(facts["period"]["start"])
    end = date.fromisoformat(facts["period"]["end"])
    r = s.scalars(
        select(Report).where(
            Report.kind == facts["kind"], Report.period_start == start, Report.period_end == end
        )
    ).first()
    if r is None:
        r = Report(kind=facts["kind"], period_start=start, period_end=end)
        s.add(r)
    r.generated_at = datetime.now(UTC)
    r.facts = facts
    r.narrative = None
    r.narrative_status = "not_requested"
    s.commit()
    return r


def ensure_reports(s: Session, today: date | None = None) -> list[Report]:
    """Generate yesterday's daily and last week's weekly report if missing (catch-up)."""
    ctx = load_shop_context(s)
    if ctx.last_order_sync is None:
        return []
    today = today or datetime.now(ctx.tz).date()
    made = []
    for kind in ("daily", "weekly"):
        cur, _ = report_windows(kind, today, ctx)
        exists = s.scalars(
            select(Report.id).where(
                Report.kind == kind,
                Report.period_start == cur.period.start,
                Report.period_end == cur.period.end,
            )
        ).first()
        if not exists:
            made.append(save_report(s, build_report(s, kind, today)))
    return made


# ------------------------------------------------------------------ export
def _fmt_kpi(k: dict, currency: str) -> str:
    v = k["current"]
    if v is None:
        return "—"
    return _money(v, currency) if k["kind"] == "money" else f"{v:g}"


def to_markdown(facts: dict[str, Any], narrative: dict | None = None) -> str:
    c = facts["currency"]
    sec = facts["sections"]
    title = "Daily" if facts["kind"] == "daily" else "Weekly"
    p, pp = facts["period"], facts["previous_period"]
    out = [
        f"# ATLAS {title} Report — {facts.get('shop') or 'Shopify store'}",
        "",
        f"Period: {p['start']} to {p['end']} (vs {pp['start']} to {pp['end']}) · "
        f"Timezone: {facts['timezone']}",
        f"Source: Shopify Admin API (synced) · Data as of: {facts.get('as_of') or '—'} · "
        f"Status: {facts['data_status']}",
        "",
    ]
    for n in facts.get("notes", []):
        out.append(f"> Note: {n}")
    out += [
        "",
        "## 1. Revenue and orders",
        "",
        "| Metric | This period | Previous | Change |",
        "|---|---|---|---|",
    ]
    for k in sec["revenue"]:
        prev = dict(k, current=k["previous"])
        ch = "n/a" if k["change_pct"] is None else f"{k['change_pct']:+.1f}%"
        out.append(f"| {k['label']} | {_fmt_kpi(k, c)} | {_fmt_kpi(prev, c)} | {ch} |")

    def plist(rows: list[dict], empty: str) -> list[str]:
        if not rows:
            return [empty]
        return [
            f"- {r['title']}: {_money(r['net_sales'], c)} net, {r['units']} units"
            + ("" if r.get("growth_pct") is None else f" ({r['growth_pct']:+.0f}% vs previous)")
            for r in rows
        ]

    out += ["", "## 2. Best-performing products", ""] + plist(
        sec["best_products"], "No product sales in this period."
    )
    out += ["", "## 3. Weakest-performing products", ""] + plist(
        sec["weakest_products"], "No active products."
    )
    out += ["", "## 4. Inventory alerts", ""]
    out += [
        f"- **{a['status'].replace('_', ' ')}** — {a['title']}: {a['reason']}"
        for a in sec["inventory_alerts"]
    ] or ["No inventory alerts."]
    out += ["", "## 5. Profitability observations", ""]
    for m in sec["profitability"]["metrics"]:
        v = m["value"]
        val = "—" if v is None else (f"{v:.1f}%" if m["kind"] == "percent" else _money(v, c))
        out.append(f"- {m['label']}: {val} ({m['status']})")
    if sec["profitability"]["missing_inputs"]:
        out.append(f"- Missing cost inputs: {'; '.join(sec['profitability']['missing_inputs'])}")
    out += ["", "## 6. Important changes", ""]
    out += [f"- {ch['text']} ({ch['evidence']})" for ch in sec["changes"]] or [
        "No significant changes."
    ]
    out += ["", "## 7. Areas to investigate", ""]
    if sec["investigate"]:
        out += [
            f"{i}. **{x['title']}** — {x['why']} Evidence: {x['evidence']}"
            for i, x in enumerate(sec["investigate"], 1)
        ]
        if len(sec["investigate"]) < 3:
            out.append(
                f"\nOnly {len(sec['investigate'])} area(s) met the evidence bar this period."
            )
    else:
        out.append("Nothing met the evidence bar this period.")
    if facts["kind"] == "weekly":
        out += ["", "## Daily trend", "", "| Date | Orders | Gross | Net |", "|---|---|---|---|"]
        out += [
            f"| {d['date']} | {d['orders']} | {_money(d['gross_sales'], c)} "
            f"| {_money(d['net_sales'], c)} |"
            for d in sec.get("daily_trend", [])
        ]
        out += ["", "## Momentum", ""]
        out += [f"- {m['title']}: {m['flag']} — {m['reason']}" for m in sec.get("movers", [])] or [
            "No momentum changes."
        ]
    if narrative and narrative.get("sections"):
        out += ["", "## AI interpretation (Claude) — not a fact source", ""]
        for item in narrative["sections"]:
            flag = "" if item.get("verified", True) else " ⚠ unverified"
            out.append(f"- [{item['type']}] {item['text']}{flag}")
    out += [
        "",
        "_Generated by ATLAS from synced data. Read-only; no changes were made to your store._",
        "",
    ]
    return "\n".join(out)


def to_csv(facts: dict[str, Any]) -> str:
    import csv
    import io

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["section", "item", "current", "previous", "change_pct", "detail"])
    for k in facts["sections"]["revenue"]:
        w.writerow(
            ["revenue", k["label"], k["current"], k["previous"], k["change_pct"], k["definition"]]
        )
    for r in facts["sections"]["best_products"]:
        w.writerow(
            [
                "best_products",
                r["title"],
                r["net_sales"],
                "",
                r["growth_pct"],
                f"{r['units']} units",
            ]
        )
    for r in facts["sections"]["weakest_products"]:
        w.writerow(
            [
                "weakest_products",
                r["title"],
                r["net_sales"],
                "",
                r["growth_pct"],
                f"{r['units']} units",
            ]
        )
    for a in facts["sections"]["inventory_alerts"]:
        w.writerow(
            [
                "inventory_alerts",
                a["title"],
                a["available"],
                "",
                "",
                f"{a['status']}: {a['reason']}",
            ]
        )
    for i, x in enumerate(facts["sections"]["investigate"], 1):
        w.writerow(["investigate", f"{i}. {x['title']}", "", "", "", f"{x['why']} {x['evidence']}"])
    return buf.getvalue()
