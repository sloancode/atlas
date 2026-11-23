import { getSystemStatus, type ProviderStatus } from "@/lib/api";
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
  searchParams: Promise<{ live?: string; sync?: string }>;
}) {
  const params = await searchParams;
  const live = params.live === "1";
  const res = await getSystemStatus(live);

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
                      {typeof p.details.shop_name === "string" && (
                        <div className="mt-1 text-[11px] text-text">
                          {p.details.shop_name} · {String(p.details.currency)} ·{" "}
                          {String(p.details.timezone)}
                        </div>
                      )}
                      <ScopeList label="Missing required scopes" items={p.details.missing_required_scopes} tone="text-neg" />
                      <ScopeList label="Missing optional scopes" items={p.details.missing_optional_scopes} tone="text-warn" />
                      <ScopeList label="Unneeded write scopes" items={p.details.unneeded_write_scopes} tone="text-warn" />
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

          <ShopifyDataPanel message={params.sync} />

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
                <li>The Shopify client rejects every GraphQL mutation before it is sent.</li>
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
