import Link from "next/link";
import { getAnalystStatus, getReport, getReports, type ReportFull } from "@/lib/api";
import { fmtDate, fmtDateTime, money, num, pct } from "@/lib/format";
import { generateReport, regenerateNarrative } from "@/app/actions";
import { AnalystPanel } from "@/components/AnalystPanel";
import { Change, StatusPill } from "@/components/analytics";
import { EmptyState, PageHeader, Panel } from "@/components/ui";

const STATUS_LABEL: Record<string, string> = {
  out_of_stock: "Out of stock", stockout_risk: "Stockout risk", low_stock: "Low stock",
  overstock: "Overstock", no_recent_sales: "No recent sales",
};

export default async function ReportsPage({ searchParams }: { searchParams: Promise<{ id?: string; msg?: string }> }) {
  const params = await searchParams;
  const [list, status] = await Promise.all([getReports(), getAnalystStatus()]);
  const selectedId = params.id ?? (list.ok && list.data[0] ? String(list.data[0].id) : undefined);
  const report = selectedId ? await getReport(selectedId) : null;
  const configured = status.ok && status.data.configured;

  return (
    <>
      <PageHeader
        code="RPT"
        title="Business Reports"
        subtitle="Ask the AI analyst about your store, and review daily and weekly reports. Report facts come straight from your synced data; AI text is labeled and checked against it."
      />
      {params.msg && <div className="mb-4 rounded-sm border border-border-strong bg-panel-2 px-3 py-2 text-[12px]">{params.msg}</div>}

      <Panel title="AI business analyst" className="mb-4"
        right={<span className="text-[11px] text-faint">{configured ? `Claude API · ${status.ok ? status.data.model : ""}` : "Not configured"}</span>}>
        <AnalystPanel configured={configured} model={status.ok ? status.data.model : ""} />
      </Panel>

      <div className="grid gap-4 xl:grid-cols-[260px_1fr]">
        <Panel title="Reports">
          <div className="mb-3 flex gap-2">
            {(["daily", "weekly"] as const).map((k) => (
              <form key={k} action={generateReport} className="flex-1">
                <input type="hidden" name="kind" value={k} />
                <button className="w-full rounded-sm border border-border-strong px-2 py-1 text-[11px] text-dim hover:border-accent hover:text-accent">
                  Generate {k}
                </button>
              </form>
            ))}
          </div>
          {!list.ok ? (
            <div className="text-[12px] text-neg">{list.error}</div>
          ) : list.data.length === 0 ? (
            <div className="text-[12px] text-faint">No reports yet. They are created automatically after each successful sync, or generate one now.</div>
          ) : (
            <ul className="max-h-[560px] space-y-0.5 overflow-y-auto">
              {list.data.map((r) => (
                <li key={r.id}>
                  <Link href={`/reports?id=${r.id}`}
                    className={`block rounded-sm px-2 py-1.5 text-[12px] ${String(r.id) === selectedId ? "bg-panel-2 text-text" : "text-dim hover:bg-panel-2"}`}>
                    <span className={`num mr-2 text-[10px] uppercase ${r.kind === "weekly" ? "text-accent" : "text-info"}`}>{r.kind === "weekly" ? "WK" : "DAY"}</span>
                    {r.period_start === r.period_end ? fmtDate(r.period_start) : `${fmtDate(r.period_start)} – ${fmtDate(r.period_end)}`}
                    <span className="float-right text-[10px] text-faint">{r.investigate} to check</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Panel>
        <div>
          {!report ? (
            <EmptyState title="No report selected" />
          ) : !report.ok ? (
            <EmptyState title="Report unavailable">{report.error}</EmptyState>
          ) : (
            <ReportView r={report.data} />
          )}
        </div>
      </div>
    </>
  );
}

function ReportView({ r }: { r: ReportFull }) {
  const f = r.facts;
  const c = f.currency;
  const s = f.sections;
  const head = ["gross_sales", "net_sales", "orders", "aov", "units_sold", "refunds_total"];
  const kp = Object.fromEntries(s.revenue.map((k) => [k.key, k]));
  const fmtK = (key: string, v: number | null) => {
    const k = kp[key];
    return k.kind === "money" ? money(v, c) : num(v);
  };
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <div className="num text-[11px] uppercase text-accent">{f.kind} report</div>
          <h2 className="text-lg font-semibold">
            {f.period.start === f.period.end ? fmtDate(f.period.start) : `${fmtDate(f.period.start)} – ${fmtDate(f.period.end)}`}
          </h2>
          <div className="text-[11px] text-faint">
            vs {fmtDate(f.previous_period.start)}{f.previous_period.start !== f.previous_period.end && ` – ${fmtDate(f.previous_period.end)}`} ·
            generated {fmtDateTime(r.generated_at)} · data as of {fmtDateTime(f.as_of)} · {f.timezone}
          </div>
        </div>
        <div className="flex gap-2 text-[11px]">
          <a href={`/reports/${r.id}/export?format=md`} className="rounded-sm border border-border-strong px-2 py-1 text-dim hover:border-accent hover:text-accent">Export Markdown</a>
          <a href={`/reports/${r.id}/export?format=csv`} className="rounded-sm border border-border-strong px-2 py-1 text-dim hover:border-accent hover:text-accent">Export CSV</a>
        </div>
      </div>
      {f.notes.map((n) => <div key={n} className="text-[11px] text-warn">⚠ {n}</div>)}

      <Panel title="1 · Revenue and orders">
        <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
          {head.map((key) => kp[key] && (
            <div key={key} className="rounded-sm border border-border px-2.5 py-2" title={kp[key].definition}>
              <div className="flex justify-between text-[11px] text-dim"><span>{kp[key].label}</span><Change value={kp[key].change_pct} /></div>
              <div className="num mt-1 text-[17px]">{fmtK(key, kp[key].current) ?? "—"}</div>
              <div className="text-[11px] text-faint">prev {fmtK(key, kp[key].previous) ?? "—"}</div>
            </div>
          ))}
        </div>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="2 · Best-performing products">
          <PList rows={s.best_products} c={c} empty="No product sales in this period." />
        </Panel>
        <Panel title="3 · Weakest-performing products">
          <PList rows={s.weakest_products} c={c} empty="No active products." />
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="4 · Inventory alerts">
          {s.inventory_alerts.length ? (
            <ul className="space-y-1.5 text-[12px]">
              {s.inventory_alerts.map((a) => (
                <li key={a.title + a.status}><span className="text-warn">{STATUS_LABEL[a.status] ?? a.status}</span> · {a.title}
                  <div className="text-[11px] text-faint">{a.reason}</div></li>
              ))}
            </ul>
          ) : <div className="text-[12px] text-faint">No inventory alerts.</div>}
        </Panel>
        <Panel title="5 · Profitability observations">
          <ul className="space-y-1 text-[12px]">
            {s.profitability.metrics.map((m) => (
              <li key={m.key} className="flex items-center justify-between gap-2">
                <span className="text-dim">{m.label}</span>
                <span className="flex items-center gap-2">
                  <span className="num">{m.value === null ? "—" : m.kind === "percent" ? pct(m.value) : money(m.value, c)}</span>
                  <StatusPill status={m.value === null ? "missing" : m.status} />
                </span>
              </li>
            ))}
          </ul>
          {s.profitability.missing_inputs.length > 0 && (
            <div className="mt-2 text-[11px] text-warn">Missing: {s.profitability.missing_inputs.join("; ")} · <Link href="/profitability" className="underline">enter costs</Link></div>
          )}
        </Panel>
      </div>

      <Panel title="6 · Important changes">
        {s.changes.length ? (
          <ul className="space-y-1 text-[12px]">
            {s.changes.map((x) => <li key={x.text}>{x.text} <span className="text-faint">({x.evidence})</span></li>)}
          </ul>
        ) : <div className="text-[12px] text-faint">No significant changes.</div>}
      </Panel>

      <Panel title="7 · Areas to investigate">
        {s.investigate.length ? (
          <ol className="space-y-2 text-[12px]">
            {s.investigate.map((x, i) => (
              <li key={x.title} className="flex gap-2">
                <span className="num text-accent">{i + 1}.</span>
                <div><div className="font-medium">{x.title}</div><div className="text-dim">{x.why}</div><div className="text-[11px] text-faint">Evidence: {x.evidence}</div></div>
              </li>
            ))}
          </ol>
        ) : <div className="text-[12px] text-faint">Nothing met the evidence bar this period.</div>}
        {s.investigate.length > 0 && s.investigate.length < 3 && (
          <div className="mt-2 text-[11px] text-faint">Only {s.investigate.length} area(s) met the evidence bar; ATLAS doesn&apos;t pad the list.</div>
        )}
      </Panel>

      {f.kind === "weekly" && (s.movers?.length ?? 0) > 0 && (
        <Panel title="Momentum this week">
          <ul className="space-y-1 text-[12px]">{s.movers!.map((m) => <li key={m.title + m.flag}>{m.title}: <span className="text-dim">{m.flag}</span> <span className="text-faint">— {m.reason}</span></li>)}</ul>
        </Panel>
      )}

      <Panel title="AI interpretation (Claude) — not a fact source"
        right={r.narrative_status !== "not_configured" ? (
          <form action={regenerateNarrative}><input type="hidden" name="id" value={r.id} />
            <button className="text-[11px] text-accent hover:underline">{r.narrative_status === "generated" ? "Regenerate" : "Generate"}</button></form>
        ) : undefined}>
        {r.narrative_status === "not_configured" ? (
          <div className="text-[12px] text-faint">Add ANTHROPIC_API_KEY to enable AI interpretation. The report above is complete without it.</div>
        ) : r.narrative_status === "failed" ? (
          <div className="text-[12px] text-neg">{r.narrative?.error ?? "Generation failed."}</div>
        ) : r.narrative?.sections ? (
          <div className="space-y-1.5 text-[12px]">
            {r.narrative.summary && <p>{r.narrative.summary}</p>}
            <ul className="space-y-1">
              {r.narrative.sections.map((it, i) => (
                <li key={i}><span className="text-[10px] uppercase text-faint">[{it.type}]</span> {it.text}{" "}
                  {it.verified ? <span className="text-[10px] text-pos">✓</span> : <span className="text-[10px] text-neg" title={it.issues.join(" ")}>⚠ unverified</span>}</li>
              ))}
            </ul>
          </div>
        ) : <div className="text-[12px] text-faint">Not generated yet.</div>}
      </Panel>
    </div>
  );
}

function PList({ rows, c, empty }: { rows: { title: string; net_sales: number; units: number; growth_pct: number | null }[]; c: string; empty: string }) {
  if (!rows.length) return <div className="text-[12px] text-faint">{empty}</div>;
  return (
    <ul className="text-[12px]">
      {rows.map((r) => (
        <li key={r.title} className="grid grid-cols-[minmax(0,1fr)_auto_2.5rem_4.5rem] items-center gap-2 border-b border-border py-1.5 last:border-0">
          <span className="truncate" title={r.title}>{r.title}</span>
          <span className="num text-right">{money(r.net_sales, c)}</span>
          <span className="num text-right text-faint">{r.units}u</span>
          <span className="text-right text-[11px]"><Change value={r.growth_pct} /></span>
        </li>
      ))}
    </ul>
  );
}
