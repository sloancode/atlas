"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { apiSend, type ScanResult } from "@/lib/api";

/* Market research actions. Paper trades are SIMULATED; nothing reaches a brokerage. */

const sym = (v: FormDataEntryValue | null) => String(v ?? "").trim().toUpperCase();
const go = (path: string, msg?: string): never => {
  revalidatePath(path.split("?")[0]);
  redirect(msg ? `${path}${path.includes("?") ? "&" : "?"}msg=${encodeURIComponent(msg)}` : path);
};

export async function createWatchlist(form: FormData) {
  const r = await apiSend("POST", "/api/markets/watchlists", { name: String(form.get("name") ?? "").trim() });
  go("/watchlists", r.ok ? "Watchlist created." : r.error);
}

export async function deleteWatchlist(form: FormData) {
  const r = await apiSend("DELETE", `/api/markets/watchlists/${Number(form.get("id"))}`);
  go("/watchlists", r.ok ? "Watchlist deleted." : r.error);
}

export async function addToWatchlist(form: FormData) {
  const back = String(form.get("return_to") || "/watchlists");
  const r = await apiSend("POST", `/api/markets/watchlists/${Number(form.get("watchlist_id"))}/items`, {
    symbol: sym(form.get("symbol")), note: String(form.get("note") ?? "").trim() || null,
  });
  go(back, r.ok ? `${sym(form.get("symbol"))} added.` : r.error);
}

export async function removeFromWatchlist(form: FormData) {
  const r = await apiSend("DELETE", `/api/markets/watchlists/${Number(form.get("watchlist_id"))}/items/${Number(form.get("item_id"))}`);
  go("/watchlists", r.ok ? "Removed." : r.error);
}

export async function generateResearchAI(form: FormData) {
  const s = sym(form.get("symbol"));
  const r = await apiSend("POST", `/api/markets/research/${encodeURIComponent(s)}/ai`);
  go(`/research?symbol=${encodeURIComponent(s)}`, r.ok ? "AI research note generated." : r.error);
}

export async function paperTrade(form: FormData) {
  const r = await apiSend<{ symbol: string; side: string; quantity: number; price: number; price_source: string }>(
    "POST", "/api/markets/paper/trades", {
      symbol: sym(form.get("symbol")), side: form.get("side") === "sell" ? "sell" : "buy",
      quantity: String(form.get("quantity") ?? "").trim(), thesis: String(form.get("thesis") ?? "").trim() || null,
    });
  go("/portfolio", r.ok
    ? `SIMULATED ${r.data.side} ${r.data.quantity} ${r.data.symbol} @ ${r.data.price} (${r.data.price_source}).`
    : `Not filled: ${r.error}`);
}

export async function paperReset(form: FormData) {
  const r = await apiSend("POST", "/api/markets/paper/reset", { starting_cash: String(form.get("starting_cash") ?? "").trim() });
  go("/portfolio", r.ok ? "Simulated portfolio reset." : r.error);
}

export async function paperJournal(form: FormData) {
  const r = await apiSend("PATCH", `/api/markets/paper/trades/${Number(form.get("id"))}`, {
    lesson: String(form.get("lesson") ?? ""),
  });
  go("/portfolio", r.ok ? "Journal saved." : r.error);
}

export type ScanState = { results: ScanResult[] | null; rules: { metric: string; op: string; value: unknown }[]; error: string | null; note?: string };

export async function runScan(_prev: ScanState, form: FormData): Promise<ScanState> {
  const preset = String(form.get("preset") ?? "");
  const wl = String(form.get("watchlist_id") ?? "");
  const symbols = String(form.get("symbols") ?? "").split(/[\s,]+/).map((x) => x.trim().toUpperCase()).filter(Boolean);
  const r = await apiSend<{ results: ScanResult[]; rules: ScanState["rules"]; note: string }>("POST", "/api/markets/scanner/run", {
    preset, symbols: symbols.length ? symbols : null, watchlist_id: wl ? Number(wl) : null,
  });
  return r.ok ? { results: r.data.results, rules: r.data.rules, error: null, note: r.data.note } : { results: null, rules: [], error: r.error };
}
