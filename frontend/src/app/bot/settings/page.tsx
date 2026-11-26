import { getBotSettings } from "@/lib/api";
import { fmtET, money, num, pct } from "@/lib/format";
import { BotTabs, BrokerError, OrdersTable, PaperBadge } from "@/components/bot";
import { Code, EmptyState, MetricTile, PageHeader, Panel } from "@/components/ui";

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <tr className="border-b border-border last:border-0">
      <td className="py-1.5 pr-3 text-dim">{k}</td>
      <td className="num py-1.5 text-right">{v}</td>
    </tr>
  );
}

const yesNo = (b: boolean) => (b ? "Allowed" : "Off");

export default async function BotSettingsPage() {
  const res = await getBotSettings();
  return (
    <>
      <PageHeader
        code="BST"
        title="Trading Bot · Settings"
        subtitle="The paper account the bot trades, its risk limits and its schedule."
        right={<PaperBadge />}
      />
      <BotTabs current="/bot/settings" />
      {!res.ok ? (
        <EmptyState title="Unavailable">{res.error}</EmptyState>
      ) : (() => {
        const d = res.data;
        const b = d.broker;
        const a = b.account;
        const dayChange = a && a.equity !== null && a.last_equity ? ((a.equity / a.last_equity) - 1) * 100 : null;
        return (
          <div className="space-y-4">
            <Panel
              title="Alpaca paper account"
              right={<span className="text-[11px] text-faint">endpoint <Code>{b.endpoint}</Code></span>}
            >
              {!b.configured ? (
                <EmptyState title="Not connected">
                  Add paper keys as {b.missing_env.map((e, i) => <span key={e}>{i > 0 && " and "}<Code>{e}</Code></span>)} in <Code>backend/.env</Code>, then restart the backend. Use keys from the Alpaca <em>paper</em> dashboard; ATLAS refuses any non-paper account.
                </EmptyState>
              ) : (
                <>
                  <BrokerError error={b.error} />
                  {a && (
                    <>
                      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
                        <MetricTile label="Equity" value={money(a.equity, a.currency)} status="simulated" note={dayChange === null ? undefined : `${pct(dayChange, true)} today`} />
                        <MetricTile label="Cash" value={money(a.cash, a.currency)} status="simulated" note="The bot buys with cash only" />
                        <MetricTile label="Positions value" value={money(a.long_market_value, a.currency)} status="simulated" />
                        <MetricTile label="Buying power" value={money(a.buying_power, a.currency)} status="simulated" note="Includes margin, which the bot does not use" />
                      </div>
                      <div className="mt-2 flex flex-wrap gap-4 text-[12px] text-dim">
                        <span>Account <span className="num text-text">{a.account ?? "—"}</span></span>
                        <span>Status <span className={a.status === "ACTIVE" ? "text-pos" : "text-warn"}>{a.status ?? "—"}</span></span>
                        {(a.trading_blocked || a.account_blocked) && <span className="text-neg">Trading blocked by Alpaca</span>}
                        {b.clock && (
                          <span>
                            Market <span className={b.clock.is_open ? "text-pos" : "text-text"}>{b.clock.is_open ? "open" : "closed"}</span>
                            {" · "}
                            {b.clock.is_open ? `closes ${fmtET(b.clock.next_close)}` : `opens ${fmtET(b.clock.next_open)}`}
                          </span>
                        )}
                      </div>
                    </>
                  )}
                </>
              )}
            </Panel>

            {a && (
              <div className="grid gap-4 xl:grid-cols-2">
                <Panel title={`Positions (${b.positions.length})`}>
                  {b.positions.length === 0 ? <div className="text-[12px] text-faint">No open positions.</div> : (
                    <table className="w-full text-left text-[12px]">
                      <thead className="text-[10px] uppercase tracking-wider text-faint"><tr className="border-b border-border"><th className="py-1.5">Symbol</th><th>Qty</th><th>Avg entry</th><th>Price</th><th>Unrealized P&amp;L</th></tr></thead>
                      <tbody>{b.positions.map((p) => (
                        <tr key={p.symbol} className="border-b border-border last:border-0">
                          <td className="num py-1.5 font-medium">{p.symbol}</td>
                          <td className="num">{num(p.qty, 4)}</td>
                          <td className="num">{money(p.avg_entry_price) ?? "—"}</td>
                          <td className="num">{money(p.current_price) ?? "—"}</td>
                          <td className={`num ${p.unrealized_pl === null ? "" : p.unrealized_pl >= 0 ? "text-pos" : "text-neg"}`}>
                            {p.unrealized_pl === null ? "—" : `${money(p.unrealized_pl)} (${pct(p.unrealized_plpc, true)})`}
                          </td>
                        </tr>
                      ))}</tbody>
                    </table>
                  )}
                </Panel>
                <Panel title={`Open orders (${b.open_orders.length})`}>
                  <OrdersTable orders={b.open_orders} empty="No open orders. Protective stops show here while positions are held." />
                </Panel>
              </div>
            )}

            <div className="grid gap-4 xl:grid-cols-3">
              <Panel title="Risk limits">
                <table className="w-full text-[12px]"><tbody>
                  <Row k="Max size per new position" v={`${d.risk.max_position_pct}% of equity`} />
                  <Row k="Max positions" v={d.risk.max_positions} />
                  <Row k="Protective stop" v={`${d.risk.stop_loss_pct}% below entry`} />
                  <Row k="Pause new buys at drawdown" v={`${d.risk.drawdown_pause_pct}% from peak`} />
                  <Row k="Max new buys per day" v={d.risk.max_new_buys_per_day} />
                  <Row k="Cooldown after a sell" v={`${d.risk.cooldown_days} days`} />
                  <Row k="Margin" v={yesNo(d.risk.allow_margin)} />
                  <Row k="Shorting" v={yesNo(d.risk.allow_short)} />
                  <Row k="Options / crypto" v={`${yesNo(d.risk.options)} / ${yesNo(d.risk.crypto)}`} />
                  <Row k="Share size" v={d.risk.whole_shares_only ? "Whole shares" : "Fractional"} />
                </tbody></table>
              </Panel>
              <Panel title="Signal settings">
                <table className="w-full text-[12px]"><tbody>
                  <Row k="Fast / slow average" v={`SMA${d.signals.fast} / SMA${d.signals.slow}`} />
                  <Row k="Slope lookback" v={`${d.signals.slope_lookback} sessions`} />
                  <Row k="Relative-strength window" v={`${d.signals.rs_window} sessions`} />
                  <Row k="Max distance below high" v={`${d.signals.max_below_high_pct}%`} />
                  <Row k="Trend exits checked from" v={`${d.signals.trend_exit_hour_et}:00 ET`} />
                  <Row k="Order ID prefix" v={<Code>{d.signals.order_prefix}-</Code>} />
                </tbody></table>
              </Panel>
              <Panel title="Schedule">
                <div className="text-[12px]">
                  <div>{d.schedule.description}</div>
                  <div className="num mt-1 text-dim">{d.schedule.runs_et.join(" · ")}</div>
                  {d.schedule.skips_when_market_closed && <div className="mt-1 text-[11px] text-faint">Runs do nothing while the market is closed. Stops stay active at the broker between runs.</div>}
                </div>
              </Panel>
            </div>
            <p className="text-[11px] text-faint">{d.note}</p>
          </div>
        );
      })()}
    </>
  );
}
