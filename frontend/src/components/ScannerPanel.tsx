"use client";

import { useActionState } from "react";
import Link from "next/link";
import { runScan, type ScanState } from "@/app/markets-actions";

type Presets = Record<string, { label: string; description: string; rules: { metric: string; op: string; value: unknown }[] }>;

export function ScannerPanel({ presets, metrics, watchlists }: { presets: Presets; metrics: Record<string, string>; watchlists: { id: number; name: string; count: number }[] }) {
  const [state, action, pending] = useActionState<ScanState, FormData>(runScan, { results: null, rules: [], error: null });
  const fmt = (v: unknown) => (v === null || v === undefined ? "—" : typeof v === "number" ? (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2)) : String(v));
  return (
    <div className="space-y-4">
      <form action={action} className="grid gap-3 rounded-[3px] border border-border bg-panel p-3 lg:grid-cols-[1fr_1fr_auto]">
        <label className="text-[12px]">
          <span className="mb-1 block text-[11px] text-dim">Category</span>
          <select name="preset" className="w-full rounded-sm border border-border-strong bg-panel-2 px-2 py-1.5">
            {Object.entries(presets).map(([k, p]) => <option key={k} value={k}>{p.label}</option>)}
          </select>
        </label>
        <div className="grid gap-2 text-[12px]">
          <label>
            <span className="mb-1 block text-[11px] text-dim">Universe: watchlist</span>
            <select name="watchlist_id" className="w-full rounded-sm border border-border-strong bg-panel-2 px-2 py-1.5">
              <option value="">(none)</option>
              {watchlists.map((w) => <option key={w.id} value={w.id}>{w.name} ({w.count})</option>)}
            </select>
          </label>
          <label>
            <span className="mb-1 block text-[11px] text-dim">…and/or symbols (max 40)</span>
            <input name="symbols" placeholder="AAPL, MSFT, SPY" className="num w-full rounded-sm border border-border-strong bg-panel-2 px-2 py-1.5 uppercase placeholder:normal-case placeholder:text-faint" />
          </label>
        </div>
        <button disabled={pending} className="self-end rounded-sm border border-accent px-4 py-1.5 text-[12px] text-accent hover:bg-accent-dim disabled:opacity-50">
          {pending ? "Scanning…" : "Run scan"}
        </button>
      </form>

      <div className="grid gap-2 text-[11px] text-dim sm:grid-cols-2 xl:grid-cols-4">
        {Object.entries(presets).map(([k, p]) => (
          <div key={k} className="rounded-sm border border-border px-2.5 py-2">
            <div className="text-text">{p.label}</div>
            <div>{p.description}</div>
            <div className="num mt-1 text-faint">{p.rules.map((r) => `${metrics[r.metric] ?? r.metric} ${r.op} ${JSON.stringify(r.value)}`).join(" · ")}</div>
          </div>
        ))}
      </div>

      {state.error && <div className="rounded-sm border border-neg/40 bg-neg/5 px-3 py-2 text-[12px] text-neg">{state.error}</div>}
      {state.results && (
        <div className="rounded-[3px] border border-border bg-panel">
          <div className="border-b border-border px-3 py-2 text-[11px] text-faint">
            {state.results.filter((r) => r.matched).length} of {state.results.length} matched · {state.note}
          </div>
          <table className="w-full text-left text-[12px]">
            <thead className="text-[10px] uppercase tracking-wider text-faint">
              <tr className="border-b border-border"><th className="px-3 py-2">Symbol</th><th>Result</th><th>Close</th><th className="pr-3">Why (each rule, actual value)</th></tr>
            </thead>
            <tbody>
              {state.results.map((r) => (
                <tr key={r.symbol} className="border-b border-border align-top last:border-0">
                  <td className="px-3 py-2"><Link href={`/research?symbol=${r.symbol}`} className="num font-medium hover:text-accent">{r.symbol}</Link>
                    <div className="text-[11px] text-faint">{r.name ?? ""}</div></td>
                  <td className="py-2">{r.matched ? <span className="text-pos">● Appears</span> : <span className="text-faint">{r.passed}/{r.total} rules</span>}</td>
                  <td className="num py-2">{fmt(r.close)}<div className="text-[10px] text-faint">{r.price_as_of ?? ""}</div></td>
                  <td className="py-2 pr-3">
                    <ul className="space-y-0.5">
                      {r.checks.map((c) => (
                        <li key={c.label} className={c.passed ? "text-pos" : c.detail === "data unavailable" ? "text-warn" : "text-dim"}>
                          {c.passed ? "✓" : "✗"} {c.label} <span className="num text-faint">(actual: {fmt(c.actual)}{c.detail === "data unavailable" ? ", data unavailable" : ""})</span>
                        </li>
                      ))}
                    </ul>
                    {r.missing_data.length > 0 && <div className="text-[10px] text-faint">Missing: {r.missing_data.join(", ")}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
