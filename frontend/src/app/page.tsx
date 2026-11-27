import Link from "next/link";
import { getBotOverview, type BotOrder, type BotPosition } from "@/lib/api";
import { fmtDateTime, money, num } from "@/lib/format";
import { EquityChart } from "@/components/EquityChart";
import { Code, EmptyState, PageHeader, Panel } from "@/components/ui";

const n = (v: string | null | undefined) => (v === null || v === undefined || v === "" ? null : Number(v));

function Tile({ label, value, tone, note }: { label: string; value: string | null; tone?: string; note?: string }) {
  return (
    <div className="rounded-[3px] border border-border bg-panel px-3 py-2.5">
      <div className="text-[11px] text-dim">{label}</div>
      <div className={`num mt-1.5 text-[20px] leading-none ${value === null ? "text-faint" : tone ?? ""}`}>{value ?? "—"}</div>
      {note && <div className="mt-1.5 text-[11px] text-faint">{note}</div>}
    </div>
  );
}

function Pl({ v, pctv }: { v: number | null; pctv?: number | null }) {
  if (v === null) return <span className="text-faint">—</span>;
  const cls = v > 0 ? "text-pos" : v < 0 ? "text-neg" : "text-dim";
  return (
    <span className={`num ${cls}`}>
      {money(v)}
      {pctv != null && ` (${(pctv * 100).toFixed(2)}%)`}
    </span>
  );
}

