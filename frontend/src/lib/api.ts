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

// ---------------------------------------------------------------- analytics
export type DataStatusValue =
  | "live" | "delayed" | "historical" | "estimated" | "incomplete" | "missing" | "simulated";

export type Period = { start: string; end: string };

export type Meta = {
  source: string;
  status: DataStatusValue;
  as_of: string | null;
  period: Period | null;
  previous_period: Period | null;
  currency: string | null;
  timezone: string;
  notes: string[];
};

export type Kpi = {
  key: string;
  label: string;
  definition: string;
  kind: "money" | "count" | "percent";
  current: number | null;
  previous: number | null;
  change_pct: number | null;
};

export type DailyPoint = { date: string; gross_sales: number; net_sales: number; orders: number };
export type Overview = { meta: Meta; kpis: Kpi[]; daily: DailyPoint[]; has_sales: boolean };

export type Flag = { key: string; label: string; reason: string };

export type ProductRow = {
  product_gid: string;
  title: string;
  status: string | null;
  image_url: string | null;
  skus: string[];
  price_min: number | null;
  price_max: number | null;
  units_sold: number;
  units_returned: number;
  gross_sales: number;
  net_sales: number;
  orders: number;
  order_frequency_per_week: number;
  prev_net_sales: number;
  growth_pct: number | null;
  rank: number | null;
  available: number | null;
  velocity_per_day: number;
  days_of_cover: number | null;
  momentum_pct: number | null;
  flags: Flag[];
  in_catalog: boolean;
  opportunity: Opportunity | null;
};

export type ProductsResponse = { meta: Meta; products: ProductRow[]; seasonality: string };

export type VariantInventory = {
  variant_gid: string;
  product_gid: string;
  product_title: string;
  variant_title: string;
  sku: string | null;
  price: number;
  tracked: boolean;
  available: number | null;
  net_units_30d: number;
  velocity_per_day: number;
  days_of_cover: number | null;
  status: string;
  reasons: string[];
  thresholds: Record<string, number>;
};

export type InventoryResponse = {
  meta: Meta;
  thresholds: Record<string, number>;
  variants: VariantInventory[];
  summary: Record<string, number>;
};

export type ProductDetail = {
  meta: Meta;
  product: ProductRow;
  variants: VariantInventory[];
  daily: { date: string; units: number; sales_after_discounts: number }[];
};

export type Metric = {
  key: string;
  label: string;
  kind: "money" | "percent";
  value: number | null;
  status: DataStatusValue;
  formula: string;
  notes: string[];
};

export type ProductProfit = {
  product_gid: string;
  title: string;
  net_units: number;
  net_sales: number;
  cogs: number | null;
  gross_profit: number | null;
  gross_margin_pct: number | null;
  status: DataStatusValue;
  cost_source: string;
};

export type ProfitabilityResponse = {
  meta: Meta;
  metrics: Metric[];
  products: ProductProfit[];
  missing_inputs: string[];
  cogs_coverage_pct: number | null;
};

export type StoreCosts = Record<
  | "shipping_cost_per_order" | "packaging_cost_per_order" | "transaction_fee_percent"
  | "transaction_fee_per_order" | "advertising_per_month" | "other_opex_per_month",
  string | null
>;

export type VariantCost = {
  variant_gid: string;
  product_title: string;
  variant_title: string;
  sku: string | null;
  price: number;
  user_cogs: number | null;
  shopify_unit_cost: number | null;
  effective_cost: number | null;
  source: string;
};

export type CostsResponse = { currency: string | null; store: StoreCosts; variants: VariantCost[] };
export type AlertRule = {
  min_units: number | null;
  min_days_of_cover: number | null;
  max_days_of_cover: number | null;
};

export type PeriodParams = { period?: string; start?: string; end?: string };

export function periodQuery(p: PeriodParams): string {
  const q = new URLSearchParams();
  q.set("period", p.period ?? "30d");
  if (p.period === "custom") {
    if (p.start) q.set("start", p.start);
    if (p.end) q.set("end", p.end);
  }
  return q.toString();
}

export const getOverview = (p: PeriodParams) => apiGet<Overview>(`/api/analytics/overview?${periodQuery(p)}`);
export const getProducts = (p: PeriodParams) =>
  apiGet<ProductsResponse>(`/api/analytics/products?${periodQuery(p)}`);
export const getProductDetail = (id: string, p: PeriodParams) =>
  apiGet<ProductDetail>(`/api/analytics/products/${encodeURIComponent(id)}?${periodQuery(p)}`);
