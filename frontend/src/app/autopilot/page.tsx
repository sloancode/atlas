import Link from "next/link";
import { getAutopilot, type AgentActionT, type AutopilotConfigT } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import { autopilotFileAttached, autopilotResume, autopilotRun, autopilotSave, autopilotStop } from "@/app/autopilot-actions";
import { EmptyState, PageHeader, Panel } from "@/components/ui";

const ACTION_LABEL: Record<string, string> = {
  create_digital_product: "Created product", update_content: "Updated content", set_price: "Changed price",
  publish: "Published", unpublish: "Unpublished", create_discount: "Created discount",
};
const STATUS_CLS: Record<string, string> = { executed: "text-pos", blocked: "text-warn", failed: "text-neg" };

export default async function AutopilotPage({ searchParams }: { searchParams: Promise<{ msg?: string }> }) {
  const params = await searchParams;
  const res = await getAutopilot();
  if (!res.ok) {
    return (<><PageHeader code="AUT" title="Autopilot" /><EmptyState title="Unavailable">{res.error}</EmptyState></>);
  }
  const a = res.data;
  const c = a.config;
  const state = c.stopped ? { label: "STOPPED", cls: "border-neg/60 bg-neg/10 text-neg" }
    : a.active ? { label: "ACTIVE", cls: "border-pos/60 bg-pos/10 text-pos" }
      : { label: "OFF", cls: "border-border-strong bg-panel-2 text-dim" };

  return (
    <>
      <PageHeader code="AUT" title="Shopify Autopilot"
        subtitle="An AI agent that runs your digital-product store within limits you set: it writes products (PDFs), creates and prices listings, publishes, improves and discounts. Every change is logged; it can only touch products it created."
        right={<span className={`rounded-sm border px-2.5 py-1 text-[12px] font-semibold tracking-wider ${state.cls}`}>{state.label}</span>} />
      {params.msg && <div className="mb-4 rounded-sm border border-border-strong bg-panel-2 px-3 py-2 text-[12px]">{params.msg}</div>}

      <div className="mb-4 grid gap-3 md:grid-cols-[1fr_auto]">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1 rounded-sm border border-border bg-panel px-3 py-2 text-[12px]">
          <span>Shopify: {a.ready.shopify ? <span className="text-pos">connected</span> : <span className="text-neg">not configured</span>}</span>
          <span>Claude API key: {a.ready.claude ? <span className="text-pos">set</span> : <span className="text-neg">missing (ANTHROPIC_API_KEY)</span>}</span>
          <span className="text-dim">Today: {a.today.actions}/{c.max_actions_per_day} changes · {a.today.new_products}/{c.max_new_products_per_day} new products · AI ${a.today.ai_spend_usd.toFixed(2)} of ${Number(c.daily_ai_budget_usd).toFixed(2)}</span>
          <span className="text-faint">Runs every {c.run_every_hours}h when active · needs write scopes (see Settings)</span>
        </div>
        <div className="flex gap-2">
          {c.stopped ? (
            <form action={autopilotResume}><button className="h-full rounded-sm border border-pos px-4 text-[12px] text-pos hover:bg-pos/10">Resume</button></form>
          ) : (
            <form action={autopilotStop}><button className="h-full rounded-sm border border-neg bg-neg/10 px-4 text-[13px] font-semibold text-neg hover:bg-neg/20">■ STOP</button></form>
          )}
          <form action={autopilotRun}><button disabled={!a.active} className="h-full rounded-sm border border-accent px-3 text-[12px] text-accent hover:bg-accent-dim disabled:opacity-40" title={a.active ? "Run one review now" : "Enable Autopilot first"}>Run now</button></form>
        </div>
      </div>

      <Panel title={`Needs you (${a.needs_you.length})`} className="mb-4">
        {a.needs_you.length === 0 ? (
          <div className="text-[12px] text-faint">Nothing waiting. When the agent creates a product, its PDF appears here for you to attach in Shopify.</div>
        ) : (
          <>
            <ol className="mb-3 list-decimal space-y-0.5 pl-4 text-[11px] text-dim">
              <li>Download the PDF and skim it. This is your review step; nothing goes live before it.</li>
              <li>In Shopify admin, open the product (it&apos;s a draft) and attach the file with the Digital Downloads or Digital Products app.</li>
              <li>Click &quot;File attached&quot;. The agent publishes it on its next run (if publishing is allowed).</li>
            </ol>
            <ul className="space-y-2">
              {a.needs_you.map((p) => (
                <li key={p.product_id} className="flex flex-wrap items-center justify-between gap-2 rounded-sm border border-warn/40 px-3 py-2 text-[12px]">
                  <span><span className="font-medium">{p.title}</span> <span className="text-faint">· created {fmtDateTime(p.created_at)}</span></span>
                  <span className="flex items-center gap-2">
                    {p.has_file ? <a href={`/autopilot/products/${p.product_id}/file`} className="rounded-sm border border-border-strong px-2 py-1 text-dim hover:text-text">Download PDF</a>
                      : <span className="text-[11px] text-neg">PDF not on this machine</span>}
                    <form action={autopilotFileAttached}><input type="hidden" name="product_id" value={p.product_id} />
                      <button className="rounded-sm border border-pos px-2 py-1 text-pos hover:bg-pos/10">File attached ✓</button></form>
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
      </Panel>

      <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
        <div className="space-y-4">
          <Panel title="Action log (every store change attempted)">
            {a.actions.length === 0 ? <div className="text-[12px] text-faint">No changes yet.</div> : (
              <ul className="space-y-1.5">{a.actions.map((x) => <ActionRow key={x.id} x={x} />)}</ul>
            )}
          </Panel>
          <Panel title="Runs">
            {a.runs.length === 0 ? <div className="text-[12px] text-faint">No runs yet.</div> : (
              <table className="w-full text-left text-[12px]">
                <thead className="text-[10px] uppercase tracking-wider text-faint"><tr className="border-b border-border"><th className="py-1 pr-2">When</th><th className="pr-2">Trigger</th><th className="pr-2">Status</th><th className="pr-2">Steps</th><th className="pr-2">AI cost</th><th>Summary</th></tr></thead>
                <tbody>{a.runs.map((r) => (
                  <tr key={r.id} className="border-b border-border align-top last:border-0">
                    <td className="whitespace-nowrap py-1.5 pr-2 text-dim">{fmtDateTime(r.started_at)}</td>
                    <td className="pr-2 text-dim">{r.trigger}</td>
                    <td className={`pr-2 ${r.status === "succeeded" ? "text-pos" : r.status === "failed" ? "text-neg" : "text-warn"}`}>{r.status}</td>
                    <td className="num pr-2">{r.steps}</td>
                    <td className="num pr-2">${r.est_cost_usd.toFixed(3)}</td>
                    <td className="text-dim">{r.summary ?? r.error ?? ""}</td>
                  </tr>
                ))}</tbody>
              </table>
            )}
            <div className="mt-2 text-[11px] text-faint">AI cost is an estimate from token counts at Claude Opus 5.5 list prices.</div>
          </Panel>
          <Panel title={`Agent products (${a.products.length})`}>
            {a.products.length === 0 ? <div className="text-[12px] text-faint">None yet.</div> : (
              <ul className="space-y-1 text-[12px]">{a.products.map((p) => (
                <li key={p.product_id} className="flex justify-between gap-2">
                  <span>{p.title}{p.concept?.sections && <span className="text-faint"> · {p.concept.sections.length} sections</span>}</span>
                  <span className={p.published ? "text-pos" : p.file_attached ? "text-info" : "text-warn"}>{p.published ? "live" : p.file_attached ? "ready to publish" : "waiting for file"}</span>
                </li>
              ))}</ul>
            )}
          </Panel>
        </div>
        <SettingsForm c={c} />
      </div>
      <p className="mt-4 text-[11px] text-faint">
        Limits are enforced by ATLAS&apos;s code, not by the AI. Autopilot never deletes anything and never touches orders, refunds, customers or payments.
        See <Link href="/settings" className="underline">Settings</Link> for the Shopify permissions it needs.
      </p>
    </>
  );
}

function ActionRow({ x }: { x: AgentActionT }) {
  const changed = x.before && x.after
    ? Object.keys(x.after).filter((k) => JSON.stringify(x.before![k]) !== JSON.stringify(x.after![k]))
    : x.after ? Object.keys(x.after) : [];
  return (
    <li className="rounded-sm border border-border px-3 py-1.5 text-[12px]">
      <div className="flex flex-wrap justify-between gap-2">
        <span><span className={STATUS_CLS[x.status]}>● {x.status}</span> {ACTION_LABEL[x.action] ?? x.action}
          {typeof x.params?.title === "string" && <span className="text-dim"> “{x.params.title}”</span>}
          {x.target && <span className="num text-faint"> {x.target.replace("gid://shopify/", "")}</span>}</span>
        <span className="text-[11px] text-faint">{fmtDateTime(x.created_at)}{x.run_id ? ` · run ${x.run_id}` : ""}</span>
      </div>
      {x.reason && <div className="text-dim">Why: {x.reason}</div>}
      {x.detail && <div className={x.status === "blocked" ? "text-warn" : "text-neg"}>{x.detail}</div>}
      {changed.length > 0 && (
        <div className="num mt-0.5 text-[11px] text-faint">
          {changed.slice(0, 4).map((k) => <div key={k}>{k}: {x.before ? `${JSON.stringify(x.before[k])} → ` : ""}{JSON.stringify(x.after![k])}</div>)}
        </div>
      )}
    </li>
  );
}

function SettingsForm({ c }: { c: AutopilotConfigT }) {
  const field = (name: keyof AutopilotConfigT, label: string, hint?: string) => (
    <label className="grid grid-cols-[1fr_90px] items-center gap-2">
      <span><span className="block text-[12px]">{label}</span>{hint && <span className="block text-[10px] text-faint">{hint}</span>}</span>
      <input name={name} defaultValue={String(c[name])} inputMode="decimal" className="num rounded-sm border border-border-strong bg-panel-2 px-2 py-1 text-right text-[12px]" />
    </label>
  );
  return (
    <Panel title="Settings & limits">
      <form action={autopilotSave} className="space-y-2.5">
        <label className="flex items-center gap-2 text-[13px]"><input type="checkbox" name="enabled" defaultChecked={c.enabled} /> Autopilot enabled</label>
        <label className="flex items-center gap-2 text-[12px]"><input type="checkbox" name="allow_publish" defaultChecked={c.allow_publish} /> Allowed to publish (after you attach the file)</label>
        {field("min_price", "Minimum price ($)")}
        {field("max_price", "Maximum price ($)")}
        {field("max_price_change_pct", "Max price change per edit (%)")}
        {field("max_discount_pct", "Max discount (%)")}
        {field("max_discount_days", "Max discount length (days)")}
        {field("max_actions_per_day", "Max store changes per day")}
        {field("max_new_products_per_day", "Max new products per day")}
        {field("daily_ai_budget_usd", "Daily AI budget ($)", "Runs stop when today's estimated cost reaches this")}
        {field("max_steps_per_run", "Max steps per run")}
        {field("run_every_hours", "Run every (hours)")}
        <button className="w-full rounded-sm border border-accent px-3 py-1 text-[12px] text-accent hover:bg-accent-dim">Save settings</button>
        <p className="text-[10px] text-faint">The STOP button overrides everything here.</p>
      </form>
    </Panel>
  );
}
