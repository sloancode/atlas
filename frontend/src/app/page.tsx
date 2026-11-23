import Link from "next/link";
import { getOverview, getSystemStatus } from "@/lib/api";
import { KpiTile } from "@/components/analytics";
import { EmptyState, MetricTile, PageHeader, Panel, StateBadge } from "@/components/ui";
import { fmtDateTime } from "@/lib/format";

const KPIS = ["gross_sales", "net_sales", "orders", "aov", "units_sold", "refunds_total"];

export default async function OverviewPage() {
  const [res, ov] = await Promise.all([getSystemStatus(), getOverview({ period: "30d" })]);
  const kpiMap = ov.ok ? Object.fromEntries(ov.data.kpis.map((k) => [k.key, k])) : {};
  const synced = ov.ok && ov.data.meta.status !== "missing";
  const providers = res.ok ? res.data.providers : [];
  const shopify = providers.find((p) => p.name === "shopify");
  const shopifyReady = shopify?.state === "connected";

  return (
    <>
      <PageHeader
        code="OVR"
        title="Overview"
        subtitle="Ecommerce performance, research activity and system readiness. Business revenue and simulated portfolio results are kept in separate ledgers."
      />

      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-[11px] font-medium uppercase tracking-[0.12em] text-dim">
          Shopify · last 30 days
        </h2>
        <span className="text-[11px] text-faint">
          Source: Shopify Admin API · as of {synced && ov.ok ? fmtDateTime(ov.data.meta.as_of) : "—"} ·{" "}
          <Link href="/shopify" className="text-accent hover:underline">Dashboard →</Link>
        </span>
      </div>
      <div className="mb-5 grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
        {KPIS.map((k) =>
          synced && kpiMap[k] ? (
            <KpiTile key={k} kpi={kpiMap[k]} currency={ov.ok ? ov.data.meta.currency : null} />
          ) : (
            <MetricTile
              key={k}
              label={k.replace("_", " ")}
              value={null}
              status="missing"
              note={shopifyReady ? "Sync not yet run" : "Shopify not connected"}
            />
          ),
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="Engines" className="lg:col-span-2">
          <table className="w-full text-left">
            <thead className="text-[10px] uppercase tracking-wider text-faint">
              <tr className="border-b border-border">
                <th className="py-1.5 font-medium">Engine</th>
                <th className="font-medium">Status</th>
                <th className="font-medium">Next step</th>
              </tr>
            </thead>
            <tbody className="[&_td]:py-2">
              <tr className="border-b border-border">
                <td>Shopify business intelligence</td>
                <td>{shopify && <StateBadge state={shopify.state} />}</td>
                <td className="text-dim">
                  {shopifyReady ? "Live: dashboards, products, profitability, inventory" : "Add Shopify app credentials"}
                </td>
              </tr>
              <tr className="border-b border-border">
                <td>Stock &amp; ETF research</td>
                <td>
                  <StateBadge state="planned" />
                </td>
                <td className="text-dim">Phase 5: market data adapters</td>
              </tr>
              <tr>
                <td>eBay Sell APIs</td>
                <td>
                  <StateBadge state="planned" />
                </td>
                <td className="text-dim">Phase 6: intentionally not connected</td>
              </tr>
            </tbody>
          </table>
        </Panel>

        <Panel title="Data sources" right={<Link href="/settings" className="text-[11px] text-accent hover:underline">Settings →</Link>}>
          {!res.ok ? (
            <EmptyState title="Backend unreachable">{res.error}</EmptyState>
          ) : (
            <ul className="space-y-2">
              {providers.map((p) => (
                <li key={p.name} className="flex items-center justify-between gap-2">
                  <span className="truncate text-dim">{p.display_name}</span>
                  <StateBadge state={p.state} />
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </>
  );
}
