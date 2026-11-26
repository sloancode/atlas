import { getSystemStatus } from "@/lib/api";
import { StateBadge } from "./ui";

export async function TopBar() {
  const res = await getSystemStatus();
  const alpaca = res.ok ? res.data.providers.find((p) => p.name === "alpaca") : undefined;
  return (
    <div className="flex h-11 shrink-0 items-center justify-between border-b border-border bg-panel px-5 text-[11px]">
      <div className="flex items-center gap-5 text-dim">
        <span className="flex items-center gap-2">
          API
          {res.ok ? <span className="text-pos">● online</span> : <span className="text-neg">● {res.error}</span>}
        </span>
        {res.ok && (
          <span className="flex items-center gap-2">
            DB
            <span className={res.data.database.ok ? "text-pos" : "text-neg"}>● {res.data.database.ok ? "ok" : "unavailable"}</span>
          </span>
        )}
        {alpaca && (
          <span className="flex items-center gap-2">
            Alpaca paper <StateBadge state={alpaca.state} />
          </span>
        )}
      </div>
      <div className="flex items-center gap-3">
        <span className="rounded-sm border border-sim/50 bg-sim/10 px-1.5 py-[1px] text-[10px] font-medium uppercase tracking-wider text-sim" title="Simulated money only. No live brokerage is connected.">
          Paper trading
        </span>
        <span className="num text-faint">{res.ok ? res.data.environment : "—"}</span>
      </div>
    </div>
  );
}
