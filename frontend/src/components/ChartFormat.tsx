"use client";

import type { DailyPoint } from "@/lib/api";
import { money } from "@/lib/format";
import { DailyBarChart } from "./DailyBarChart";

/** Client wrapper so the chart's formatter (a function) never crosses the server boundary. */
export function ChartFormat({ daily, currency }: { daily: DailyPoint[]; currency: string | null }) {
  return (
    <DailyBarChart
      label="Net sales by day"
      format={(v) => money(v, currency) ?? ""}
      data={daily.map((d) => ({
        date: d.date,
        value: d.net_sales,
        detail: `${d.orders} order${d.orders === 1 ? "" : "s"} · gross ${money(d.gross_sales, currency)}`,
      }))}
    />
  );
}
