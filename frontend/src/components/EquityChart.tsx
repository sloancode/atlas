"use client";

import { LineChart } from "./LineChart";

export function EquityChart({ curve, start }: { curve: { date: string; equity: number }[]; start: number }) {
  return (
    <LineChart label="Simulated portfolio equity" dates={curve.map((c) => c.date)}
      format={(v) => `$${v.toLocaleString("en-US", { maximumFractionDigits: 0 })}`}
      series={[
        { key: "equity", label: "Simulated equity", color: "var(--sim)", values: curve.map((c) => c.equity) },
        { key: "start", label: "Starting cash", color: "var(--text-faint)", dash: "4 4", values: curve.map(() => start) },
      ]} />
  );
}
