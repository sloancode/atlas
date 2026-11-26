import { getSystemStatus, type ProviderStatus } from "@/lib/api";
import { Code, EmptyState, PageHeader, Panel, StateBadge } from "@/components/ui";

const CATEGORY_LABEL: Record<ProviderStatus["category"], string> = {
  broker: "Broker",
  market_data: "Market data",
  filings: "Filings",
  ai: "AI",
};

export default async function SettingsPage({
  searchParams,
}: {
  searchParams: Promise<{ live?: string }>;
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

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title="Connect the Alpaca paper account">
              <ol className="list-decimal space-y-1.5 pl-4 text-dim">
                <li>alpaca.markets → switch to <span className="text-text">Paper Trading</span> → API Keys → Generate.</li>
                <li>
                  Put <Code>ALPACA_API_KEY_ID</Code> and <Code>ALPACA_API_SECRET_KEY</Code> in{" "}
                  <Code>backend/.env</Code> (never in a chat), restart ATLAS, then run a live check above.
                </li>
                <li>Optional: <Code>ALPACA_DATA_FEED</Code> is <Code>iex</Code> (free); use <Code>sip</Code> only with an Alpaca data plan.</li>
              </ol>
            </Panel>
            <Panel title="Safety guarantees">
              <ul className="list-disc space-y-1.5 pl-4 text-dim">
                <li>Paper trading only: ATLAS talks to Alpaca&apos;s paper host and refuses non-paper accounts. There is no live-trading code.</li>
                <li>This website never places, changes or cancels orders. The scheduled bot places exactly what the planner outputs, within fixed limits.</li>
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
