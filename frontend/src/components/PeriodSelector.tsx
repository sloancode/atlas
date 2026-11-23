import Link from "next/link";
import type { PeriodParams } from "@/lib/api";

const OPTIONS = [
  { key: "today", label: "Today" },
  { key: "7d", label: "7D" },
  { key: "30d", label: "30D" },
  { key: "90d", label: "90D" },
  { key: "ytd", label: "YTD" },
];

/** Period tabs + custom range. Pure links/GET form: works without client JS. */
export function PeriodSelector({ basePath, current }: { basePath: string; current: PeriodParams }) {
  const active = current.period ?? "30d";
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex overflow-hidden rounded-sm border border-border-strong" role="tablist">
        {OPTIONS.map((o) => (
          <Link
            key={o.key}
            href={`${basePath}?period=${o.key}`}
            role="tab"
            aria-selected={active === o.key}
            className={`num px-2.5 py-1 text-[11px] ${
              active === o.key ? "bg-accent-dim text-accent" : "text-dim hover:bg-panel-2 hover:text-text"
            }`}
          >
            {o.label}
          </Link>
        ))}
      </div>
      <form action={basePath} method="get" className="flex items-center gap-1.5 text-[11px]">
        <input type="hidden" name="period" value="custom" />
        <label className="sr-only" htmlFor="start">Start date</label>
        <input
          id="start"
          type="date"
          name="start"
          required
          defaultValue={active === "custom" ? current.start : undefined}
          className="num rounded-sm border border-border-strong bg-panel px-1.5 py-[3px] text-text [color-scheme:dark]"
        />
        <span className="text-faint">–</span>
        <label className="sr-only" htmlFor="end">End date</label>
        <input
          id="end"
          type="date"
          name="end"
          required
          defaultValue={active === "custom" ? current.end : undefined}
          className="num rounded-sm border border-border-strong bg-panel px-1.5 py-[3px] text-text [color-scheme:dark]"
        />
        <button
          type="submit"
          className={`rounded-sm border px-2 py-[3px] ${
            active === "custom" ? "border-accent text-accent" : "border-border-strong text-dim hover:text-text"
          }`}
        >
          Apply
        </button>
      </form>
    </div>
  );
}
