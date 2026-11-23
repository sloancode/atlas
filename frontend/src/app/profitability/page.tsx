import { getCosts, getProfitability, type PeriodParams, type StoreCosts } from "@/lib/api";
import { money, pct } from "@/lib/format";
import { saveStoreCosts, saveVariantCosts } from "@/app/actions";
import { PeriodSelector } from "@/components/PeriodSelector";
import { MetaBar, NoSyncState, StatusPill } from "@/components/analytics";
import { EmptyState, PageHeader, Panel } from "@/components/ui";

const STORE_INPUTS: { key: keyof StoreCosts; label: string; hint: string; unit: "money" | "pct" }[] = [
  { key: "shipping_cost_per_order", label: "Shipping cost / order", hint: "What you pay carriers per order", unit: "money" },
  { key: "packaging_cost_per_order", label: "Packaging / order", hint: "Boxes, mailers, inserts", unit: "money" },
  { key: "transaction_fee_percent", label: "Transaction fee %", hint: "e.g. 2.9 for 2.9%", unit: "pct" },
  { key: "transaction_fee_per_order", label: "Transaction fee / order", hint: "e.g. 0.30", unit: "money" },
  { key: "advertising_per_month", label: "Advertising / month", hint: "Total ad spend per month", unit: "money" },
  { key: "other_opex_per_month", label: "Other expenses / month", hint: "Apps, subscriptions, tools…", unit: "money" },
];

const SOURCE_LABEL: Record<string, string> = {
  user_input: "You entered",
  shopify_cost_per_item: "Shopify cost per item",
  missing: "Missing",
};

type Params = PeriodParams & { msg?: string };

