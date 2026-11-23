"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { apiPostJson, apiPut, type AnalystAnswer, type ReportFull } from "@/lib/api";

/*
 * Server actions for user inputs stored in ATLAS's own database.
 * None of these write to Shopify.
 */

const STORE_FIELDS = [
  "shipping_cost_per_order",
  "packaging_cost_per_order",
  "transaction_fee_percent",
  "transaction_fee_per_order",
  "advertising_per_month",
  "other_opex_per_month",
] as const;

function amount(v: FormDataEntryValue | null): string | null {
  const s = (typeof v === "string" ? v : "").trim().replace(/[$,\s]/g, "");
  return s === "" ? null : s; // blank = unknown, never zero
}

function back(path: string, msg: string): never {
  revalidatePath(path);
  redirect(`${path}${path.includes("?") ? "&" : "?"}msg=${encodeURIComponent(msg)}`);
}

export async function saveStoreCosts(form: FormData) {
  const body = Object.fromEntries(STORE_FIELDS.map((f) => [f, amount(form.get(f))]));
  const res = await apiPut("/api/costs/store", body);
  back(String(form.get("return_to") || "/profitability"), res.ok ? "Store costs saved." : `Not saved: ${res.error}`);
}

export async function saveVariantCosts(form: FormData) {
  const rows = [...form.keys()]
    .filter((k) => k.startsWith("cogs:"))
    .map((k) => ({ variant_gid: k.slice(5), cogs: amount(form.get(k)) }));
  const res = await apiPut("/api/costs/variants", rows);
  back(String(form.get("return_to") || "/profitability"), res.ok ? "Product costs saved." : `Not saved: ${res.error}`);
}

export async function saveAlertRule(form: FormData) {
  const int = (k: string) => {
    const v = amount(form.get(k));
    return v === null ? null : Number.parseInt(v, 10);
  };
  const res = await apiPut("/api/analytics/inventory/rule", {
    min_units: int("min_units"),
    min_days_of_cover: int("min_days_of_cover"),
    max_days_of_cover: int("max_days_of_cover"),
  });
  back("/inventory", res.ok ? "Alert thresholds saved." : `Not saved: ${res.error}`);
}


export async function generateReport(form: FormData) {
  const kind = form.get("kind") === "weekly" ? "weekly" : "daily";
  const res = await apiPostJson<ReportFull>("/api/reports/generate", { kind, with_ai: false });
  revalidatePath("/reports");
  if (!res.ok) redirect(`/reports?msg=${encodeURIComponent(`Report not generated: ${res.error}`)}`);
  redirect(`/reports?id=${res.data.id}`);
}

export async function regenerateNarrative(form: FormData) {
  const id = String(form.get("id") ?? "");
  const res = await apiPostJson<ReportFull>(`/api/reports/${encodeURIComponent(id)}/narrative`, {});
  revalidatePath("/reports");
  redirect(`/reports?id=${id}${res.ok ? "" : `&msg=${encodeURIComponent(res.error)}`}`);
}

export type AskState = { question: string; answer: AnalystAnswer | null; error: string | null };

export async function askAnalyst(_prev: AskState, form: FormData): Promise<AskState> {
  const question = String(form.get("question") ?? "").trim();
  if (!question) return { question, answer: null, error: "Type a question first." };
  const res = await apiPostJson<AnalystAnswer>("/api/analyst/ask", { question });
  return res.ok ? { question, answer: res.data, error: null } : { question, answer: null, error: res.error };
}
