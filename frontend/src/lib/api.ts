// Typed access to the ATLAS backend. Requests run server-side and are proxied
// via Next rewrites (/api -> FastAPI), so no secrets ever reach the browser.

export type ConnectionState =
  | "not_configured"
  | "configured"
  | "connected"
  | "error"
  | "planned";

export type ProviderStatus = {
  name: string;
  display_name: string;
  category: "commerce" | "market_data" | "filings" | "ai";
  state: ConnectionState;
  message: string;
  required_env: string[];
  missing_env: string[];
  details: Record<string, unknown>;
  checked_at: string;
};

export type SystemStatus = {
  environment: string;
  database: { ok: boolean; message: string };
  providers: ProviderStatus[];
  read_only: boolean;
};

const BACKEND = process.env.ATLAS_API_URL ?? "http://127.0.0.1:8000";

export type ApiResult<T> =
  | { ok: true; data: T; fetchedAt: string }
  | { ok: false; error: string; fetchedAt: string };

export async function apiGet<T>(path: string): Promise<ApiResult<T>> {
  const fetchedAt = new Date().toISOString();
  try {
    const res = await fetch(`${BACKEND}${path}`, { cache: "no-store" });
    if (!res.ok) return { ok: false, error: `Backend returned HTTP ${res.status}`, fetchedAt };
    return { ok: true, data: (await res.json()) as T, fetchedAt };
  } catch {
    return { ok: false, error: "ATLAS backend is unreachable", fetchedAt };
  }
}

export const getSystemStatus = (live = false) =>
  apiGet<SystemStatus>(`/api/system/status${live ? "?live=true" : ""}`);

export type DataSummary = {
  counts: Record<string, number>;
  orders_first_created_at: string | null;
  orders_last_created_at: string | null;
  last_successful_sync: Record<string, string | null>;
  notes: string[];
};

export type SyncRun = {
  id: number;
  resource: string;
  status: "running" | "succeeded" | "failed";
  started_at: string;
  finished_at: string | null;
  records: number;
  error: string | null;
};

export const getShopifyDataSummary = () => apiGet<DataSummary>("/api/shopify/data-summary");
export const getShopifySyncRuns = (limit = 8) =>
  apiGet<SyncRun[]>(`/api/shopify/sync/runs?limit=${limit}`);

export async function apiPost<T>(path: string): Promise<ApiResult<T>> {
  const fetchedAt = new Date().toISOString();
  try {
    const res = await fetch(`${BACKEND}${path}`, { method: "POST", cache: "no-store" });
    const body = await res.json().catch(() => null);
    if (!res.ok) {
      const detail = body && typeof body.detail === "string" ? body.detail : `HTTP ${res.status}`;
      return { ok: false, error: detail, fetchedAt };
    }
    return { ok: true, data: body as T, fetchedAt };
  } catch {
    return { ok: false, error: "ATLAS backend is unreachable", fetchedAt };
  }
}