export default async function ProfitabilityPage({ searchParams }: { searchParams: Promise<Params> }) {
  const params = await searchParams;
  const [res, costs] = await Promise.all([getProfitability(params), getCosts()]);
  const qs = new URLSearchParams(Object.entries(params).filter(([k, v]) => v && k !== "msg") as [string, string][]);
  const returnTo = `/profitability${qs.toString() ? `?${qs}` : ""}`;

  if (!res.ok) {
    return (
      <>
        <PageHeader code="PNL" title="Profitability" />
        <EmptyState title="Profitability unavailable">{res.error}</EmptyState>
      </>
    );
  }
  const { meta, metrics, products, missing_inputs, cogs_coverage_pct } = res.data;
  const c = meta.currency;
  const fmt = (kind: string, v: number | null) => (kind === "percent" ? pct(v) : money(v, c));

  return (
    <>
      <PageHeader
        code="PNL"
        title="Profitability"
        subtitle="Revenue is not profit. Results use only costs you enter (or Shopify's own cost per item). Anything missing is named, and results that depend on it are marked incomplete."
        right={<PeriodSelector basePath="/profitability" current={params} />}
      />
      <MetaBar meta={meta} compare={false} />
      {params.msg && (
        <div className="mb-4 rounded-sm border border-border-strong bg-panel-2 px-3 py-2 text-[12px]">{params.msg}</div>
      )}

      {meta.status === "missing" ? (
        <NoSyncState />
      ) : (
        <>
          {missing_inputs.length > 0 && (
            <div className="mb-4 rounded-sm border border-warn/40 bg-warn/5 px-3 py-2 text-[12px]">
              <div className="font-medium text-warn">Incomplete: {missing_inputs.length} cost input{missing_inputs.length > 1 ? "s" : ""} missing</div>
              <ul className="mt-1 list-disc pl-4 text-dim">
                {missing_inputs.map((m) => <li key={m}>{m}</li>)}
              </ul>
              <div className="mt-1 text-faint">Enter them below. Blank means unknown; enter 0 only if the cost really is zero.</div>
            </div>
          )}

          <div className="mb-4 grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-4">
            {metrics.map((m) => (
              <div key={m.key} className="rounded-[3px] border border-border bg-panel px-3 py-2.5" title={m.formula}>
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-[11px] text-dim">{m.label}</span>
                  <StatusPill status={m.value === null ? "missing" : m.status} />
                </div>
                <div className={`num mt-1.5 text-[20px] leading-none ${m.value === null ? "text-faint" : m.value < 0 ? "text-neg" : ""}`}>
                  {fmt(m.kind, m.value) ?? "—"}
                </div>
                <div className="mt-1.5 text-[11px] text-faint">{m.formula}</div>
                {m.notes.slice(0, 2).map((n) => (
                  <div key={n} className="mt-0.5 line-clamp-2 text-[11px] text-warn" title={n}>{n}</div>
                ))}
              </div>
            ))}
          </div>

          <Panel title="Profit by product" className="mb-4"
            right={cogs_coverage_pct !== null ? <span className="text-[11px] text-faint">COGS known for {pct(cogs_coverage_pct)} of net sales</span> : undefined}>
            {products.length === 0 ? (
              <div className="text-[12px] text-faint">No product sales in this period.</div>
            ) : (
              <table className="w-full text-left text-[12px]">
                <thead className="text-[10px] uppercase tracking-wider text-faint">
                  <tr className="border-b border-border">
                    <th className="py-1.5">Product</th><th>Net units</th><th>Net sales</th><th>COGS</th><th>Gross profit</th><th>Margin</th><th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {products.map((p) => (
                    <tr key={p.product_gid} className="border-b border-border last:border-0">
                      <td className="py-1.5">{p.title}</td>
                      <td className="num">{p.net_units}</td>
                      <td className="num">{money(p.net_sales, c)}</td>
                      <td className="num">{money(p.cogs, c) ?? <span className="text-faint">unknown</span>}</td>
                      <td className="num">{money(p.gross_profit, c) ?? <span className="text-faint">—</span>}</td>
                      <td className="num">{pct(p.gross_margin_pct) ?? "—"}</td>
                      <td><StatusPill status={p.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>
        </>
      )}

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Store-wide costs">
          {!costs.ok ? (
            <div className="text-[12px] text-neg">{costs.error}</div>
          ) : (
            <form action={saveStoreCosts} className="space-y-2.5">
              <input type="hidden" name="return_to" value={returnTo} />
              {STORE_INPUTS.map((f) => (
                <label key={f.key} className="grid grid-cols-[1fr_140px] items-center gap-3">
                  <span>
                    <span className="block text-[12px]">{f.label}</span>
                    <span className="block text-[11px] text-faint">{f.hint}</span>
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="w-3 text-[11px] text-faint">{f.unit === "money" ? "$" : ""}</span>
                    <input
                      name={f.key}
                      inputMode="decimal"
                      defaultValue={costs.data.store[f.key] === null ? "" : String(Number(costs.data.store[f.key]))}
                      placeholder="unknown"
                      pattern="[0-9]*[.,]?[0-9]*"
                      className="num w-full rounded-sm border border-border-strong bg-panel-2 px-2 py-1 text-right text-[12px] placeholder:text-faint"
                    />
                    <span className="w-3 text-[11px] text-faint">{f.unit === "pct" ? "%" : ""}</span>
                  </span>
                </label>
              ))}
              <div className="flex items-center justify-between pt-1">
                <span className="text-[11px] text-faint">Stored in ATLAS only. Nothing is sent to Shopify.</span>
                <button className="rounded-sm border border-accent px-3 py-1 text-[12px] text-accent hover:bg-accent-dim">Save store costs</button>
              </div>
            </form>
          )}
        </Panel>

        <Panel title="Product costs (COGS per unit)">
          {!costs.ok ? (
            <div className="text-[12px] text-neg">{costs.error}</div>
          ) : costs.data.variants.length === 0 ? (
            <div className="text-[12px] text-faint">No products synced yet. Products appear here after you add them in Shopify and sync.</div>
          ) : (
            <form action={saveVariantCosts}>
              <input type="hidden" name="return_to" value={returnTo} />
              <div className="max-h-[420px] overflow-y-auto">
                <table className="w-full text-left text-[12px]">
                  <thead className="sticky top-0 bg-panel text-[10px] uppercase tracking-wider text-faint">
                    <tr className="border-b border-border">
                      <th className="py-1.5">Product</th><th>Price</th><th>Shopify cost</th><th>Your cost</th><th>Used</th>
                    </tr>
                  </thead>
                  <tbody>
                    {costs.data.variants.map((v) => (
                      <tr key={v.variant_gid} className="border-b border-border last:border-0">
                        <td className="py-1.5 pr-2">
                          {v.product_title}
                          {v.variant_title !== "Default Title" && <span className="text-faint"> / {v.variant_title}</span>}
                          {v.sku && <div className="num text-[10px] text-faint">{v.sku}</div>}
                        </td>
                        <td className="num pr-2">{money(v.price, costs.data.currency)}</td>
                        <td className="num pr-2 text-dim">{money(v.shopify_unit_cost, costs.data.currency) ?? "—"}</td>
                        <td className="pr-2">
                          <input
                            name={`cogs:${v.variant_gid}`}
                            inputMode="decimal"
                            aria-label={`Unit cost for ${v.product_title} ${v.variant_title}`}
                            defaultValue={v.user_cogs ?? ""}
                            placeholder={v.shopify_unit_cost !== null ? "use Shopify" : "unknown"}
                            className="num w-24 rounded-sm border border-border-strong bg-panel-2 px-2 py-1 text-right text-[12px] placeholder:text-faint"
                          />
                        </td>
                        <td className={`text-[11px] ${v.source === "missing" ? "text-warn" : "text-dim"}`}>{SOURCE_LABEL[v.source] ?? v.source}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex justify-end pt-3">
                <button className="rounded-sm border border-accent px-3 py-1 text-[12px] text-accent hover:bg-accent-dim">Save product costs</button>
              </div>
            </form>
          )}
        </Panel>
      </div>
    </>
  );
}
