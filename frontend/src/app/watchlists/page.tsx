import Link from "next/link";
import { getWatchlists } from "@/lib/api";
import { fmtDate, num } from "@/lib/format";
import { addToWatchlist, createWatchlist, deleteWatchlist, removeFromWatchlist } from "@/app/markets-actions";
import { Change } from "@/components/analytics";
import { EmptyState, PageHeader, Panel } from "@/components/ui";

export default async function WatchlistsPage({ searchParams }: { searchParams: Promise<{ msg?: string }> }) {
  const params = await searchParams;
  const res = await getWatchlists(true);
  return (
    <>
      <PageHeader code="WCH" title="Watchlists" subtitle="Symbols you are researching, with the latest end-of-day close from your data provider." />
      {params.msg && <div className="mb-4 rounded-sm border border-border-strong bg-panel-2 px-3 py-2 text-[12px]">{params.msg}</div>}
      <form action={createWatchlist} className="mb-4 flex gap-2">
        <input name="name" required maxLength={60} placeholder="New watchlist name" aria-label="New watchlist name"
          className="w-64 rounded-sm border border-border-strong bg-panel px-2.5 py-1.5 text-[12px] placeholder:text-faint" />
        <button className="rounded-sm border border-accent px-3 py-1.5 text-[12px] text-accent hover:bg-accent-dim">Create</button>
      </form>
      {!res.ok ? <EmptyState title="Unavailable">{res.error}</EmptyState> : res.data.length === 0 ? (
        <EmptyState title="No watchlists yet">Create one above, then add tickers.</EmptyState>
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {res.data.map((w) => (
            <Panel key={w.id} title={w.name}
              right={<form action={deleteWatchlist}><input type="hidden" name="id" value={w.id} /><button className="text-[11px] text-faint hover:text-neg">Delete list</button></form>}>
              <form action={addToWatchlist} className="mb-3 flex gap-2">
                <input type="hidden" name="watchlist_id" value={w.id} />
                <input name="symbol" required placeholder="Ticker" aria-label={`Add ticker to ${w.name}`} className="num w-28 rounded-sm border border-border-strong bg-panel-2 px-2 py-1 text-[12px] uppercase placeholder:normal-case placeholder:text-faint" />
                <input name="note" placeholder="Note (optional)" aria-label="Note" className="flex-1 rounded-sm border border-border-strong bg-panel-2 px-2 py-1 text-[12px] placeholder:text-faint" />
                <button className="rounded-sm border border-border-strong px-2 py-1 text-[12px] text-dim hover:text-text">Add</button>
              </form>
              {w.items.length === 0 ? <div className="text-[12px] text-faint">Empty.</div> : (
                <table className="w-full text-left text-[12px]">
                  <thead className="text-[10px] uppercase tracking-wider text-faint"><tr className="border-b border-border"><th className="py-1">Symbol</th><th>Close</th><th>Change</th><th>As of</th><th>Note</th><th /></tr></thead>
                  <tbody>{w.items.map((i) => (
                    <tr key={i.id} className="border-b border-border last:border-0">
                      <td className="py-1.5"><Link href={`/research?symbol=${i.symbol}`} className="num font-medium hover:text-accent">{i.symbol}</Link></td>
                      <td className="num">{i.close === null || i.close === undefined ? <span className="text-faint" title={(i.notes ?? []).join(" ")}>unavailable</span> : num(i.close, 2)}</td>
                      <td className="text-[11px]">{i.close !== null && i.close !== undefined ? <Change value={i.change_pct ?? null} /> : "—"}</td>
                      <td className="text-[11px] text-faint">{i.as_of ? `${fmtDate(i.as_of)}${i.source ? ` · ${i.source}` : ""}` : "—"}</td>
                      <td className="max-w-[160px] truncate text-dim" title={i.note ?? ""}>{i.note ?? ""}</td>
                      <td className="text-right"><form action={removeFromWatchlist}><input type="hidden" name="watchlist_id" value={w.id} /><input type="hidden" name="item_id" value={i.id} />
                        <button className="text-[11px] text-faint hover:text-neg" aria-label={`Remove ${i.symbol}`}>✕</button></form></td>
                    </tr>
                  ))}</tbody>
                </table>
              )}
            </Panel>
          ))}
        </div>
      )}
    </>
  );
}
