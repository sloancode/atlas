import Link from "next/link";
import { getInventory, getOverview, getProducts, getTraffic, productIdFromGid, type PeriodParams, type TrafficT } from "@/lib/api";
import { money, num } from "@/lib/format";
import { PeriodSelector } from "@/components/PeriodSelector";
import { Change, KpiTile, MetaBar, NoSyncState } from "@/components/analytics";
import { ChartFormat } from "@/components/ChartFormat";
import { EmptyState, PageHeader, Panel } from "@/components/ui";

const HEADLINE = ["gross_sales", "net_sales", "orders", "aov", "units_sold", "returns"];
const SECONDARY = ["discounts", "refunds_total", "units_returned", "shipping", "taxes", "cancelled_orders"];

export default async function ShopifyPage({ searchParams }: { searchParams: Promise<PeriodParams> }) {
  const params = await searchParams;
  const [ov, prods, inv, traffic] = await Promise.all([getOverview(params), getProducts(params), getInventory(), getTraffic(params)]);

  if (!ov.ok) {
    return (
      <>
        <PageHeader code="SHP" title="Shopify" />
        <EmptyState title="Analytics unavailable">{ov.error}</EmptyState>
      </>
    );
  }
  const { meta, kpis, daily, has_sales } = ov.data;
  const k = Object.fromEntries(kpis.map((x) => [x.key, x]));
  const currency = meta.currency;
  const synced = meta.status !== "missing";

  const sold = prods.ok ? prods.data.products.filter((p) => p.net_sales > 0) : [];
  const best = sold.slice(0, 5);
  const worst = prods.ok
    ? prods.data.products
        .filter((p) => p.in_catalog && p.status === "ACTIVE")
        .sort((a, b) => a.net_sales - b.net_sales)
        .slice(0, 5)
    : [];
  const low = inv.ok
    ? inv.data.variants.filter((v) => ["out_of_stock", "stockout_risk", "low_stock"].includes(v.status)).slice(0, 6)
    : [];

  return (
    <>
      <PageHeader
        code="SHP"
        title="Shopify"
        subtitle="Executive dashboard. Gross sales, discounts, returns, net sales and refunds are separate metrics with fixed definitions (hover a tile for its definition)."
        right={<PeriodSelector basePath="/shopify" current={params} />}
      />
      <MetaBar meta={meta} />

      {!synced ? (
        <NoSyncState />
      ) : (
        <>
          <div className="mb-2 grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
            {HEADLINE.map((key) => k[key] && <KpiTile key={key} kpi={k[key]} currency={currency} />)}
          </div>
          <div className="mb-4 grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
            {SECONDARY.map((key) => k[key] && <KpiTile key={key} kpi={k[key]} currency={currency} />)}
          </div>

          <Panel
            title="Net sales by day"
            className="mb-4"
            right={<span className="text-[11px] text-faint">Blue: net positive · Red: refunds exceeded sales</span>}
          >
            {has_sales ? (
              <>
                <ChartFormat daily={daily} currency={currency} />
                <details className="mt-2 text-[11px]">
                  <summary className="cursor-pointer text-dim hover:text-text">Show as table</summary>
                  <table className="num mt-2 w-full max-w-xl text-left">
                    <thead className="text-faint">
                      <tr><th className="py-1">Date</th><th>Orders</th><th>Gross</th><th>Net</th></tr>
                    </thead>
                    <tbody>
                      {daily.map((d) => (
                        <tr key={d.date} className="border-t border-border">
                          <td className="py-0.5">{d.date}</td>
                          <td>{d.orders}</td>
                          <td>{money(d.gross_sales, currency)}</td>
                          <td>{money(d.net_sales, currency)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </details>
              </>
            ) : (
              <EmptyState title="No sales in this period">
                The sync succeeded and found no qualifying orders between these dates. Zero is the real value here.
              </EmptyState>
            )}
          </Panel>

          <Panel title="Traffic & conversion" className="mb-4"
            right={<span className="text-[11px] text-faint">Shopify analytics (ShopifyQL){traffic.ok && traffic.data.as_of ? ` · fetched ${new Date(traffic.data.as_of).toLocaleTimeString()}` : ""}</span>}>
            {traffic.ok ? <Funnel t={traffic.data} /> : <div className="text-[12px] text-neg">{traffic.error}</div>}
          </Panel>

          <div className="grid gap-4 xl:grid-cols-3">
            <Panel title="Best performers (net sales)">
              {best.length ? (
                <ProductList rows={best} currency={currency} />
              ) : (
                <div className="text-[12px] text-faint">No product sales in this period.</div>
              )}
            </Panel>
            <Panel title="Weakest active products">
              {worst.length ? (
                <ProductList rows={worst} currency={currency} />
              ) : (
                <div className="text-[12px] text-faint">No active products synced.</div>
              )}
            </Panel>
            <Panel
              title="Low inventory"
              right={<Link href="/inventory" className="text-[11px] text-accent hover:underline">Inventory →</Link>}
            >
              {!inv.ok ? (
                <div className="text-[12px] text-neg">{inv.error}</div>
              ) : low.length ? (
                <ul className="space-y-1.5">
                  {low.map((v) => (
                    <li key={v.variant_gid} className="flex justify-between gap-2 text-[12px]">
                      <span className="truncate">
                        {v.product_title}
                        {v.variant_title !== "Default Title" && <span className="text-faint"> / {v.variant_title}</span>}
                      </span>
                      <span className="num shrink-0 text-warn">
                        {num(v.available)} left{v.days_of_cover !== null && ` · ${num(v.days_of_cover)}d`}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="text-[12px] text-faint">
                  {inv.data.variants.length ? "No variants below alert thresholds." : "No inventory synced."}
                </div>
              )}
            </Panel>
          </div>
        </>
      )}
    </>
  );
}

function ProductList({
  rows,
  currency,
}: {
  rows: { product_gid: string; title: string; net_sales: number; growth_pct: number | null; units_sold: number }[];
  currency: string | null;
}) {
  return (
    <ul className="text-[12px]">
      {rows.map((p) => {
        const id = productIdFromGid(p.product_gid);
        return (
          <li
            key={p.product_gid}
            className="grid grid-cols-[minmax(0,1fr)_auto_2.5rem_4.5rem] items-center gap-2 border-b border-border py-1.5 last:border-0"
          >
            <span className="truncate" title={p.title}>
              {id ? <Link href={`/products/${id}`} className="hover:text-accent">{p.title}</Link> : p.title}
            </span>
            <span className="num text-right">{money(p.net_sales, currency)}</span>
            <span className="num text-right text-faint">{num(p.units_sold)}u</span>
            <span className="text-right text-[11px]"><Change value={p.growth_pct} /></span>
          </li>
        );
      })}
    </ul>
  );
}


function Funnel({ t }: { t: TrafficT }) {
  if (t.status === "missing") return <div className="text-[12px] text-faint">{t.notes.join(" ") || "Unavailable."}</div>;
  const steps = [
    ["Sessions", t.sessions], ["Added to cart", t.cart_sessions], ["Reached checkout", t.checkout_sessions], ["Purchased", t.completed_sessions],
  ] as const;
  const top = t.sessions || 0;
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_280px]">
      <div className="space-y-2">
        {steps.map(([label, v]) => (
          <div key={label} className="grid grid-cols-[130px_1fr_90px] items-center gap-3 text-[12px]">
            <span className="text-dim">{label}</span>
            <div className="h-2 overflow-hidden rounded-full bg-panel-2" aria-hidden>
              <div className="h-full bg-[var(--viz-pos)]" style={{ width: `${top && v !== null ? Math.max((v / top) * 100, v ? 2 : 0) : 0}%` }} />
            </div>
            <span className="num text-right">{v === null ? "—" : num(v)}{top && v !== null && label !== "Sessions" ? <span className="text-faint"> ({((v / top) * 100).toFixed(1)}%)</span> : null}</span>
          </div>
        ))}
        <div className="text-[12px]">Conversion rate: <span className="num">{t.conversion_rate_pct === null ? "— (no sessions)" : `${t.conversion_rate_pct}%`}</span></div>
        {t.notes.map((n) => <div key={n} className="text-[11px] text-faint">{n}</div>)}
      </div>
      <div>
        <div className="mb-1 text-[10px] uppercase tracking-wider text-faint">Top traffic sources</div>
        {t.sources.length === 0 ? <div className="text-[12px] text-faint">No sessions recorded.</div> : (
          <ul className="space-y-1 text-[12px]">{t.sources.map((src) => (
            <li key={src.source} className="flex justify-between"><span className="truncate text-dim">{src.source}</span>
              <span className="num">{num(src.sessions)}{src.conversion_rate_pct !== null && <span className="text-faint"> · {src.conversion_rate_pct}%</span>}</span></li>
          ))}</ul>
        )}
      </div>
    </div>
  );
}
