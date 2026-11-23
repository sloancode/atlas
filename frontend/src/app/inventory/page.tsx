import Link from "next/link";
import { getAlertRule, getInventory, productIdFromGid } from "@/lib/api";
import { money, num } from "@/lib/format";
import { saveAlertRule } from "@/app/actions";
import { MetaBar, NoSyncState } from "@/components/analytics";
import { EmptyState, PageHeader, Panel } from "@/components/ui";

const STATUS: Record<string, { label: string; cls: string }> = {
  out_of_stock: { label: "Out of stock", cls: "text-neg" },
  stockout_risk: { label: "Stockout risk", cls: "text-neg" },
  low_stock: { label: "Low stock", cls: "text-warn" },
  overstock: { label: "Overstock", cls: "text-info" },
  no_recent_sales: { label: "No recent sales", cls: "text-info" },
  ok: { label: "OK", cls: "text-pos" },
  untracked: { label: "Not tracked", cls: "text-faint" },
};

export default async function InventoryPage({ searchParams }: { searchParams: Promise<{ status?: string; msg?: string }> }) {
  const params = await searchParams;
  const [res, rule] = await Promise.all([getInventory(), getAlertRule()]);
  if (!res.ok) {
    return (
      <>
        <PageHeader code="INV" title="Inventory" />
        <EmptyState title="Inventory unavailable">{res.error}</EmptyState>
      </>
    );
  }
  const { meta, variants, summary } = res.data;
  const rows = params.status ? variants.filter((v) => v.status === params.status) : variants;
  const field = (name: string, label: string, hint: string, value: number | null | undefined) => (
    <label className="grid grid-cols-[1fr_90px] items-center gap-3">
      <span>
        <span className="block text-[12px]">{label}</span>
        <span className="block text-[11px] text-faint">{hint}</span>
      </span>
      <input name={name} inputMode="numeric" defaultValue={value ?? ""} pattern="[0-9]*"
        className="num rounded-sm border border-border-strong bg-panel-2 px-2 py-1 text-right text-[12px]" />
    </label>
  );

  return (
    <>
      <PageHeader
        code="INV"
        title="Inventory"
        subtitle="Coverage estimated from the last 30 days of net sales. Alerts only inform you. ATLAS never changes stock or places purchase orders."
      />
      <MetaBar meta={meta} compare={false} />
      {params.msg && <div className="mb-4 rounded-sm border border-border-strong bg-panel-2 px-3 py-2 text-[12px]">{params.msg}</div>}

      {meta.status === "missing" && variants.length === 0 ? (
        <NoSyncState />
      ) : (
        <div className="grid gap-4 xl:grid-cols-[1fr_300px]">
          <div>
            <div className="mb-3 flex flex-wrap gap-1.5 text-[11px]">
              <Link href="/inventory" className={`rounded-sm border px-2 py-[3px] ${!params.status ? "border-accent text-accent" : "border-border text-dim hover:text-text"}`}>
                All ({variants.length})
              </Link>
              {Object.entries(STATUS).map(([k, s]) => (summary[k] ?? 0) > 0 && (
                <Link key={k} href={`/inventory?status=${k}`}
                  className={`rounded-sm border px-2 py-[3px] ${params.status === k ? "border-accent text-accent" : "border-border text-dim hover:text-text"}`}>
                  <span className={s.cls}>●</span> {s.label} ({summary[k]})
                </Link>
              ))}
            </div>
            {rows.length === 0 ? (
              <EmptyState title={variants.length ? "Nothing in this category" : "No inventory synced"}>
                {variants.length ? undefined : "Your store has no products yet. Add products in Shopify, then sync."}
              </EmptyState>
            ) : (
              <div className="overflow-x-auto rounded-[3px] border border-border bg-panel">
                <table className="w-full min-w-[760px] text-left text-[12px]">
                  <thead className="text-[10px] uppercase tracking-wider text-faint">
                    <tr className="border-b border-border">
                      <th className="px-2 py-2">Product</th><th className="px-2">Available</th><th className="px-2">30d net units</th>
                      <th className="px-2">Per day</th><th className="px-2">Cover</th><th className="px-2">Status</th><th className="px-2">Why</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((v) => {
                      const id = productIdFromGid(v.product_gid);
                      const s = STATUS[v.status] ?? { label: v.status, cls: "" };
                      return (
                        <tr key={v.variant_gid} className="border-b border-border align-top last:border-0">
                          <td className="px-2 py-2">
                            {id ? <Link href={`/products/${id}`} className="hover:text-accent">{v.product_title}</Link> : v.product_title}
                            {v.variant_title !== "Default Title" && <span className="text-faint"> / {v.variant_title}</span>}
                            <div className="num text-[10px] text-faint">{v.sku ?? "no SKU"} · {money(v.price, meta.currency)}</div>
                          </td>
                          <td className="num px-2 py-2">{v.available ?? "—"}</td>
                          <td className="num px-2 py-2">{v.net_units_30d}</td>
                          <td className="num px-2 py-2">{num(v.velocity_per_day, 2)}</td>
                          <td className="num px-2 py-2">{v.days_of_cover === null ? "—" : `${num(v.days_of_cover)}d`}</td>
                          <td className={`whitespace-nowrap px-2 py-2 ${s.cls}`}>● {s.label}</td>
                          <td className="px-2 py-2 text-[11px] text-dim">{v.reasons.join(" ")}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <Panel title="Alert thresholds">
            {!rule.ok ? (
              <div className="text-[12px] text-neg">{rule.error}</div>
            ) : (
              <form action={saveAlertRule} className="space-y-3">
                {field("min_units", "Low stock at", "Units or fewer", rule.data.min_units)}
                {field("min_days_of_cover", "Stockout risk under", "Days of cover", rule.data.min_days_of_cover)}
                {field("max_days_of_cover", "Overstock above", "Days of cover", rule.data.max_days_of_cover)}
                <button className="w-full rounded-sm border border-accent px-3 py-1 text-[12px] text-accent hover:bg-accent-dim">Save thresholds</button>
                <p className="text-[11px] text-faint">Applies to all products. Blank uses the built-in default.</p>
              </form>
            )}
          </Panel>
        </div>
      )}
    </>
  );
}
