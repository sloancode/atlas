import Link from "next/link";
import type { BotAction, BrokerOrder } from "@/lib/api";
import { fmtET, money, num } from "@/lib/format";

const TABS = [
  { href: "/bot", label: "Run log" },
  { href: "/bot/rules", label: "Rules" },
  { href: "/bot/settings", label: "Settings" },
];

export function PaperBadge() {
  return (
    <span className="rounded-sm border border-sim/60 bg-sim/10 px-2 py-1 text-[11px] font-medium uppercase tracking-wider text-sim">
      Alpaca paper
    </span>
  );
}

export function BotTabs({ current }: { current: string }) {
  return (
    <nav aria-label="Trading bot" className="mb-4 flex gap-1 text-[12px]">
      {TABS.map((t) => (
        <Link
          key={t.href}
          href={t.href}
          aria-current={t.href === current ? "page" : undefined}
          className={`rounded-sm border px-2.5 py-1 ${
            t.href === current
              ? "border-accent/60 bg-accent/10 text-text"
              : "border-border text-dim hover:text-text"
          }`}
        >
          {t.label}
        </Link>
      ))}
    </nav>
  );
}

const ACTION_CLS: Record<string, string> = {
  buy: "text-pos",
  sell: "text-neg",
  stop: "text-warn",
  cancel: "text-dim",
};

export function ActionLabel({ action }: { action: BotAction["action"] | string }) {
  return (
    <span className={`num text-[11px] font-medium uppercase ${ACTION_CLS[action] ?? "text-dim"}`}>
      {action}
    </span>
  );
}

export function BrokerError({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <div className="mb-3 rounded-sm border border-warn/40 bg-warn/5 px-3 py-2 text-[12px] text-warn">
      ⚠ {error}
    </div>
  );
}

const STATUS_CLS: Record<string, string> = {
  filled: "text-pos",
  partially_filled: "text-info",
  new: "text-info",
  accepted: "text-info",
  canceled: "text-faint",
  expired: "text-faint",
  rejected: "text-neg",
};

export function OrdersTable({ orders, empty }: { orders: BrokerOrder[]; empty: string }) {
  if (orders.length === 0) return <div className="text-[12px] text-faint">{empty}</div>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-[12px]">
        <thead className="text-[10px] uppercase tracking-wider text-faint">
          <tr className="border-b border-border">
            <th className="py-1.5 pr-3">Submitted</th>
            <th className="pr-3">Symbol</th>
            <th className="pr-3">Side</th>
            <th className="pr-3">Type</th>
            <th className="pr-3">Qty</th>
            <th className="pr-3">Price</th>
            <th className="pr-3">Status</th>
            <th>Placed by</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((o) => (
            <tr key={o.id} className="border-b border-border last:border-0">
              <td className="py-1.5 pr-3 text-dim">{fmtET(o.submitted_at)}</td>
              <td className="num pr-3 font-medium">{o.symbol}</td>
              <td className="pr-3"><ActionLabel action={o.side} /></td>
              <td className="pr-3 text-dim">
                {o.type}
                {o.time_in_force ? ` · ${o.time_in_force}` : ""}
              </td>
              <td className="num pr-3">
                {o.filled_qty && o.filled_qty !== o.qty
                  ? `${num(o.filled_qty, 4)} / ${num(o.qty, 4)}`
                  : num(o.qty, 4) ?? "—"}
              </td>
              <td className="num pr-3">
                {o.filled_avg_price !== null
                  ? `${money(o.filled_avg_price)} filled`
                  : o.stop_price !== null
                    ? `stop ${money(o.stop_price)}`
                    : o.limit_price !== null
                      ? `limit ${money(o.limit_price)}`
                      : "—"}
              </td>
              <td className={`pr-3 ${STATUS_CLS[o.status] ?? "text-dim"}`}>{o.status}</td>
              <td className={o.by_bot ? "text-accent" : "text-faint"}>{o.by_bot ? "bot" : "other"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
