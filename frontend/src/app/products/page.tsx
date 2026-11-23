import Link from "next/link";
import { getProducts, productIdFromGid, type PeriodParams, type ProductRow } from "@/lib/api";
import { money, num } from "@/lib/format";
import { PeriodSelector } from "@/components/PeriodSelector";
import { Change, FLAG_TONE, FlagChip, MetaBar, NoSyncState } from "@/components/analytics";
import { EmptyState, PageHeader } from "@/components/ui";

type Params = PeriodParams & { q?: string; sort?: string; flag?: string };

const SORTS: Record<string, { label: string; fn: (a: ProductRow, b: ProductRow) => number }> = {
  rank: { label: "Rank", fn: (a, b) => (a.rank ?? 1e9) - (b.rank ?? 1e9) || a.title.localeCompare(b.title) },
  net: { label: "Net sales", fn: (a, b) => b.net_sales - a.net_sales },
  units: { label: "Units", fn: (a, b) => b.units_sold - a.units_sold },
  growth: { label: "Growth", fn: (a, b) => (b.growth_pct ?? -1e9) - (a.growth_pct ?? -1e9) },
  cover: { label: "Days of cover", fn: (a, b) => (a.days_of_cover ?? 1e9) - (b.days_of_cover ?? 1e9) },
  stock: { label: "Inventory", fn: (a, b) => (b.available ?? -1) - (a.available ?? -1) },
  score: { label: "Opportunity", fn: (a, b) => (b.opportunity?.score ?? -1) - (a.opportunity?.score ?? -1) },
};

const FLAG_FILTERS = [
  ["best_seller", "Best sellers"],
  ["accelerating", "Accelerating"],
  ["losing_momentum", "Losing momentum"],
  ["high_inventory_weak_demand", "High stock / weak demand"],
  ["low_inventory_strong_demand", "Low stock / selling"],
] as const;

