"use client";

import { money } from "@/lib/format";
import { DailyBarChart } from "./DailyBarChart";

export function UnitsChart({
  daily,
  currency,
}: {
  daily: { date: string; units: number; sales_after_discounts: number }[];
  currency: string | null;
}) {
  return (
    <DailyBarChart
      label="Units sold by day"
      format={(v) => `${Math.round(v * 100) / 100}`}
      data={daily.map((d) => ({
        date: d.date,
        value: d.units,
        detail: `${money(d.sales_after_discounts, currency)} after discounts`,
      }))}
    />
  );
}
