import Link from "next/link";
import { getProductDetail, type PeriodParams } from "@/lib/api";
import { money, num } from "@/lib/format";
import { PeriodSelector } from "@/components/PeriodSelector";
import { Change, FLAG_TONE, MetaBar } from "@/components/analytics";
import { UnitsChart } from "@/components/UnitsChart";
import { EmptyState, MetricTile, PageHeader, Panel } from "@/components/ui";

const STATUS_LABEL: Record<string, string> = {
  out_of_stock: "Out of stock", stockout_risk: "Stockout risk", low_stock: "Low stock",
  overstock: "Overstock", no_recent_sales: "No recent sales", ok: "OK", untracked: "Not tracked",
};

export default async function ProductPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<PeriodParams>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const res = await getProductDetail(id, sp);
  if (!res.ok) {
    return (
      <>
        <PageHeader code="PRD" title="Product" />
        <EmptyState title="Product not available">{res.error}</EmptyState>
        <Link href="/products" className="mt-3 inline-block text-[12px] text-accent hover:underline">← All products</Link>
      </>
    );
  }
  const { meta, product: p, variants, daily } = res.data;
  const c = meta.currency;
  return (
    <>
      <Link href="/products" className="mb-2 inline-block text-[11px] text-dim hover:text-accent">← All products</Link>
      <PageHeader
        code="PRD"
        title={p.title}
        subtitle={`${p.skus.join(", ") || "No SKU"} · ${p.status?.toLowerCase() ?? "not in catalog"}${p.rank ? ` · #${p.rank} by net sales` : ""}`}
        right={<PeriodSelector basePath={`/products/${id}`} current={sp} />}
      />
      <MetaBar meta={meta} />
      <div className="mb-4 grid gap-4 lg:grid-cols-[180px_1fr]">
        <div className="flex aspect-square items-center justify-center overflow-hidden rounded-[3px] border border-border bg-panel">
          {p.image_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={p.image_url} alt={p.title} className="h-full w-full object-cover" />
          ) : (
            <span className="text-[11px] text-faint">No image</span>
          )}
        </div>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          <MetricTile label="Net sales" value={money(p.net_sales, c)} status="historical" note={`prev ${money(p.prev_net_sales, c)}`} />
          <MetricTile label="Gross sales" value={money(p.gross_sales, c)} status="historical" />
          <MetricTile label="Units sold" value={num(p.units_sold)} status="historical"
            note={p.units_returned ? `${p.units_returned} returned` : undefined} />
          <MetricTile label="Orders" value={num(p.orders)} status="historical" note={`${num(p.order_frequency_per_week, 1)} per week`} />
          <div className="rounded-[3px] border border-border bg-panel px-3 py-2.5">
            <div className="text-[11px] text-dim">Growth vs previous</div>
            <div className="mt-2 text-[18px]"><Change value={p.growth_pct} /></div>
          </div>
          <MetricTile label="Inventory" value={p.available === null ? null : num(p.available)} status="historical"
            note={p.available === null ? "Not tracked" : undefined} />
          <MetricTile label="Days of cover" value={p.days_of_cover === null ? null : `${num(p.days_of_cover)}d`}
            status="estimated" note={`${num(p.velocity_per_day, 2)} units/day (30d)`} />
          <MetricTile label="Price" value={p.price_min === null ? null
            : p.price_min === p.price_max ? money(p.price_min, c) : `${money(p.price_min, c)}–${money(p.price_max, c)}`} status="historical" />
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Panel title="Units sold by day" className="xl:col-span-2">
          {daily.some((d) => d.units > 0) ? <UnitsChart daily={daily} currency={c} />
            : <div className="text-[12px] text-faint">No units sold in this period.</div>}
        </Panel>
        <Panel title="Signals">
          {p.flags.length ? (
            <ul className="space-y-2">
              {p.flags.map((f) => (
                <li key={f.key + f.label}>
                  <span className={`text-[11px] font-medium ${(FLAG_TONE[f.key] ?? "").split(" ").find((x) => x.startsWith("text-")) ?? "text-dim"}`}>{f.label}</span>
                  <div className="text-[12px] text-dim">{f.reason}</div>
                </li>
              ))}
            </ul>
          ) : (
            <div className="text-[12px] text-faint">No signals for this product right now.</div>
          )}
        </Panel>
      </div>

      {p.opportunity && (
        <Panel title="Opportunity score" className="mt-4"
          right={<span className="text-[11px] text-faint">{p.opportunity.disclaimer}</span>}>
          <div className="grid gap-4 md:grid-cols-[160px_1fr]">
            <div>
              <div className="num text-[40px] leading-none">{p.opportunity.score}<span className="text-[14px] text-faint">/100</span></div>
              <div className="mt-1 text-[11px] text-dim">Confidence: {p.opportunity.confidence}</div>
            </div>
            <div className="space-y-2">
              {p.opportunity.components.map((comp) => (
                <div key={comp.name}>
                  <div className="flex justify-between text-[12px]">
                    <span>{comp.name}</span>
                    <span className="num text-dim">{comp.points} / {comp.max_points}</span>
                  </div>
                  <div className="mt-0.5 h-1.5 overflow-hidden rounded-full bg-panel-2" aria-hidden>
                    <div className="h-full bg-[var(--viz-pos)]" style={{ width: `${(comp.points / comp.max_points) * 100}%` }} />
                  </div>
                  <div className="mt-0.5 text-[11px] text-faint">{comp.reason}</div>
                </div>
              ))}
              <div className="text-[11px] text-dim">{p.opportunity.summary}</div>
            </div>
          </div>
        </Panel>
      )}

      <Panel title="Variants & inventory" className="mt-4">
        <table className="w-full text-left text-[12px]">
          <thead className="text-[10px] uppercase tracking-wider text-faint">
            <tr className="border-b border-border">
              <th className="py-1.5">Variant</th><th>SKU</th><th>Price</th><th>Available</th><th>30d units</th><th>Cover</th><th>Status</th>
            </tr>
          </thead>
          <tbody>
            {variants.map((v) => (
              <tr key={v.variant_gid} className="border-b border-border align-top last:border-0">
                <td className="py-1.5">{v.variant_title}</td>
                <td className="num text-dim">{v.sku ?? "—"}</td>
                <td className="num">{money(v.price, c)}</td>
                <td className="num">{v.available ?? "—"}</td>
                <td className="num">{v.net_units_30d}</td>
                <td className="num">{v.days_of_cover === null ? "—" : `${num(v.days_of_cover)}d`}</td>
                <td title={v.reasons.join(" ")}>{STATUS_LABEL[v.status] ?? v.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </>
  );
}
