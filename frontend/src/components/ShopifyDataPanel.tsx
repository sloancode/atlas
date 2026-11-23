import { getShopifyDataSummary, getShopifySyncRuns } from "@/lib/api";
import { syncShopifyNow } from "@/app/settings/actions";
import { EmptyState, Panel } from "./ui";

const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "—");
const STATUS_CLS = { succeeded: "text-pos", failed: "text-neg", running: "text-info" } as const;

export async function ShopifyDataPanel({ message }: { message?: string }) {
  const [summary, runs] = await Promise.all([getShopifyDataSummary(), getShopifySyncRuns()]);
  return (
    <Panel
      title="Shopify data in ATLAS"
      right={
        <form action={syncShopifyNow}>
          <button
            type="submit"
            className="rounded-sm border border-border-strong px-2.5 py-1 text-[11px] text-dim hover:border-accent hover:text-accent"
          >
            Sync now (read-only)
          </button>
        </form>
      }
    >
      {message && (
        <div className="mb-3 rounded-sm border border-border-strong bg-panel-2 px-3 py-2 text-[12px]">
          {message}
        </div>
      )}
      {!summary.ok ? (
        <EmptyState title="Unavailable">{summary.error}</EmptyState>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <div>
            <dl className="grid grid-cols-3 gap-2">
              {Object.entries(summary.data.counts).map(([k, v]) => (
                <div key={k} className="rounded-sm border border-border px-2 py-1.5">
                  <dt className="text-[10px] uppercase tracking-wider text-faint">{k.replace("_", " ")}</dt>
                  <dd className="num mt-0.5 text-[16px]">{v}</dd>
                </div>
              ))}
            </dl>
            <ul className="mt-3 space-y-1 text-[11px] text-faint">
              {summary.data.notes.map((n) => (
                <li key={n}>· {n}</li>
              ))}
            </ul>
          </div>
          <div>
            <div className="mb-1 text-[10px] uppercase tracking-wider text-faint">Recent sync runs</div>
            {runs.ok && runs.data.length > 0 ? (
              <table className="w-full text-left text-[12px]">
                <tbody>
                  {runs.data.map((r) => (
                    <tr key={r.id} className="border-b border-border align-top last:border-0">
                      <td className="py-1 pr-2 text-dim">{r.resource}</td>
                      <td className={`py-1 pr-2 ${STATUS_CLS[r.status]}`}>{r.status}</td>
                      <td className="num py-1 pr-2">{r.records}</td>
                      <td className="py-1 text-faint">
                        {fmt(r.finished_at ?? r.started_at)}
                        {r.error && <div className="text-neg">{r.error}</div>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="text-[12px] text-faint">No sync has run yet.</div>
            )}
          </div>
        </div>
      )}
    </Panel>
  );
}
