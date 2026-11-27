import { getBotJournal } from "@/lib/api";
import { fmtDateTime, money } from "@/lib/format";
import { EmptyState, PageHeader, Panel } from "@/components/ui";

export default async function RunLog() {
  const res = await getBotJournal(100);
  return (
    <>
      <PageHeader code="LOG" title="Run log" subtitle="Every plan the bot's planner produced on this machine, newest first: the guardrails, what it decided, and why." />
      {!res.ok ? (
        <EmptyState title="Could not load the run log">{res.error}</EmptyState>
      ) : res.data.length === 0 ? (
        <EmptyState title="No runs recorded on this computer yet">
          The scheduled bot runs in a Claude cloud session and reports each run there. Plans appear here when the planner runs on this computer.
          The dashboard always shows a live dry run.
        </EmptyState>
      ) : (
        <div className="space-y-3">
          {res.data.map((r, i) => (
            <Panel key={i} title={fmtDateTime(r.planned_at)} right={<span className={`text-[10px] uppercase tracking-wider ${r.summary.new_trades_blocked ? "text-neg" : "text-pos"}`}>{r.summary.new_trades_blocked ? "no new stock trades" : "stock trading allowed"}</span>}>
              <div className="text-[12px] text-dim">
                Equity <span className="num text-text">{money(r.summary.equity)}</span> · today {r.summary.day_pnl_pct?.toFixed(2)}% · {r.summary.longs ?? 0} long, {r.summary.shorts ?? 0} short · {r.summary.candidates_scanned ?? 0} stocks scanned · {r.skipped.length} skipped
              </div>
              {r.actions.length ? (
                <ul className="mt-2 space-y-1 text-[12px]">
                  {r.actions.map((a, j) => (
                    <li key={j}><span className="num uppercase text-info">{a.action.replace("_", " ")}</span> <span className="font-medium">{a.symbol}</span> <span className="text-dim">{a.qty ? `${a.qty} · ` : ""}{a.reason}</span></li>
                  ))}
                </ul>
              ) : (
                <div className="mt-2 text-[12px] text-faint">No orders.</div>
              )}
            </Panel>
          ))}
        </div>
      )}
    </>
  );
}