export const getInventory = () => apiGet<InventoryResponse>("/api/analytics/inventory");
export const getAlertRule = () => apiGet<AlertRule>("/api/analytics/inventory/rule");
export const getProfitability = (p: PeriodParams) =>
  apiGet<ProfitabilityResponse>(`/api/analytics/profitability?${periodQuery(p)}`);
export const getCosts = () => apiGet<CostsResponse>("/api/costs");

export async function apiPut<T>(path: string, body: unknown): Promise<ApiResult<T>> {
  const fetchedAt = new Date().toISOString();
  try {
    const res = await fetch(`${BACKEND}${path}`, {
      method: "PUT",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) {
      const d = data?.detail;
      const msg = typeof d === "string" ? d : Array.isArray(d) ? d.map((x) => x.msg).join("; ") : `HTTP ${res.status}`;
      return { ok: false, error: msg, fetchedAt };
    }
    return { ok: true, data: data as T, fetchedAt };
  } catch {
    return { ok: false, error: "ATLAS backend is unreachable", fetchedAt };
  }
}

/** Numeric Shopify id from a gid, for URLs. Returns null for non-catalog keys. */
export function productIdFromGid(gid: string): string | null {
  const m = gid.match(/^gid:\/\/shopify\/Product\/(\d+)$/);
  return m ? m[1] : null;
}

// ------------------------------------------------------------ phase 4 types
export type ScoreComponent = { name: string; points: number; max_points: number; reason: string };
export type Opportunity = {
  score: number;
  confidence: "high" | "medium" | "low";
  components: ScoreComponent[];
  summary: string;
  disclaimer: string;
};

export type ReportSummary = {
  id: number;
  kind: "daily" | "weekly";
  period_start: string;
  period_end: string;
  generated_at: string;
  narrative_status: "not_requested" | "generated" | "failed" | "not_configured";
  alerts: number;
  investigate: number;
};

export type NarrativeItem = { type: string; text: string; citations: string[]; verified: boolean; issues: string[] };
export type Narrative = { summary?: string; sections?: NarrativeItem[]; model?: string; unverified?: number; error?: string };

export type ReportFacts = {
  kind: "daily" | "weekly";
  shop: string | null;
  currency: string;
  timezone: string;
  period: Period;
  previous_period: Period;
  data_status: DataStatusValue;
  as_of: string | null;
  notes: string[];
  sections: {
    revenue: Kpi[];
    best_products: { title: string; net_sales: number; units: number; growth_pct: number | null }[];
    weakest_products: { title: string; net_sales: number; units: number; growth_pct: number | null; available: number | null }[];
    inventory_alerts: { title: string; status: string; available: number | null; days_of_cover: number | null; reason: string }[];
    profitability: {
      metrics: { key: string; label: string; kind: string; value: number | null; status: DataStatusValue }[];
      missing_inputs: string[];
      cogs_coverage_pct: number | null;
    };
    changes: { text: string; evidence: string }[];
    investigate: { title: string; why: string; evidence: string }[];
    daily_trend?: DailyPoint[];
    movers?: { title: string; flag: string; reason: string }[];
  };
};

export type ReportFull = ReportSummary & { facts: ReportFacts; narrative: Narrative | null };

export type VerifiedItem = {
  type: "fact" | "estimate" | "interpretation";
  text: string;
  citations: string[];
  verified: boolean;
  issues: string[];
  cited_values: Record<string, unknown>;
};

export type AnalystAnswer = {
  question: string;
  summary: string;
  items: VerifiedItem[];
  insufficient_data: boolean;
  follow_up_questions: string[];
  verification: Record<string, number>;
  model: string | null;
  data_as_of: string | null;
  generated_at: string;
  disclaimer: string;
};

export const getReports = () => apiGet<ReportSummary[]>("/api/reports?limit=60");
export const getReport = (id: string) => apiGet<ReportFull>(`/api/reports/${encodeURIComponent(id)}`);
export const getAnalystStatus = () => apiGet<{ configured: boolean; model: string }>("/api/analyst/status");

export async function apiPostJson<T>(path: string, body: unknown): Promise<ApiResult<T>> {
  const fetchedAt = new Date().toISOString();
  try {
    const res = await fetch(`${BACKEND}${path}`, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) {
      const d = data?.detail;
      return { ok: false, error: typeof d === "string" ? d : `HTTP ${res.status}`, fetchedAt };
    }
    return { ok: true, data: data as T, fetchedAt };
  } catch {
    return { ok: false, error: "ATLAS backend is unreachable", fetchedAt };
  }
}

export const BACKEND_URL = BACKEND;
