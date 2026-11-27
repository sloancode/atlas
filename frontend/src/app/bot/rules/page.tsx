import { apiGet, type BotRules } from "@/lib/api";
import { EmptyState, PageHeader, Panel } from "@/components/ui";

export default async function Rules() {
  const res = await apiGet<BotRules>("/api/bot/rules");
  if (!res.ok) return <EmptyState title="Could not load the rules">{res.error}</EmptyState>;
  const r = res.data;
  const row = (k: string, v: string) => (
    <tr key={k} className="border-b border-border last:border-0"><td className="py-1.5 pr-4 align-top text-dim">{k}</td><td>{v}</td></tr>
  );
  return (
    <>
      <PageHeader code="RUL" title="Rules & limits" subtitle="Fixed in code (backend/app/services/trading). Each run reads the news, then the code checks the price and sizes every order. The scheduled bot places exactly the orders the code produces, and nothing else." />
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Stocks: news + price patterns (market hours)">
          <table className="w-full text-left text-[12px]"><tbody>
            {row("Which stocks", `Any US stock in the run's scan (most active, biggest movers, in the news) priced ≥ $${r.min_price} and actively traded`)}
            {row("News", "Each run scores the last hour's headlines per stock from −2 (very bad) to +2 (very good)")}
            {row("Price checks", `Above/below today's average price (VWAP) and open; moved ≥ ${r.gap_pct}% from yesterday; broke its ${r.breakout_days}-day high/low; volume ≥ ${r.rel_volume}× normal`)}
            {row("Buy", `Good news and ≥ ${r.news_pattern_points} of 5 rising checks, or no news and all ${r.momentum_pattern_points}`)}
            {row("Short", `Bad news and ≥ ${r.news_pattern_points} of 5 falling checks, or no news and all ${r.momentum_pattern_points}; only stocks Alpaca marks easy to borrow`)}
            {row("Exits", `Stop ${r.stop_atr_mult}× daily range away (${r.min_stop_pct}–${r.max_stop_pct}%) and profit target at ${r.target_r}× that, both held at Alpaca; news turns against it; or after ${r.max_hold_days} days unless up ${r.stale_min_gain_pct}%`)}
            {row("Hours", `New stock trades ${r.first_entry_et}–${r.last_entry_et} ET`)}
          </tbody></table>
        </Panel>
        <Panel title="Crypto: around the clock">
          <table className="w-full text-left text-[12px]"><tbody>
            {row("Buy", `Hourly price above its ${r.crypto_ema_fast}- and ${r.crypto_ema_slow}-hour averages, plus a new ${r.crypto_breakout_bars}-hour high or good news; not after a ${r.crypto_max_24h_gain_pct}%+ day`)}
            {row("Exits", `Stop ${r.crypto_stop_atr_mult}× hourly range below entry (${r.crypto_min_stop_pct}–${r.crypto_max_stop_pct}%); price falls below its ${r.crypto_ema_fast}-hour average; bad news`)}
            {row("Size", `≤ ${r.crypto_max_position_pct}% of equity per coin, ≤ ${r.crypto_max_total_pct}% in crypto, paid from cash (no shorting or margin for crypto)`)}
            {row("Coins", r.crypto_pairs.join(", "))}
          </tbody></table>
        </Panel>
        <Panel title="Risk limits (whole account)">
          <table className="w-full text-left text-[12px]"><tbody>
            {row("Risk per trade", `About ${r.risk_per_trade_pct}% of equity if the stop is hit (gaps can lose more)`)}
            {row("Per stock", `≤ ${r.max_position_pct}% of equity`)}
            {row("Total invested", `≤ ${r.max_gross_pct}% of equity, longs + shorts (uses margin)`)}
            {row("Positions / new trades", `≤ ${r.max_positions} open, ≤ ${r.max_new_trades_per_day} new per day`)}
            {row("Daily loss cap", `No new trades for the rest of the day after losing ${r.daily_loss_cap_pct}%`)}
            {row("Drawdown pause", `No new trades while ≥ ${r.drawdown_pause_pct}% below the peak, until you review`)}
            {row("Account", "Alpaca paper only; refuses any non-paper account")}
          </tbody></table>
        </Panel>
      </div>
      <p className="mt-4 text-[11px] text-faint">Rules are unit-tested, not backtested: nothing here promises profits. Paper fills are kinder than real ones. Not financial advice.</p>
    </>
  );
}
