import Link from "next/link";
import { getResearchReports, getSnapshot, getWatchlists, type Snapshot, type ResearchAI } from "@/lib/api";
import { fmtDate, fmtDateTime, num, pct } from "@/lib/format";
import { addToWatchlist, generateResearchAI } from "@/app/markets-actions";
import { PriceChart } from "@/components/PriceChart";
import { DataStatusTag, EmptyState, PageHeader, Panel } from "@/components/ui";

const big = (v: unknown) => {
  if (typeof v !== "number") return "—";
  const a = Math.abs(v);
  return a >= 1e12 ? `${(v / 1e12).toFixed(2)}T` : a >= 1e9 ? `${(v / 1e9).toFixed(2)}B` : a >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : num(v, 2) ?? "—";
};
const SECTION_LABEL: Record<string, string> = {
  business_overview: "Business overview", competitive_position: "Competitive position", financial_health: "Financial health",
  growth_opportunities: "Growth opportunities", major_risks: "Major risks", valuation: "Valuation", recent_news: "Recent news",
  technical_analysis: "Technical analysis", bull_case: "Bull case", bear_case: "Bear case", investment_thesis: "Investment thesis",
  events_to_monitor: "Events to monitor",
};

export default async function ResearchPage({ searchParams }: { searchParams: Promise<{ symbol?: string; msg?: string }> }) {
  const params = await searchParams;
  const symbol = (params.symbol ?? "").trim().toUpperCase();
  const [snap, reports, lists] = symbol
    ? await Promise.all([getSnapshot(symbol), getResearchReports(symbol), getWatchlists()])
    : [null, null, null];
  return (
    <>
      <PageHeader code="RSH" title="Stock Research"
        subtitle="Research US stocks and ETFs from your configured data providers. Research only, not investment advice; you make every decision." />
      <form action="/research" method="get" className="mb-4 flex gap-2">
        <input name="symbol" defaultValue={symbol} placeholder="Ticker, e.g. AAPL or SPY" aria-label="Ticker symbol"
          className="num w-56 rounded-sm border border-border-strong bg-panel px-2.5 py-1.5 uppercase placeholder:normal-case placeholder:text-faint" />
        <button className="rounded-sm border border-accent px-3 py-1.5 text-[12px] text-accent hover:bg-accent-dim">Research</button>
      </form>
      {params.msg && <div className="mb-4 rounded-sm border border-border-strong bg-panel-2 px-3 py-2 text-[12px]">{params.msg}</div>}
      {!symbol ? (
        <EmptyState title="Enter a ticker to start">
          Needs a market data provider: MASSIVE_API_KEY or FMP_API_KEY for prices, and FMP_API_KEY or SEC_USER_AGENT (free) for financials.
        </EmptyState>
      ) : !snap!.ok ? (
        <EmptyState title="Research unavailable">{snap!.error}</EmptyState>
      ) : (
        <SnapshotView s={snap!.data} ai={reports && reports.ok ? reports.data[0]?.report ?? null : null}
          lists={lists && lists.ok ? lists.data : []} />
      )}
    </>
  );
}

