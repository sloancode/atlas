import { apiGet, type BotRules } from "@/lib/api";
import { EmptyState, PageHeader, Panel } from "@/components/ui";

export default async function Rules() {
  const res = await apiGet<BotRules>("/api/bot/rules");
  if (!res.ok) return <EmptyState title="Could not load the rules">{res.error}</EmptyState>;
  const r = res.data;
  const row = (k: string, v: string) => (
    <tr key={k} className="border-b border-border last:border-0"><td className="py-1.5 pr-4 text-dim">{k}</td><td>{v}</td></tr>
  );
  return (
    <>
      <PageHeader code="RUL" title="Rules & limits" subtitle="Fixed in code (backend/app/services/trading). The scheduled bot places exactly the orders these rules produce, and nothing else." />
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Strategy: trend-following swing">
          <table className="w-full text-left text-[12px]"><tbody>
            {row("Market filter", `New buys only while ${r.benchmark} is above its ${r.slow}-day average`)}
            {row("Uptrend", `Price > ${r.fast}-day avg > ${r.slow}-day avg, and the ${r.fast}-day avg is higher than ${r.slope_lookback} sessions ago`)}
            {row("Strength", `~6-month (${r.rs_window}-session) return beats ${r.benchmark}'s; strongest first`)}
            {row("Near highs", `Within ${r.max_below_high_pct}% of its high`)}
            {row("Exit 1", `Protective stop ${r.stop_loss_pct}% below the average entry price, held at the broker`)}
            {row("Exit 2", `Price below its ${r.fast}-day average, checked only from ${r.trend_exit_hour_et}:00 ET`)}
          </tbody></table>
        </Panel>
        <Panel title="Risk limits (moderate)">
          <table className="w-full text-left text-[12px]"><tbody>
            {row("Per position", `≤ ${r.max_position_pct}% of equity at entry, whole shares`)}
            {row("Positions", `≤ ${r.max_positions}`)}
            {row("New buys per day", `≤ ${r.max_new_buys_per_day}`)}
            {row("Cooldown", `${r.cooldown_days} days before re-buying a sold symbol`)}
            {row("Drawdown pause", `No new buys while equity is ≥ ${r.drawdown_pause_pct}% below its peak`)}
            {row("Margin / shorting", `${r.allow_margin ? "allowed" : "never"} / ${r.allow_short ? "allowed" : "never"}`)}
            {row("Account", "Alpaca paper only; refuses any non-paper account")}
          </tbody></table>
        </Panel>
      </div>
      <Panel title={`Universe (${r.universe.length})`} className="mt-4">
        <div className="num flex flex-wrap gap-1.5 text-[12px]">
          {r.universe.map((s) => <span key={s} className="rounded-sm border border-border bg-panel-2 px-1.5 py-[1px]">{s}</span>)}
        </div>
      </Panel>
      <p className="mt-4 text-[11px] text-faint">Rules are unit-tested, not backtested: nothing here promises profits. Not financial advice.</p>
    </>
  );
}