function OrdersTable({ orders, empty }: { orders: BotOrder[]; empty: string }) {
  if (!orders.length) return <div className="text-[12px] text-faint">{empty}</div>;
  return (
    <table className="w-full text-left text-[12px]">
      <thead className="text-[10px] uppercase tracking-wider text-faint">
        <tr className="border-b border-border">
          <th className="py-1.5 font-medium">Symbol</th><th className="font-medium">Side</th><th className="font-medium">Type</th>
          <th className="font-medium text-right">Qty</th><th className="font-medium text-right">Stop</th>
          <th className="font-medium text-right">Fill</th><th className="font-medium">Status</th><th className="font-medium">Time</th>
        </tr>
      </thead>
      <tbody>
        {orders.map((o) => (
          <tr key={o.id} className="border-b border-border last:border-0">
            <td className="py-1.5 font-medium">{o.symbol}</td>
            <td className={o.side === "buy" ? "text-pos" : "text-neg"}>{o.side}</td>
            <td className="text-dim">{o.type}</td>
            <td className="num text-right">{o.filled_qty && o.filled_qty !== "0" ? o.filled_qty : o.qty}</td>
            <td className="num text-right text-dim">{o.stop_price ? money(Number(o.stop_price)) : "—"}</td>
            <td className="num text-right">{o.filled_avg_price ? money(Number(o.filled_avg_price)) : "—"}</td>
            <td className="text-dim">{o.status}</td>
            <td className="text-faint">{fmtDateTime(o.filled_at ?? o.submitted_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function PositionsTable({ positions, stops }: { positions: BotPosition[]; stops: Map<string, string | null> }) {
  if (!positions.length) return <div className="text-[12px] text-faint">No open positions.</div>;
  return (
    <table className="w-full text-left text-[12px]">
      <thead className="text-[10px] uppercase tracking-wider text-faint">
        <tr className="border-b border-border">
          <th className="py-1.5 font-medium">Symbol</th><th className="font-medium text-right">Qty</th>
          <th className="font-medium text-right">Avg entry</th><th className="font-medium text-right">Price</th>
          <th className="font-medium text-right">Value</th><th className="font-medium text-right">Unrealized P/L</th>
          <th className="font-medium text-right">Protective stop</th>
        </tr>
      </thead>
      <tbody>
        {positions.map((p) => {
          const stop = stops.get(p.symbol);
          return (
            <tr key={p.symbol} className="border-b border-border last:border-0">
              <td className="py-1.5 font-medium">{p.symbol}</td>
              <td className="num text-right">{p.qty}</td>
              <td className="num text-right">{money(n(p.avg_entry_price))}</td>
              <td className="num text-right">{money(n(p.current_price))}</td>
              <td className="num text-right">{money(n(p.market_value))}</td>
              <td className="text-right"><Pl v={n(p.unrealized_pl)} pctv={n(p.unrealized_plpc)} /></td>
              <td className={`num text-right ${stop ? "text-dim" : "text-warn"}`}>{stop ? money(Number(stop)) : "missing — next run adds it"}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export default async function BotDashboard() {
  const res = await getBotOverview();
  const header = (
    <PageHeader code="BOT" title="Trading bot" subtitle="News + price-pattern bot on an Alpaca paper account (simulated money): stocks long and short during market hours, crypto around the clock. Code limits decide every order size; this page only shows what it is doing." />
  );
  if (!res.ok) {
    return (<>{header}<EmptyState title="Could not load the paper account">{res.error}</EmptyState></>);
  }
  const d = res.data;
  if (!d.configured) {
    return (
      <>
        {header}
        <Panel title="Connect the Alpaca paper account">
          <ol className="list-decimal space-y-1.5 pl-4 text-[12px] text-dim">
            <li>Sign in at alpaca.markets and switch to <span className="text-text">Paper Trading</span>.</li>
            <li>Open <span className="text-text">API Keys</span> and generate a key pair (paper keys start with <Code>PK</Code>).</li>
            <li>On your Chromebook run <Code>nano backend/.env</Code> and fill in <Code>ALPACA_API_KEY_ID</Code> and <Code>ALPACA_API_SECRET_KEY</Code>. Never paste keys into a chat.</li>
            <li>Restart ATLAS (<Code>Ctrl+C</Code>, then <Code>./scripts/run.sh</Code>) and reload this page.</li>
          </ol>
          <p className="mt-3 text-[11px] text-faint">{d.message}</p>
        </Panel>
      </>
    );
  }

  const eq = n(d.account.equity), last = n(d.account.last_equity), cash = n(d.account.cash);
  const day = eq !== null && last !== null ? eq - last : null;
  const start = d.equity_history[0]?.equity ?? null;
  const total = eq !== null && start ? ((eq - start) / start) * 100 : null;
  const stops = new Map<string, string | null>();
  d.open_orders.filter((o) => o.type.includes("stop")).forEach((o) => stops.set(o.symbol.replace("/", ""), o.stop_price));
  const s = d.plan?.summary;

  return (
    <>
      {header}
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Tile label="Equity (paper)" value={money(eq)} tone="text-sim" note={`Retrieved ${fmtDateTime(d.retrieved_at)}`} />
        <Tile label="Today" value={day === null ? null : money(day)} tone={day && day < 0 ? "text-neg" : day ? "text-pos" : ""} note="vs. previous close" />
        <Tile label="Since start" value={total === null ? null : `${total >= 0 ? "+" : ""}${total.toFixed(2)}%`} tone={total && total < 0 ? "text-neg" : total ? "text-pos" : ""} note={start ? `from ${money(start)}` : undefined} />
        <Tile label="Cash" value={money(cash)} note={s ? `Invested ${num(s.gross_exposure_pct, 0)}% of equity (max ${d.rules.max_gross_pct}%)` : undefined} />
        <Tile label="Market" value={d.clock.is_open ? "Open" : "Closed"} tone={d.clock.is_open ? "text-pos" : "text-dim"} note={d.clock.is_open ? `Closes ${fmtDateTime(d.clock.next_close)}` : `Opens ${fmtDateTime(d.clock.next_open)}`} />
      </div>

      {s && (
        <Panel title="Guardrails" className="mb-4">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-[12px]">
            <span className={`rounded-sm border px-1.5 py-[1px] text-[10px] font-medium uppercase tracking-wider ${s.new_trades_blocked ? "border-neg/50 bg-neg/10 text-neg" : "border-pos/50 bg-pos/10 text-pos"}`}>
              {s.new_trades_blocked ? "No new stock trades" : "Stock trading allowed"}
            </span>
            {s.new_trades_blocked && <span className="text-dim">{s.new_trades_blocked}</span>}
            <span className="text-dim">Today <span className="num text-text">{num(s.day_pnl_pct, 2)}%</span> (stops new trades at −{d.rules.daily_loss_cap_pct}%)</span>
            <span className="text-dim">From peak <span className="num text-text">−{num(s.drawdown_pct, 2)}%</span> (pauses at −{d.rules.drawdown_pause_pct}%)</span>
            <span className="text-dim">{s.longs} long · {s.shorts} short · crypto {money(s.crypto?.value ?? 0)}</span>
            <span className="text-dim">New trades today <span className="num text-text">{s.entries_today}</span> / {d.rules.max_new_trades_per_day}</span>
          </div>
        </Panel>
      )}

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title={`Positions (${d.positions.length})`}><PositionsTable positions={d.positions} stops={stops} /></Panel>
        <Panel title="If the bot ran now" right={<span className="text-[10px] text-faint">dry run · no orders placed</span>}>
          {d.plan_error ? (
            <div className="text-[12px] text-neg">Planner stopped: {d.plan_error}</div>
          ) : d.plan && d.plan.actions.length ? (
            <ul className="space-y-1.5 text-[12px]">
              {d.plan.actions.map((a, i) => (
                <li key={i} className="flex gap-2">
                  <span className={`num w-20 shrink-0 uppercase ${a.action.endsWith("buy") ? "text-pos" : a.action.endsWith("sell") || a.action === "short" ? "text-neg" : "text-info"}`}>{a.action.replace("_", " ")}</span>
                  <span className="w-16 shrink-0 font-medium">{a.symbol}</span>
                  <span className="text-dim">{a.qty ? `${a.qty} · ` : ""}{a.stop_price ? `stop ${money(a.stop_price)} · ` : ""}{a.reason}</span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="text-[12px] text-dim">No changes needed: every position has its stop and nothing is due to close.</div>
          )}
          <p className="mt-3 text-[11px] text-faint">{d.plan_note}</p>
        </Panel>
      </div>

      {d.equity_history.length > 1 && (
        <Panel title="Equity, last 3 months" className="mt-4">
          <EquityChart curve={d.equity_history.map((p) => ({ date: p.t, equity: p.equity }))} start={d.equity_history[0].equity} />
        </Panel>
      )}

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Panel title={`Open orders (${d.open_orders.length})`}><OrdersTable orders={d.open_orders} empty="No open orders." /></Panel>
        <Panel title="Orders, last 30 days"><OrdersTable orders={d.recent_orders} empty="No orders in the last 30 days." /></Panel>
      </div>

      {d.plan && d.plan.skipped.length > 0 && (
        <Panel title="Why each symbol was skipped" className="mt-4" right={<Link href="/bot/rules" className="text-[11px] text-dim hover:text-accent">Rules →</Link>}>
          <div className="grid gap-x-6 gap-y-1 text-[12px] md:grid-cols-2">
            {d.plan.skipped.map((k) => (
              <div key={k.symbol} className="flex gap-2"><span className="w-12 shrink-0 font-medium">{k.symbol}</span><span className="text-dim">{k.reason}</span></div>
            ))}
          </div>
        </Panel>
      )}
      <p className="mt-4 text-[11px] text-faint">Source: {d.source}. Paper account only; ATLAS has no live-trading connection. Not financial advice.</p>
    </>
  );
}