function SnapshotView({ s, ai, lists }: { s: Snapshot; ai: ResearchAI | null; lists: { id: number; name: string }[] }) {
  const t = s.technicals;
  const f = s.fundamentals;
  const p = s.profile;
  const noPrices = s.data_status.prices.status === "missing";
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="num text-[11px] text-accent">{s.symbol}{s.is_etf ? " · ETF" : ""}</div>
          <h2 className="text-xl font-semibold">{(p.name as string) ?? s.symbol}</h2>
          <div className="text-[12px] text-dim">{[p.sector, p.industry, p.exchange].filter(Boolean).join(" · ") || "Profile unavailable"}</div>
        </div>
        <div className="text-right">
          <div className="num text-[26px] leading-none">{t.close === null ? "—" : num(t.close, 2)}</div>
          <div className="text-[11px] text-faint">{s.price.as_of ? `Close ${fmtDate(s.price.as_of)} · end-of-day, not real-time` : "No price data"}</div>
        </div>
      </div>

      <div className="rounded-sm border border-border bg-panel px-3 py-2 text-[11px]">
        <div className="flex flex-wrap gap-x-5 gap-y-1">
          {Object.entries(s.data_status).map(([k, v]) => (
            <span key={k} title={v.notes.join(" ")}>
              <span className="text-dim">{k}: </span>
              <DataStatusTag status={v.status} />
              {v.source && <span className="text-faint"> {v.source}{v.cached ? " (cached)" : ""}</span>}
            </span>
          ))}
        </div>
        {Object.values(s.data_status).flatMap((v) => v.notes).slice(0, 4).map((n) => (
          <div key={n} className="mt-1 text-warn">⚠ {n}</div>
        ))}
      </div>

      {noPrices ? (
        <EmptyState title="No price data">Configure MASSIVE_API_KEY or FMP_API_KEY in backend/.env. ATLAS never shows sample prices.</EmptyState>
      ) : (
        <Panel title="Price (daily close)" right={<span className="text-[11px] text-faint">{t.sessions} sessions</span>}>
          <PriceChart chart={s.chart} symbol={s.symbol} />
        </Panel>
      )}

      <div className="grid gap-4 xl:grid-cols-3">
        <Panel title="Technicals">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[12px]">
            {[
              ["Trend", t.trend], ["RSI (14)", num(t.rsi14, 1)], ["SMA 50", num(t.sma50, 2)], ["SMA 200", num(t.sma200, 2)],
              ["MACD", num(t.macd, 3)], ["MACD signal", num(t.macd_signal, 3)], ["ATR (14)", num(t.atr14, 2)],
              ["Volatility 60d", pct(t.volatility_60d)], ["52w high", num(t.high_52w, 2)], ["From 52w high", pct(t.pct_from_52w_high, true)],
            ].map(([k, v]) => (<div key={k as string} className="contents"><dt className="text-dim">{k}</dt><dd className="num text-right">{v ?? "—"}</dd></div>))}
          </dl>
          <div className="mt-2 text-[11px] text-faint">{t.trend_reason}</div>
        </Panel>
        <Panel title="Returns & relative strength">
          <table className="w-full text-[12px]">
            <thead className="text-[10px] uppercase text-faint"><tr><th className="text-left">Window</th><th className="text-right">Return</th><th className="text-right">vs SPY</th></tr></thead>
            <tbody>{["1m", "3m", "6m", "12m"].map((w) => (
              <tr key={w}><td className="py-0.5">{w}</td><td className="num text-right">{pct(t.returns[w], true) ?? "—"}</td>
                <td className="num text-right">{t.relative_strength[w] === undefined || t.relative_strength[w] === null ? "—" : `${t.relative_strength[w]! > 0 ? "+" : ""}${t.relative_strength[w]} pts`}</td></tr>
            ))}</tbody>
          </table>
          <div className="mt-3 text-[11px] text-dim">Support / resistance <span className="text-faint">(estimates)</span></div>
          <div className="num text-[12px]">
            S: {t.support_resistance.support.map((l) => l.level).join(", ") || "—"} · R: {t.support_resistance.resistance.map((l) => l.level).join(", ") || "—"}
          </div>
          <div className="text-[10px] text-faint">{t.support_resistance.method}</div>
        </Panel>
        <Panel title="Fundamentals">
          {!f ? (
            <div className="text-[12px] text-faint">{s.is_etf ? "Not applicable to ETFs." : "Unavailable."}</div>
          ) : (
            <>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[12px]">
                {[
                  ["Fiscal year", f.fiscal_year === null ? null : String(f.fiscal_year)], ["Revenue", big(f.revenue)], ["Revenue growth", pct(f.revenue_growth_pct, true)],
                  ["Earnings growth", pct(f.earnings_growth_pct, true)], ["Free cash flow", big(f.free_cash_flow)],
                  ["FCF margin", pct(f.fcf_margin_pct)], ["Cash", big(f.cash)], ["Total debt", big(f.total_debt)],
                  ["Debt / equity", num(f.debt_to_equity, 2)], ["Market cap", big(f.market_cap)],
                  ["P/E", num(f.pe, 1)], ["P/S", num(f.ps, 1)], ["FCF yield", pct(f.fcf_yield_pct)],
                ].map(([k, v]) => (<div key={k as string} className="contents"><dt className="text-dim">{k}</dt><dd className="num text-right">{(v as string) ?? "—"}</dd></div>))}
              </dl>
              {f.notes.map((n) => <div key={n} className="mt-1 text-[11px] text-warn">⚠ {n}</div>)}
              {f.market_cap_source && f.market_cap_source !== "provider" && <div className="mt-1 text-[11px] text-faint">Market cap: {f.market_cap_source}</div>}
            </>
          )}
        </Panel>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Panel title="Earnings">
          {s.earnings.upcoming.length || s.earnings.recent.length ? (
            <ul className="space-y-1 text-[12px]">
              {s.earnings.upcoming.map((e) => <li key={e.date} className="text-accent">Next: {fmtDate(e.date)}{e.eps_estimate !== null && ` · est. EPS ${e.eps_estimate}`}</li>)}
              {s.earnings.recent.slice().reverse().map((e) => <li key={e.date} className="text-dim">{fmtDate(e.date)} · EPS {e.eps_actual ?? "—"} vs est. {e.eps_estimate ?? "—"}</li>)}
            </ul>
          ) : <div className="text-[12px] text-faint">Earnings data unavailable (needs FMP_API_KEY).</div>}
        </Panel>
        <Panel title="Recent news" className="xl:col-span-2">
          {s.news.length ? (
            <ul className="space-y-1.5 text-[12px]">
              {s.news.map((n) => (
                <li key={(n.url ?? "") + n.title}>
                  {n.url ? <a href={n.url} target="_blank" rel="noopener noreferrer nofollow" className="hover:text-accent">{n.title}</a> : n.title}
                  <span className="text-[11px] text-faint"> · {n.publisher ?? "unknown source"} · {fmtDateTime(n.published)}</span>
                </li>
              ))}
            </ul>
          ) : <div className="text-[12px] text-faint">No news available from the configured providers.</div>}
        </Panel>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Panel title="Events to monitor">
          {s.events_to_monitor.length ? <ul className="list-disc space-y-1 pl-4 text-[12px] text-dim">{s.events_to_monitor.map((e) => <li key={e}>{e}</li>)}</ul>
            : <div className="text-[12px] text-faint">Nothing identified from the available data.</div>}
        </Panel>
        <Panel title="Watch / simulate" className="xl:col-span-2">
          <div className="flex flex-wrap items-center gap-3 text-[12px]">
            {lists.length ? (
              <form action={addToWatchlist} className="flex items-center gap-2">
                <input type="hidden" name="symbol" value={s.symbol} />
                <input type="hidden" name="return_to" value={`/research?symbol=${s.symbol}`} />
                <select name="watchlist_id" aria-label="Watchlist" className="rounded-sm border border-border-strong bg-panel-2 px-2 py-1">
                  {lists.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
                </select>
                <button className="rounded-sm border border-border-strong px-2 py-1 text-dim hover:text-text">Add to watchlist</button>
              </form>
            ) : <Link href="/watchlists" className="text-accent hover:underline">Create a watchlist</Link>}
            <Link href={`/portfolio?symbol=${s.symbol}`} className="rounded-sm border border-sim/50 px-2 py-1 text-sim">Paper trade (simulated)</Link>
          </div>
        </Panel>
      </div>

      <Panel title="AI research note (Claude) — labeled and verified"
        right={<form action={generateResearchAI}><input type="hidden" name="symbol" value={s.symbol} />
          <button className="text-[11px] text-accent hover:underline">{ai ? "Regenerate" : "Generate"}</button></form>}>
        {!ai ? (
          <div className="text-[12px] text-faint">Not generated. Needs ANTHROPIC_API_KEY; uses only the data shown above.</div>
        ) : (
          <div className="space-y-3">
            <p className="text-[13px]">{ai.summary}</p>
            <div className="text-[11px] text-faint">{ai.verification.verified} verified · {ai.verification.unverified} unverified · {ai.model} · prices as of {ai.price_as_of ?? "—"} · generated {fmtDateTime(ai.generated_at)}</div>
            <div className="grid gap-3 lg:grid-cols-2">
              {Object.entries(ai.sections).map(([key, items]) => (
                <div key={key} className="rounded-sm border border-border px-3 py-2">
                  <div className="mb-1 text-[11px] uppercase tracking-wider text-dim">{SECTION_LABEL[key] ?? key}</div>
                  {items.length ? items.map((it, i) => (
                    <div key={i} className="mb-1 text-[12px]">
                      <span className={`mr-1 text-[10px] uppercase ${it.type === "fact" ? "text-pos" : it.type === "estimate" ? "text-warn" : "text-info"}`}>[{it.type}]</span>
                      {it.text} {!it.verified && <span className="text-[10px] text-neg" title={it.issues.join(" ")}>⚠ unverified</span>}
                    </div>
                  )) : <div className="text-[12px] text-faint">No content.</div>}
                </div>
              ))}
            </div>
          </div>
        )}
      </Panel>
      <p className="text-[11px] text-faint">{s.disclaimer}</p>
    </div>
  );
}
