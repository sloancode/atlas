"use client";

import { LineChart } from "./LineChart";

export function PriceChart({ chart, symbol }: { chart: { dates: string[]; close: (number | null)[]; sma50: (number | null)[]; sma200: (number | null)[] }; symbol: string }) {
  return (
    <LineChart
      label={`${symbol} daily close with 50- and 200-day averages`}
      dates={chart.dates}
      format={(v) => v.toLocaleString("en-US", { maximumFractionDigits: v >= 100 ? 0 : 2 })}
      series={[
        { key: "close", label: "Close", color: "var(--viz-1)", values: chart.close },
        { key: "sma50", label: "SMA 50", color: "var(--viz-2)", dash: "6 3", values: chart.sma50 },
        { key: "sma200", label: "SMA 200", color: "var(--viz-3)", dash: "2 3", values: chart.sma200 },
      ]}
    />
  );
}
