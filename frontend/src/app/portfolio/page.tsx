import Link from "next/link";
import { getPaper } from "@/lib/api";
import { fmtDateTime, money, num, pct } from "@/lib/format";
import { paperJournal, paperReset, paperTrade } from "@/app/markets-actions";
import { EquityChart } from "@/components/EquityChart";
import { EmptyState, PageHeader, Panel } from "@/components/ui";

export default async function PortfolioPage({ searchParams }: { searchParams: Promise<{ msg?: string; symbol?: string }> }) {
  const params = await searchParams;
  const res = await getPaper();
  return (
    <>
      <PageHeader code="PPF" title="Paper Portfolio"
        subtitle="Practice trading with virtual money. No brokerage connection exists and no real orders are ever placed. Results are kept separate from business revenue."
        right={<span className="rounded-sm border border-sim/60 bg-sim/10 px-2 py-1 text-[11px] font-medium uppercase tracking-wider text-sim">Simulated</span>} />
      {params.msg && <div className="mb-4 rounded-sm border border-sim/40 bg-sim/5 px-3 py-2 text-[12px]">{params.msg}</div>}
      {!res.ok ? <EmptyState title="Unavailable">{res.error}</EmptyState> : (() => {
        const p = res.data;
        return (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
              {[
                ["Simulated equity", p.equity === null ? null : money(p.equity)],
                ["Virtual cash", money(p.cash)],
                ["Positions value", money(p.market_value)],
                ["Total return", p.total_return_pct === null ? null : pct(p.total_return_pct, true)],
                ["Realized P&L", money(p.realized_pl)],
              ].map(([k, v]) => (
                <div key={k} className="rounded-[3px] border border-sim/30 bg-panel px-3 py-2.5">
                  <div className="flex justify-between text-[11px] text-dim"><span>{k}</span><span className="num text-[10px] uppercase text-sim">● simulated</span></div>
                  <div className={`num mt-1.5 text-[20px] leading-none ${v === null ? "text-faint" : ""}`}>{v ?? "—"}</div>
                </div>
              ))}
            </div>
            {p.missing_prices.length > 0 && <div className="text-[12px] text-warn">⚠ No current price for {p.missing_prices.join(", ")}: equity and return are unknown until prices are available.</div>}

            <div className="grid gap-4 xl:grid-cols-[1fr_320px]">
              <Panel title="Simulated equity">
                {p.equity_curve.length > 1 ? <EquityChart curve={p.equity_curve} start={p.account.starting_cash} />
                  : <div className="text-[12px] text-faint">The curve appears after trades span at least two price dates.</div>}
              </Panel>
              <Panel title="New simulated trade">
                <form action={paperTrade} className="space-y-2 text-[12px]">
                  <div className="flex gap-2">
                    <input name="symbol" required defaultValue={params.symbol ?? ""} placeholder="Ticker" aria-label="Ticker" className="num w-24 rounded-sm border border-border-strong bg-panel-2 px-2 py-1 uppercase placeholder:normal-case placeholder:text-faint" />
                    <select name="side" aria-label="Side" className="rounded-sm border border-border-strong bg-panel-2 px-2 py-1"><option value="buy">Buy</option><option value="sell">Sell</option></select>
                    <input name="quantity" required inputMode="decimal" placeholder="Qty" aria-label="Quantity" className="num w-20 rounded-sm border border-border-strong bg-panel-2 px-2 py-1 placeholder:text-faint" />
                  </div>
                  <textarea name="thesis" rows={2} maxLength={2000} placeholder="Why? (trade journal)" aria-label="Trade thesis" className="w-full rounded-sm border border-border-strong bg-panel-2 px-2 py-1 placeholder:text-faint" />
                  <button className="w-full rounded-sm border border-sim px-3 py-1 text-sim hover:bg-sim/10">Place simulated trade</button>
                  <p className="text-[11px] text-faint">Fills at the latest end-of-day close from your data provider; the price source and date are recorded. Long only, no margin.</p>
                </form>
              </Panel>
            </div>

            <Panel title="Positions (simulated)">
              {p.positions.length === 0 ? <div className="text-[12px] text-faint">No open positions.</div> : (
                <table className="w-full text-left text-[12px]">
                  <thead className="text-[10px] uppercase tracking-wider text-faint"><tr className="border-b border-border"><th className="py-1.5">Symbol</th><th>Qty</th><th>Avg cost</th><th>Price</th><th>Value</th><th>Unrealized P&amp;L</th></tr></thead>
                  <tbody>{p.positions.map((x) => (
                    <tr key={x.symbol} className="border-b border-border last:border-0">
                      <td className="py-1.5"><Link href={`/research?symbol=${x.symbol}`} className="num font-medium hover:text-accent">{x.symbol}</Link></td>
                      <td className="num">{num(x.quantity, 4)}</td><td className="num">{money(x.avg_cost)}</td>
                      <td className="num">{x.price === null ? "—" : money(x.price)}<div className="text-[10px] text-faint">{x.price_as_of ?? ""}</div></td>
                      <td className="num">{money(x.market_value) ?? "—"}</td>
                      <td className={`num ${x.unrealized_pl === null ? "" : x.unrealized_pl >= 0 ? "text-pos" : "text-neg"}`}>{x.unrealized_pl === null ? "—" : `${money(x.unrealized_pl)} (${pct(x.unrealized_pl_pct, true)})`}</td>
                    </tr>
                  ))}</tbody>
                </table>
              )}
            </Panel>

            <Panel title="Trade journal (simulated fills)">
              {p.trades.length === 0 ? <div className="text-[12px] text-faint">No trades yet.</div> : (
                <ul className="space-y-2">
                  {p.trades.map((t) => (
                    <li key={t.id} className="rounded-sm border border-border px-3 py-2 text-[12px]">
                      <div className="flex flex-wrap justify-between gap-2">
                        <span><span className={t.side === "buy" ? "text-pos" : "text-neg"}>{t.side.toUpperCase()}</span> <span className="num">{num(t.quantity, 4)} {t.symbol} @ {money(t.price)}</span></span>
                        <span className="text-[11px] text-faint">{t.price_source} · recorded {fmtDateTime(t.executed_at)}</span>
                      </div>
                      {t.thesis && <div className="mt-1 text-dim">Thesis: {t.thesis}</div>}
                      <form action={paperJournal} className="mt-1 flex gap-2">
                        <input type="hidden" name="id" value={t.id} />
                        <input name="lesson" defaultValue={t.lesson ?? ""} maxLength={2000} placeholder="Lesson learned (optional)" aria-label="Lesson learned" className="flex-1 rounded-sm border border-border bg-panel-2 px-2 py-0.5 text-[11px] placeholder:text-faint" />
                        <button className="text-[11px] text-dim hover:text-text">Save</button>
                      </form>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>

            <Panel title="Reset simulated portfolio">
              <form action={paperReset} className="flex flex-wrap items-center gap-2 text-[12px]">
                <span className="text-dim">Starting virtual cash</span>
                <input name="starting_cash" required inputMode="decimal" defaultValue={p.account.starting_cash} aria-label="Starting virtual cash" className="num w-32 rounded-sm border border-border-strong bg-panel-2 px-2 py-1" />
                <button className="rounded-sm border border-neg/50 px-2 py-1 text-neg">Reset (deletes simulated trades)</button>
              </form>
            </Panel>
          </div>
        );
      })()}
    </>
  );
}
