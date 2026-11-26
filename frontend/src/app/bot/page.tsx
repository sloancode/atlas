import { getBotRuns, type BotRun } from "@/lib/api";
import { fmtET, money, pct } from "@/lib/format";
import { ActionLabel, BotTabs, BrokerError, OrdersTable, PaperBadge } from "@/components/bot";
import { Code, EmptyState, PageHeader, Panel } from "@/components/ui";

function RunCard({ run }: { run: BotRun }) {
  const s = run.summary;
  const acted = run.actions.length > 0;
  const signals = run.skipped.filter((x) => x.reason.startsWith("signal OK"));
  return (
    <li className="rounded-sm border border-border px-3 py-2 text-[12px]">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-3">
          <span className="font-medium">{fmtET(run.planned_at)}</span>
          <span className={s.regime === "on" ? "text-pos" : "text-warn"}>
            Market filter {s.regime === "on" ? "on" : "off"}
          </span>
          {s.buys_paused && <span className="text-warn">Buys paused (drawdown)</span>}
          {s.trend_exits_evaluated && <span className="text-dim">End-of-day exits checked</span>}
        </div>
        <div className="num flex gap-3 text-[11px] text-dim">
          <span>Equity {money(s.equity) ?? "—"}</span>
          <span>Cash {money(s.cash) ?? "—"}</span>
          <span>Drawdown {pct(s.drawdown_pct) ?? "—"}</span>
          <span>{s.positions ?? 0} positions</span>
        </div>
      </div>
      {acted ? (
        <ul className="mt-2 space-y-1">
          {run.actions.map((a, i) => (
            <li key={`${a.symbol}-${a.action}-${i}`} className="flex flex-wrap gap-2">
              <span className="w-12"><ActionLabel action={a.action} /></span>
              <span className="num w-28 font-medium">
                {a.qty ? `${a.qty} ` : ""}
                {a.symbol}
                {a.stop_price ? ` @ ${a.stop_price}` : ""}
              </span>
              <span className="text-dim">{a.reason}</span>
            </li>
          ))}
        </ul>
      ) : (
        <div className="mt-1.5 text-dim">No orders. {signals.length === 0 ? "No symbol passed the entry rules." : ""}</div>
      )}
      {signals.length > 0 && (
        <div className="mt-1.5 text-[11px] text-faint">
          Passed the rules but not bought: {signals.map((x) => `${x.symbol} (${x.reason.replace("signal OK, but ", "")})`).join("; ")}
        </div>
      )}
      <details className="mt-1.5 text-[11px]">
        <summary className="cursor-pointer text-faint hover:text-dim">
          Why each other symbol was skipped ({run.skipped.length})
        </summary>
        <ul className="mt-1 grid gap-x-4 gap-y-0.5 md:grid-cols-2">
          {run.skipped.map((x) => (
            <li key={x.symbol}><span className="num text-dim">{x.symbol}</span> <span className="text-faint">{x.reason}</span></li>
          ))}
        </ul>
      </details>
    </li>
  );
}

export default async function BotRunLogPage() {
  const res = await getBotRuns(50);
  return (
    <>
      <PageHeader
        code="BOT"
        title="Trading Bot · Run Log"
        subtitle="What each scheduled run decided, and what the Alpaca paper account actually did. Paper money only; ATLAS itself never places orders."
        right={<PaperBadge />}
      />
      <BotTabs current="/bot" />
      {!res.ok ? (
        <EmptyState title="Unavailable">{res.error}</EmptyState>
      ) : (
        <div className="space-y-4">
          <Panel
            title="Orders at Alpaca (paper)"
            right={<span className="text-[11px] text-faint">latest 100 · source: Alpaca</span>}
          >
            <BrokerError error={res.data.broker.error} />
            {res.data.broker.configured && !res.data.broker.error && (
              <OrdersTable orders={res.data.orders} empty="No orders on the paper account yet." />
            )}
          </Panel>
          <Panel
            title="Planner runs"
            right={
              <span className="text-[11px] text-faint">
                {res.data.journal.total} logged · source: <Code>{res.data.journal.path}</Code>
              </span>
            }
          >
            {res.data.journal.unreadable > 0 && (
              <div className="mb-2 text-[12px] text-warn">⚠ {res.data.journal.unreadable} journal line(s) could not be read and are not shown.</div>
            )}
            {res.data.runs.length === 0 ? (
              <EmptyState title="No runs logged yet">
                Each scheduled run appends its plan to the journal. Runs happen every trading hour (9:41–15:41 ET) and skip when the market is closed.
              </EmptyState>
            ) : (
              <ul className="space-y-2">
                {res.data.runs.map((r, i) => <RunCard key={`${r.planned_at}-${i}`} run={r} />)}
              </ul>
            )}
          </Panel>
        </div>
      )}
    </>
  );
}
