import Link from "next/link";
import type { DataStatusValue, Kpi, Meta } from "@/lib/api";
import { fmtDate, fmtDateTime, formatKpi, pct } from "@/lib/format";
import { DataStatusTag, EmptyState } from "./ui";

/** Source, freshness, compared periods and caveats -- shown on every analytics page. */
export function MetaBar({ meta, compare = true }: { meta: Meta; compare?: boolean }) {
  return (
    <div className="mb-4 rounded-sm border border-border bg-panel px-3 py-2 text-[11px] text-dim">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
        <DataStatusTag status={meta.status} />
        <span>
          Source: <span className="text-text">Shopify Admin API</span> (synced copy)
        </span>
        <span>
          As of: <span className="num text-text">{fmtDateTime(meta.as_of)}</span>
        </span>
        {meta.period && (
          <span>
            Period:{" "}
            <span className="num text-text">
              {fmtDate(meta.period.start)} – {fmtDate(meta.period.end)}
            </span>
          </span>
        )}
        {compare && meta.previous_period && (
          <span>
            vs{" "}
            <span className="num text-text">
              {fmtDate(meta.previous_period.start)} – {fmtDate(meta.previous_period.end)}
            </span>
          </span>
        )}
        <span>
          Timezone: <span className="text-text">{meta.timezone}</span>
        </span>
      </div>
      {meta.notes.length > 0 && (
        <ul className="mt-1.5 space-y-0.5 text-warn">
          {meta.notes.map((n) => (
            <li key={n}>⚠ {n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function Change({ value }: { value: number | null }) {
  if (value === null) return <span className="text-faint">n/a</span>;
  const cls = value > 0 ? "text-pos" : value < 0 ? "text-neg" : "text-dim";
  const arrow = value > 0 ? "▲" : value < 0 ? "▼" : "■";
  return (
    <span className={`num ${cls}`}>
      {arrow} {pct(value, true)}
    </span>
  );
}

export function KpiTile({ kpi, currency }: { kpi: Kpi; currency: string | null }) {
  const cur = formatKpi(kpi.kind, kpi.current, currency);
  const prev = formatKpi(kpi.kind, kpi.previous, currency);
  return (
    <div className="rounded-[3px] border border-border bg-panel px-3 py-2.5" title={kpi.definition}>
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-[11px] text-dim">{kpi.label}</span>
        {cur !== null && <Change value={kpi.change_pct} />}
      </div>
      <div className={`num mt-1.5 text-[20px] leading-none ${cur === null ? "text-faint" : ""}`}>
        {cur ?? "—"}
      </div>
      <div className="mt-1.5 truncate text-[11px] text-faint">
        {cur === null ? "Unavailable" : `prev ${prev ?? "—"}`}
      </div>
    </div>
  );
}

export function NoSyncState() {
  return (
    <EmptyState title="No Shopify data synced yet">
      Run a sync from <Link href="/settings" className="text-accent hover:underline">Settings</Link>.
      ATLAS shows nothing here rather than placeholder numbers.
    </EmptyState>
  );
}

export function StatusPill({ status }: { status: DataStatusValue }) {
  return <DataStatusTag status={status} />;
}

export function FlagChip({ label, reason, tone }: { label: string; reason: string; tone?: string }) {
  return (
    <span
      title={reason}
      className={`inline-flex cursor-help items-center whitespace-nowrap rounded-sm border px-1.5 py-[1px] text-[10px] ${
        tone ?? "border-border-strong text-dim"
      }`}
    >
      {label}
    </span>
  );
}

export const FLAG_TONE: Record<string, string> = {
  best_seller: "border-accent/50 text-accent",
  accelerating: "border-pos/50 text-pos",
  losing_momentum: "border-neg/50 text-neg",
  low_inventory_strong_demand: "border-warn/50 text-warn",
  high_inventory_weak_demand: "border-info/50 text-info",
};