export default async function ProductsPage({ searchParams }: { searchParams: Promise<Params> }) {
  const params = await searchParams;
  const res = await getProducts(params);
  const base = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v && k !== "sort" && k !== "flag") base.set(k, v);
  const link = (extra: Record<string, string | undefined>) => {
    const q = new URLSearchParams(base);
    for (const [k, v] of Object.entries(extra)) {
      if (v) q.set(k, v);
      else q.delete(k);
    }
    return `/products?${q.toString()}`;
  };

  if (!res.ok) {
    return (
      <>
        <PageHeader code="PRD" title="Products" />
        <EmptyState title="Product analytics unavailable">{res.error}</EmptyState>
      </>
    );
  }
  const { meta, products, seasonality } = res.data;
  const currency = meta.currency;
  const sort = SORTS[params.sort ?? "rank"] ? params.sort ?? "rank" : "rank";
  const q = (params.q ?? "").trim().toLowerCase();
  const rows = products
    .filter((p) => !q || p.title.toLowerCase().includes(q) || p.skus.some((s) => s.toLowerCase().includes(q)))
    .filter((p) => !params.flag || p.flags.some((f) => f.key === params.flag))
    .sort(SORTS[sort].fn);

  return (
    <>
      <PageHeader
        code="PRD"
        title="Products"
        subtitle="Every product's performance for the selected period. Flags use the last 30 days of sales and current inventory; hover a flag to see the numbers behind it."
        right={<PeriodSelector basePath="/products" current={params} />}
      />
      <MetaBar meta={meta} />
      {meta.status === "missing" ? (
        <NoSyncState />
      ) : (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-3">
            <form action="/products" method="get" className="flex items-center gap-1.5">
              {Object.entries(params).map(
                ([k, v]) => v && k !== "q" && <input key={k} type="hidden" name={k} value={v} />,
              )}
              <input
                name="q"
                defaultValue={params.q}
                placeholder="Search title or SKU"
                aria-label="Search products"
                className="w-56 rounded-sm border border-border-strong bg-panel px-2 py-1 text-[12px] placeholder:text-faint"
              />
              <button className="rounded-sm border border-border-strong px-2 py-1 text-[11px] text-dim hover:text-text">
                Search
              </button>
            </form>
            <div className="flex flex-wrap gap-1.5 text-[11px]">
              <Link href={link({ flag: undefined, sort: params.sort })}
                className={`rounded-sm border px-2 py-[3px] ${!params.flag ? "border-accent text-accent" : "border-border text-dim hover:text-text"}`}>
                All ({products.length})
              </Link>
              {FLAG_FILTERS.map(([key, label]) => {
                const n = products.filter((p) => p.flags.some((f) => f.key === key)).length;
                return (
                  <Link key={key} href={link({ flag: key, sort: params.sort })}
                    className={`rounded-sm border px-2 py-[3px] ${params.flag === key ? "border-accent text-accent" : "border-border text-dim hover:text-text"}`}>
                    {label} ({n})
                  </Link>
                );
              })}
            </div>
          </div>

          {rows.length === 0 ? (
            <EmptyState title={products.length ? "No products match" : "No products synced"}>
              {products.length ? "Clear the search or filter." : "Your store has no products yet. Add products in Shopify, then sync."}
            </EmptyState>
          ) : (
            <div className="overflow-x-auto rounded-[3px] border border-border bg-panel">
              <table className="w-full min-w-[1080px] text-left text-[12px]">
                <thead className="text-[10px] uppercase tracking-wider text-faint">
                  <tr className="border-b border-border">
                    {[
                      ["rank", "#"], [null, "Product"], [null, "SKU"], [null, "Price"], ["units", "Units"],
                      ["net", "Net sales"], [null, "Orders/wk"], ["growth", "Growth"], ["stock", "Inventory"],
                      ["cover", "Cover"], ["score", "Opportunity"], [null, "Signals"],
                    ].map(([key, label]) => (
                      <th key={label} className="px-2 py-2 font-medium">
                        {key ? (
                          <Link href={link({ sort: key, flag: params.flag })} className={sort === key ? "text-accent" : "hover:text-text"}>
                            {label}{sort === key ? " ↓" : ""}
                          </Link>
                        ) : label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((p) => {
                    const id = productIdFromGid(p.product_gid);
                    return (
                      <tr key={p.product_gid} className="border-b border-border align-top last:border-0 hover:bg-panel-2">
                        <td className="num px-2 py-2 text-faint">{p.rank ?? "—"}</td>
                        <td className="px-2 py-2">
                          <div className="flex items-center gap-2">
                            {p.image_url ? (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img src={p.image_url} alt="" width={28} height={28} className="h-7 w-7 rounded-sm object-cover" />
                            ) : (
                              <div className="h-7 w-7 rounded-sm border border-border bg-panel-2" aria-hidden />
                            )}
                            <div className="min-w-0">
                              {id ? <Link href={`/products/${id}?${base.toString()}`} className="font-medium hover:text-accent">{p.title}</Link>
                                : <span className="font-medium">{p.title}</span>}
                              {p.status && p.status !== "ACTIVE" && <span className="ml-1.5 text-[10px] text-faint">{p.status.toLowerCase()}</span>}
                            </div>
                          </div>
                        </td>
                        <td className="num max-w-[120px] truncate px-2 py-2 text-dim">{p.skus.join(", ") || "—"}</td>
                        <td className="num px-2 py-2">
                          {p.price_min === null ? "—" : p.price_min === p.price_max ? money(p.price_min, currency)
                            : `${money(p.price_min, currency)}–${money(p.price_max, currency)}`}
                        </td>
                        <td className="num px-2 py-2">
                          {num(p.units_sold)}
                          {p.units_returned > 0 && <span className="text-faint"> (−{p.units_returned})</span>}
                        </td>
                        <td className="num px-2 py-2">{money(p.net_sales, currency)}</td>
                        <td className="num px-2 py-2 text-dim">{num(p.order_frequency_per_week, 1)}</td>
                        <td className="px-2 py-2"><Change value={p.growth_pct} /></td>
                        <td className="num px-2 py-2">{p.available === null ? <span className="text-faint">untracked</span> : num(p.available)}</td>
                        <td className="num px-2 py-2 text-dim">{p.days_of_cover === null ? "—" : `${num(p.days_of_cover)}d`}</td>
                        <td className="px-2 py-2" title={p.opportunity ? `${p.opportunity.summary} ${p.opportunity.disclaimer}` : undefined}>
                          {p.opportunity ? (
                            <span className="inline-flex items-center gap-1.5">
                              <span className="num text-[13px]">{p.opportunity.score}</span>
                              <span className="h-1 w-10 overflow-hidden rounded-full bg-panel-2" aria-hidden>
                                <span className="block h-full bg-[var(--viz-pos)]" style={{ width: `${p.opportunity.score}%` }} />
                              </span>
                              <span className="text-[10px] text-faint">{p.opportunity.confidence}</span>
                            </span>
                          ) : <span className="text-faint">—</span>}
                        </td>
                        <td className="px-2 py-2">
                          <div className="flex flex-wrap gap-1">
                            {p.flags.map((f) => <FlagChip key={f.key + f.label} label={f.label} reason={f.reason} tone={FLAG_TONE[f.key]} />)}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <p className="mt-3 text-[11px] text-faint">
            Seasonal demand: {seasonality === "available" ? "enough history to analyze (coming in Phase 4)." : seasonality}
            {" "}Opportunity score: a 0–100 relative ranking within your store to prioritise investigation, not a probability of success. Open a product to see how it is built.
          </p>
        </>
      )}
    </>
  );
}
