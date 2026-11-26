import Link from "next/link";
import { getBotRules } from "@/lib/api";
import { fmtET, money } from "@/lib/format";
import { BotTabs, PaperBadge } from "@/components/bot";
import { Code, EmptyState, PageHeader, Panel } from "@/components/ui";

const STATUS: Record<string, { label: string; cls: string }> = {
  buy: { label: "Bought", cls: "text-pos" },
  sell: { label: "Sold", cls: "text-neg" },
  signal: { label: "Signal", cls: "text-info" },
  held: { label: "Held", cls: "text-accent" },
  no: { label: "No", cls: "text-faint" },
};

export default async function BotRulesPage() {
  const res = await getBotRules();
  return (
    <>
      <PageHeader
        code="BRL"
        title="Trading Bot · Rules"
        subtitle="The fixed rules the planner applies every run. They are code, not AI judgment, and they are the same rules that produce the run log."
        right={<PaperBadge />}
      />
      <BotTabs current="/bot/rules" />
      {!res.ok ? (
        <EmptyState title="Unavailable">{res.error}</EmptyState>
      ) : (() => {
        const d = res.data;
        const ev = d.latest_evaluation;
        const s = ev?.summary;
        return (
          <div className="space-y-4">
            <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
              <Panel title={`${d.strategy} rules`} right={<span className="text-[11px] text-faint">source: <Code>{d.source}</Code></span>}>
                <table className="w-full text-left text-[12px]">
                  <tbody>
                    {d.rules.map((r) => (
                      <tr key={r.key} className="border-b border-border last:border-0">
                        <td className="w-32 py-1.5 pr-3 align-top text-[11px] uppercase tracking-wider text-faint">{r.group}</td>
                        <td className="py-1.5">{r.rule}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="mt-2 text-[11px] text-faint">Risk limits (position size, max positions, drawdown pause, cooldown) are on the <Link href="/bot/settings" className="text-accent hover:underline">Settings</Link> tab.</p>
              </Panel>
              <Panel title="Market filter, latest run">
                {!ev || !s ? (
                  <div className="text-[12px] text-faint">No run logged yet.</div>
                ) : (
                  <div className="space-y-1.5 text-[12px]">
                    <div className={`text-[16px] font-medium ${s.regime === "on" ? "text-pos" : "text-warn"}`}>
                      {s.regime === "on" ? "On: new buys allowed" : "Off: no new buys"}
                    </div>
                    <div className="num text-dim">
                      {d.benchmark} {money(s[`${d.benchmark.toLowerCase()}_last`] as number | undefined) ?? "—"}
                      {" vs 200-day "}
                      {money(s[`${d.benchmark.toLowerCase()}_sma200`] as number | undefined) ?? "—"}
                    </div>
                    {s.buys_paused && <div className="text-warn">Drawdown pause active</div>}
                    <div className="text-[11px] text-faint">Run at {fmtET(ev.planned_at)}</div>
                  </div>
                )}
              </Panel>
            </div>

            <Panel
              title={`Universe (${d.universe.length}) · how each symbol scored in the latest run`}
              right={ev ? <span className="text-[11px] text-faint">{fmtET(ev.planned_at)}</span> : undefined}
            >
              {!ev ? (
                <>
                  <div className="mb-2 text-[12px] text-faint">No run logged yet, so there is no evaluation to show. The symbols the bot may buy:</div>
                  <div className="num flex flex-wrap gap-1.5 text-[12px]">
                    {d.universe.map((u) => <span key={u} className="rounded-sm border border-border px-1.5 py-0.5">{u}</span>)}
                  </div>
                </>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-[12px]">
                    <thead className="text-[10px] uppercase tracking-wider text-faint">
                      <tr className="border-b border-border"><th className="py-1.5 pr-3">Symbol</th><th className="pr-3">Result</th><th>Reason</th></tr>
                    </thead>
                    <tbody>
                      {ev.symbols.map((r) => (
                        <tr key={r.symbol} className="border-b border-border last:border-0">
                          <td className="py-1.5 pr-3"><Link href={`/research?symbol=${r.symbol}`} className="num font-medium hover:text-accent">{r.symbol}</Link></td>
                          <td className={`pr-3 ${STATUS[r.status]?.cls ?? ""}`}>{STATUS[r.status]?.label ?? r.status}</td>
                          <td className="text-dim">{r.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Panel>
          </div>
        );
      })()}
    </>
  );
}
