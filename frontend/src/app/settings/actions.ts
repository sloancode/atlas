"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { apiPost } from "@/lib/api";

type Report = { ok: boolean; skipped_reason: string | null };

/** Triggers a read-only Shopify -> ATLAS sync. Never writes to Shopify. */
export async function syncShopifyNow() {
  const res = await apiPost<Report>("/api/shopify/sync");
  revalidatePath("/settings");
  const msg = !res.ok
    ? `Sync not started: ${res.error}`
    : res.data.skipped_reason ?? (res.data.ok ? "Sync completed." : "Sync finished with errors — see runs below.");
  redirect(`/settings?sync=${encodeURIComponent(msg)}`);
}
