import { getStoreSettings, getSystemStatus, type ProviderStatus } from "@/lib/api";
import { setDigitalOnly } from "@/app/autopilot-actions";
import { Code, EmptyState, PageHeader, Panel, StateBadge } from "@/components/ui";
import { ShopifyDataPanel } from "@/components/ShopifyDataPanel";

const CATEGORY_LABEL: Record<ProviderStatus["category"], string> = {
  commerce: "Commerce",
  market_data: "Market data",
  filings: "Filings",
  ai: "AI",
};

function ScopeList({ label, items, tone }: { label: string; items: unknown; tone: string }) {
  if (!Array.isArray(items) || items.length === 0) return null;
  return (
    <div className="mt-1 text-[11px]">
      <span className="text-faint">{label}: </span>
      <span className={tone}>{items.join(", ")}</span>
    </div>
  );
}

export default async function SettingsPage({
  searchParams,
}: {
  searchParams: Promise<{ live?: string; sync?: string; msg?: string }>;
}) {
  const params = await searchParams;
  const live = params.live === "1";
  const [res, store] = await Promise.all([getSystemStatus(live), getStoreSettings()]);

  return (
    <>
      <PageHeader
        code="SET"
        title="Settings"
        subtitle="Data source configuration. Credentials are read from environment variables on the server and are never displayed here."
        right={
          <a
            href={live ? "/settings" : "/settings?live=1"}
            className="rounded-sm border border-border-strong px-2.5 py-1 text-[11px] text-dim hover:border-accent hover:text-accent"
          >
            {live ? "Show config only" : "Run live connection check"}
          </a>
        }
      />

      {!res.ok ? (
        <EmptyState title="Backend unreachable">{res.error}</EmptyState>
      ) : (
        <div className="space-y-4">
          <Panel
            title="Data sources"
            right={
              <span className="text-[11px] text-faint">
                {live ? "Live check" : "Configuration only"} ·{" "}
                {new Date(res.fetchedAt).toLocaleString()}
              </span>
            }
          >
            <table className="w-full text-left">
              <thead className="text-[10px] uppercase tracking-wider text-faint">
                <tr className="border-b border-border">
                  <th className="py-1.5 font-medium">Provider</th>
                  <th className="font-medium">Type</th>
                  <th className="font-medium">Status</th>
                  <th className="font-medium">Detail</th>
                  <th className="font-medium">Environment variables</th>
                </tr>
              </thead>
              <tbody>
                {res.data.providers.map((p) => (
                  <tr key={p.name} className="border-b border-border align-top last:border-0">
                    <td className="py-2.5 pr-3 font-medium">{p.display_name}</td>
                    <td className="py-2.5 pr-3 text-dim">{CATEGORY_LABEL[p.category]}</td>
                    <td className="py-2.5 pr-3">
                      <StateBadge state={p.state} />
                    </td>
                    <td className="max-w-md py-2.5 pr-3 text-dim">
                      {p.message}
                      {typeof p.details.last_successful_sync === "string" && (
                        <div className="mt-1 text-[11px] text-faint">
                          Last full sync: {new Date(p.details.last_successful_sync).toLocaleString()}
                        </div>
                      )}
                      {typeof p.details.shop_name === "string" && (
                        <div className="mt-1 text-[11px] text-text">
                          {p.details.shop_name} · {String(p.details.currency)} ·{" "}
                          {String(p.details.timezone)}
                        </div>
                      )}
                      <ScopeList label="Missing required scopes" items={p.details.missing_required_scopes} tone="text-neg" />
                      <ScopeList label="Missing optional scopes" items={p.details.missing_optional_scopes} tone="text-warn" />
                      <ScopeList label="Unneeded write scopes" items={p.details.unneeded_write_scopes} tone="text-warn" />
                      <ScopeList label="Autopilot needs (add to enable store changes)" items={p.details.autopilot_missing_scopes} tone="text-info" />
                    </td>
                    <td className="py-2.5">
                      <div className="flex flex-wrap gap-1">
                        {p.required_env.map((e) => (
                          <span key={e} className={p.missing_env.includes(e) ? "opacity-60" : ""}>
                            <Code>{e}</Code>
                          </span>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          {params.msg && (
            <div className="rounded-sm border border-border-strong bg-panel-2 px-3 py-2 text-[12px]">{params.msg}</div>
          )}
          <ShopifyDataPanel message={params.sync} />

          <Panel title="Store mode">
            <form action={setDigitalOnly} className="flex flex-wrap items-center gap-3 text-[12px]">
              <label className="flex items-center gap-2">
                <input type="checkbox" name="digital_only" defaultChecked={store.ok && store.data.digital_only} />
                This store sells only digital products
              </label>
              <button className="rounded-sm border border-border-strong px-2 py-1 text-dim hover:border-accent hover:text-accent">Save</button>
              <span className="text-[11px] text-faint">Shipping and packaging costs count as zero; stock rules don&apos;t apply.</span>
            </form>
          </Panel>

          <Panel title="Enable Autopilot store changes">
            <ol className="list-decimal space-y-1 pl-4 text-[12px] text-dim">
              <li>Dev Dashboard → <span className="text-text">app named from claude</span> → new version: add <Code>write_products</Code> <Code>write_discounts</Code> <Code>read_publications</Code> <Code>write_publications</Code>.</li>
              <li>Release the version and approve the new permissions in your Shopify admin.</li>
              <li>Run the live connection check above: &quot;Autopilot write scopes granted&quot; should appear.</li>
              <li>Install Shopify&apos;s free <span className="text-text">Digital Downloads</span> (or Digital Products) app to deliver files to buyers.</li>
            </ol>
          </Panel>

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title="Connect Shopify (read-only)">
              <ol className="list-decimal space-y-1.5 pl-4 text-dim">
                <li>
                  In the Shopify <span className="text-text">Dev Dashboard</span>, create an app
                  for your store.
                </li>
                <li>
                  Give its version only these scopes: <Code>read_products</Code>{" "}
                  <Code>read_inventory</Code> <Code>read_orders</Code> <Code>read_locations</Code>{" "}
                  and optionally <Code>read_reports</Code> <Code>read_all_orders</Code>.
                </li>
                <li>Release the version and install the app on your store (done: “app named from claude”).</li>
                <li>
                  Put <Code>SHOPIFY_STORE_DOMAIN</Code>, <Code>SHOPIFY_CLIENT_ID</Code> and{" "}
                  <Code>SHOPIFY_CLIENT_SECRET</Code> in <Code>backend/.env</Code>, restart the API,
                  then run a live check above.
                </li>
              </ol>
            </Panel>
            <Panel title="Safety guarantees">
              <ul className="list-disc space-y-1.5 pl-4 text-dim">
                <li>Analytics and sync use a read path that rejects every store change. Only Autopilot can change the store, through five pre-approved operations, within your limits, with every change logged.</li>
                <li>No brokerage or bank connections exist; the paper portfolio is simulated.</li>
                <li>Secrets live only in server environment variables and are redacted from logs.</li>
                <li>Unavailable data is shown as unavailable, never estimated silently.</li>
              </ul>
            </Panel>
          </div>
        </div>
      )}
    </>
  );
}
