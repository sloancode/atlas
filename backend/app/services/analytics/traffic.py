"""Traffic and conversion funnel from Shopify analytics (ShopifyQL, read-only).

Requires the `read_reports` scope. Queries validated against the live store:
  FROM sessions SHOW sessions, sessions_with_cart_additions,
       sessions_that_reached_checkout, sessions_that_completed_checkout, conversion_rate
  FROM sessions SHOW sessions, conversion_rate GROUP BY referrer_source
Results are cached for 30 minutes (Shopify analytics are not real-time).
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import redact
from app.db.models import MarketCache
from app.providers.base import ProviderError
from app.providers.shopify.client import ShopifyClient
from app.services.analytics.context import Window

SHOPIFYQL = """
query AtlasShopifyQL($q: String!) {
  shopifyqlQuery(query: $q) {
    parseErrors
    tableData { columns { name dataType } rows }
  }
}
"""
TTL = timedelta(minutes=30)
FUNNEL = (
    "FROM sessions SHOW sessions, sessions_with_cart_additions, sessions_that_reached_checkout, "
    "sessions_that_completed_checkout, conversion_rate SINCE {s} UNTIL {e}"
)
SOURCES = (
    "FROM sessions SHOW sessions, conversion_rate GROUP BY referrer_source "
    "SINCE {s} UNTIL {e} ORDER BY sessions DESC LIMIT 10"
)


class Traffic(BaseModel):
    status: str  # historical | missing
    as_of: datetime | None
    sessions: int | None = None
    cart_sessions: int | None = None
    checkout_sessions: int | None = None
    completed_sessions: int | None = None
    conversion_rate_pct: float | None = None
    sources: list[dict[str, Any]] = []
    notes: list[str] = []


def _rows(table: dict) -> list[dict[str, Any]]:
    """Normalise ShopifyQL rows (list of lists or list of objects) to dicts."""
    cols = [c["name"] for c in table.get("columns") or []]
    out = []
    for r in table.get("rows") or []:
        out.append(dict(zip(cols, r, strict=False)) if isinstance(r, list) else dict(r))
    return out


def _int(v: Any) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _pct(v: Any) -> float | None:
    """ShopifyQL PERCENT: a ratio (0.025) or a percent (2.5); empty means undefined."""
    try:
        x = float(str(v).rstrip("%"))
    except (TypeError, ValueError):
        return None
    return round(x * 100, 2) if 0 < x <= 1 and "%" not in str(v) else round(x, 2)


async def run_query(client: ShopifyClient, q: str) -> list[dict[str, Any]]:
    data = await client.query(SHOPIFYQL, {"q": q})
    res = data.get("shopifyqlQuery") or {}
    if res.get("parseErrors"):
        raise ProviderError("ShopifyQL error: " + "; ".join(map(str, res["parseErrors"]))[:300])
    return _rows(res.get("tableData") or {})


async def traffic(
    s: Session, settings: Settings, w: Window, client: ShopifyClient | None = None
) -> Traffic:
    key = f"shopify_traffic:{w.period.start}:{w.period.end}"
    row = s.get(MarketCache, key)
    if row and datetime.now(UTC) - row.retrieved_at < TTL:
        return Traffic(**row.payload)
    from app.providers.shopify.provider import ShopifyProvider

    if ShopifyProvider(settings).missing_env():
        return Traffic(status="missing", as_of=None, notes=["Shopify is not configured."])
    own = client is None
    client = client or ShopifyClient(settings)
    try:
        f = await run_query(client, FUNNEL.format(s=w.period.start, e=w.period.end))
        src = await run_query(client, SOURCES.format(s=w.period.start, e=w.period.end))
    except ProviderError as exc:
        msg = redact(str(exc))
        if "403" in msg or "scope" in msg.lower():
            msg += " (traffic analytics need the read_reports scope)"
        return Traffic(status="missing", as_of=None, notes=[msg])
    finally:
        if own:
            await client.aclose()
    top = f[0] if f else {}
    t = Traffic(
        status="historical",
        as_of=datetime.now(UTC),
        sessions=_int(top.get("sessions")),
        cart_sessions=_int(top.get("sessions_with_cart_additions")),
        checkout_sessions=_int(top.get("sessions_that_reached_checkout")),
        completed_sessions=_int(top.get("sessions_that_completed_checkout")),
        conversion_rate_pct=_pct(top.get("conversion_rate")),
        sources=[
            {
                "source": r.get("referrer_source") or "(direct/unknown)",
                "sessions": _int(r.get("sessions")),
                "conversion_rate_pct": _pct(r.get("conversion_rate")),
            }
            for r in src
        ],
        notes=["Shopify analytics can lag by a few hours."],
    )
    if t.sessions == 0:
        t.notes.append("No storefront sessions in this period.")
    stmt = insert(MarketCache).values(
        key=key, source="shopifyql", retrieved_at=t.as_of, payload=t.model_dump(mode="json")
    )
    s.execute(
        stmt.on_conflict_do_update(
            index_elements=["key"], set_={"retrieved_at": t.as_of, "payload": stmt.excluded.payload}
        )
    )
    s.commit()
    return t
