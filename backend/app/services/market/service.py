"""Market data facade: provider routing, caching and provenance.

Routing (first configured provider that succeeds):
  bars        Massive -> FMP
  profile     Massive -> FMP -> SEC EDGAR
  financials  FMP -> SEC EDGAR
  earnings    FMP
  news        Massive -> FMP
Every result records its source, retrieval time, whether it came from cache,
and which providers failed first. When nothing is configured the result is
MISSING with the env vars that would enable it -- never sample data.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import redact
from app.db.models import MarketCache
from app.providers.base import ProviderError
from app.services.market.indicators import Bar
from app.services.market.providers import FMP, Edgar, MarketProvider, Massive

ROUTES: dict[str, list[str]] = {
    "bars": ["massive", "fmp"],
    "profile": ["massive", "fmp", "sec_edgar"],
    "financials": ["fmp", "sec_edgar"],
    "earnings": ["fmp"],
    "news": ["massive", "fmp"],
}
TTL = {
    "bars": timedelta(hours=6),
    "profile": timedelta(days=7),
    "financials": timedelta(days=1),
    "earnings": timedelta(hours=12),
    "news": timedelta(hours=1),
}
ENV_FOR = {"massive": "MASSIVE_API_KEY", "fmp": "FMP_API_KEY", "sec_edgar": "SEC_USER_AGENT"}


class Sourced(BaseModel):
    kind: str
    symbol: str
    status: str  # historical | missing
    source: str | None = None
    retrieved_at: datetime | None = None
    cached: bool = False
    data: Any = None
    notes: list[str] = []


class MarketData:
    def __init__(
        self, s: Session, settings: Settings, providers: dict[str, MarketProvider] | None = None
    ):
        self.s = s
        self.providers = providers or {
            "massive": Massive(settings),
            "fmp": FMP(settings),
            "sec_edgar": Edgar(settings),
        }

    async def get(self, kind: str, symbol: str, **kw) -> Sourced:
        symbol = symbol.strip().upper()
        key = f"{kind}:{symbol}"
        row = self.s.get(MarketCache, key)
        if row and datetime.now(UTC) - row.retrieved_at < TTL[kind]:
            return Sourced(
                kind=kind,
                symbol=symbol,
                status="historical",
                source=row.source,
                retrieved_at=row.retrieved_at,
                cached=True,
                data=row.payload,
            )
        notes: list[str] = []
        configured = [p for p in ROUTES[kind] if self.providers[p].configured]
        if not configured:
            needed = " or ".join(ENV_FOR[p] for p in ROUTES[kind])
            return Sourced(
                kind=kind,
                symbol=symbol,
                status="missing",
                notes=[f"No provider configured for {kind}: set {needed}."],
            )
        for name in configured:
            prov = self.providers[name]
            try:
                data = await getattr(prov, kind)(symbol, **kw)
            except ProviderError as exc:
                notes.append(redact(str(exc)))
                continue
            payload = _dump(data)
            if kind == "bars" and not payload:
                notes.append(f"{name}: no bars returned")
                continue
            now = datetime.now(UTC)
            stmt = insert(MarketCache).values(
                key=key, source=name, retrieved_at=now, payload=payload
            )
            self.s.execute(
                stmt.on_conflict_do_update(
                    index_elements=["key"],
                    set_={"source": name, "retrieved_at": now, "payload": payload},
                )
            )
            self.s.commit()
            return Sourced(
                kind=kind,
                symbol=symbol,
                status="historical",
                source=name,
                retrieved_at=now,
                data=payload,
                notes=notes,
            )
        if row:  # stale cache beats nothing -- but say so
            notes.append(
                "Live fetch failed; showing cached data from "
                f"{row.retrieved_at:%Y-%m-%d %H:%M} UTC."
            )
            return Sourced(
                kind=kind,
                symbol=symbol,
                status="historical",
                source=row.source,
                retrieved_at=row.retrieved_at,
                cached=True,
                data=row.payload,
                notes=notes,
            )
        return Sourced(kind=kind, symbol=symbol, status="missing", notes=notes or ["Unavailable."])

    async def bars(self, symbol: str, days: int = 420) -> Sourced:
        end = datetime.now(UTC).date()
        return await self.get("bars", symbol, start=end - timedelta(days=days), end=end)


def _dump(data: Any) -> Any:
    if isinstance(data, list):
        return [_dump(x) for x in data]
    if isinstance(data, Bar):
        return {
            "date": data.date.isoformat(),
            "open": data.open,
            "high": data.high,
            "low": data.low,
            "close": data.close,
            "volume": data.volume,
        }
    if hasattr(data, "model_dump"):
        return data.model_dump(mode="json")
    return data


def bars_from(payload: list[dict] | None) -> list[Bar]:
    return [
        Bar(date.fromisoformat(b["date"]), b["open"], b["high"], b["low"], b["close"], b["volume"])
        for b in payload or []
    ]


def clear_cache(s: Session, symbol: str | None = None) -> int:
    q = select(MarketCache)
    if symbol:
        q = q.where(MarketCache.key.like(f"%:{symbol.upper()}"))
    rows = list(s.scalars(q))
    for r in rows:
        s.delete(r)
    s.commit()
    return len(rows)
