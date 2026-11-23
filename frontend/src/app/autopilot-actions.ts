"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { apiPut, apiSend, type AgentRunT } from "@/lib/api";

/* Owner controls for Shopify Autopilot. */

const back = (msg: string, path = "/autopilot"): never => {
  revalidatePath(path);
  redirect(`${path}?msg=${encodeURIComponent(msg)}`);
};

export async function autopilotStop() {
  const r = await apiSend("POST", "/api/autopilot/stop");
  back(r.ok ? "Autopilot STOPPED. It will not change your store until you resume." : r.error);
}

export async function autopilotResume() {
  const r = await apiSend("POST", "/api/autopilot/resume");
  back(r.ok ? "Autopilot resumed." : r.error);
}

export async function autopilotSave(form: FormData) {
  const num = (k: string) => Number(String(form.get(k) ?? "").trim());
  const str = (k: string) => String(form.get(k) ?? "").trim();
  const r = await apiPut("/api/autopilot/config", {
    enabled: form.get("enabled") === "on", allow_publish: form.get("allow_publish") === "on",
    min_price: str("min_price"), max_price: str("max_price"), max_price_change_pct: num("max_price_change_pct"),
    max_discount_pct: num("max_discount_pct"), max_discount_days: num("max_discount_days"),
    max_actions_per_day: num("max_actions_per_day"), max_new_products_per_day: num("max_new_products_per_day"),
    daily_ai_budget_usd: str("daily_ai_budget_usd"), max_steps_per_run: num("max_steps_per_run"),
    run_every_hours: num("run_every_hours"),
  });
  back(r.ok ? "Autopilot settings saved." : `Not saved: ${r.error}`);
}

export async function autopilotRun() {
  const r = await apiSend<AgentRunT>("POST", "/api/autopilot/run");
  back(r.ok ? `Run ${r.data.status}: ${r.data.summary ?? r.data.error ?? ""}`.slice(0, 400) : `Run not started: ${r.error}`);
}

export async function autopilotFileAttached(form: FormData) {
  const id = String(form.get("product_id") ?? "");
  const r = await apiSend("POST", `/api/autopilot/products/${encodeURIComponent(id)}/file-attached`);
  back(r.ok ? "Thanks — the agent can publish this product on its next run." : r.error);
}

export async function setDigitalOnly(form: FormData) {
  const r = await apiPut("/api/settings/store", { digital_only: form.get("digital_only") === "on" });
  back(r.ok ? "Store mode saved." : r.error, "/settings");
}
