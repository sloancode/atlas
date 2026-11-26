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
