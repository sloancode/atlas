"use client";

import { LineChart } from "./LineChart";

export function EquityChart({ curve, start }: { curve: { date: string; equity: number }[]; start: number }) {
  return (
    <LineChart label="Paper account equity" dates={curve.map((c) => c.date)}
      format={(v) => `$${v.toLocaleString("en-US", { maximumFractionDigits: 0 })}`}
      series={[
        { key: "equity", label: "Equity (paper)", color: "var(--sim)", values: curve.map((c) => c.equity) },
        { key: "start", label: "Starting equity", color: "var(--text-faint)", dash: "4 4", values: curve.map(() => start) },
      ]} />
  );
}
