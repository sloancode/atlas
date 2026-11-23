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

// ------------------------------------------------------------ phase 5 types
export type SourceStatus = { status: "historical" | "missing"; source: string | null; retrieved_at: string | null; cached: boolean; notes: string[] };

export type Technicals = {
  as_of: string | null; sessions: number; close: number | null; sma20: number | null; sma50: number | null;
  sma200: number | null; ema20: number | null; rsi14: number | null; macd: number | null; macd_signal: number | null;
  macd_hist: number | null; atr14: number | null; volatility_20d: number | null; volatility_60d: number | null;
  returns: Record<string, number | null>; relative_strength: Record<string, number | null>;
  high_52w: number | null; low_52w: number | null; pct_from_52w_high: number | null; avg_volume_20d: number | null;
  support_resistance: { support: { level: number; touches: number }[]; resistance: { level: number; touches: number }[]; method: string };
  trend: string; trend_reason: string;
};

export type FundamentalsData = {
  fiscal_year: number | null; period_end: string | null; revenue: number | null; net_income: number | null;
  revenue_growth_pct: number | null; earnings_growth_pct: number | null; eps_growth_pct: number | null;
  gross_margin_pct: number | null; operating_margin_pct: number | null; free_cash_flow: number | null;
  fcf_margin_pct: number | null; cash: number | null; total_debt: number | null; net_debt: number | null;
  debt_to_equity: number | null; market_cap: number | null; market_cap_source: string | null;
  pe: number | null; ps: number | null; p_fcf: number | null; fcf_yield_pct: number | null;
  history: { fiscal_year: number | null; period_end: string; revenue: number | null; net_income: number | null; eps_diluted: number | null; free_cash_flow: number | null }[];
  notes: string[];
};

export type Snapshot = {
  symbol: string; generated_at: string; is_etf: boolean;
  price: { close: number | null; as_of: string | null; note: string };
  profile: Record<string, string | number | boolean | null>;
  technicals: Technicals;
  fundamentals: FundamentalsData | null;
  earnings: { upcoming: { date: string; eps_estimate: number | null }[]; recent: { date: string; eps_actual: number | null; eps_estimate: number | null }[] };
  news: { published: string | null; title: string; publisher: string | null; url: string | null; summary: string | null }[];
  events_to_monitor: string[];
  chart: { dates: string[]; close: (number | null)[]; sma50: (number | null)[]; sma200: (number | null)[] };
  data_status: Record<string, SourceStatus>;
  disclaimer: string;
};

export type ResearchAI = {
  summary: string; sections: Record<string, VerifiedItem[]>; insufficient_data: boolean;
  verification: { verified: number; unverified: number }; model: string | null; generated_at: string; price_as_of: string | null;
};

export type ScanResult = {
  symbol: string; name: string | null; matched: boolean; passed: number; total: number;
  checks: { label: string; passed: boolean; actual: unknown; detail: string }[];
  close: number | null; price_as_of: string | null; missing_data: string[];
};

export type WatchItem = { id: number; symbol: string; note: string | null; close?: number | null; as_of?: string | null; change_pct?: number | null; source?: string | null; status?: string; notes?: string[] };
export type WatchlistT = { id: number; name: string; items: WatchItem[] };

export type PaperState = {
  label: string;
  account: { id: number; name: string; starting_cash: number; created_at: string };
  simulated: true; cash: number; market_value: number; equity: number | null; total_return_pct: number | null;
  realized_pl: number; missing_prices: string[];
  positions: { symbol: string; quantity: number; avg_cost: number; cost_basis: number; price: number | null; price_as_of: string | null; market_value: number | null; unrealized_pl: number | null; unrealized_pl_pct: number | null }[];
  equity_curve: { date: string; equity: number }[];
  trades: { id: number; symbol: string; side: "buy" | "sell"; quantity: number; price: number; price_source: string; executed_at: string; thesis: string | null; lesson: string | null }[];
};

export const getSnapshot = (symbol: string) => apiGet<Snapshot>(`/api/markets/research/${encodeURIComponent(symbol)}`);
export const getResearchReports = (symbol: string) =>
  apiGet<{ id: number; generated_at: string; report: ResearchAI }[]>(`/api/markets/research/${encodeURIComponent(symbol)}/reports`);
export const getPresets = () =>
  apiGet<{ presets: Record<string, { label: string; description: string; rules: { metric: string; op: string; value: unknown }[] }>; metrics: Record<string, string> }>("/api/markets/scanner/presets");
export const getWatchlists = (withPrices = false) => apiGet<WatchlistT[]>(`/api/markets/watchlists${withPrices ? "?with_prices=true" : ""}`);
export const getPaper = () => apiGet<PaperState>("/api/markets/paper");

export async function apiSend<T>(method: "POST" | "PATCH" | "DELETE", path: string, body?: unknown): Promise<ApiResult<T>> {
  const fetchedAt = new Date().toISOString();
  try {
    const res = await fetch(`${BACKEND}${path}`, {
      method, cache: "no-store",
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) {
      const d = data?.detail;
      return { ok: false, error: typeof d === "string" ? d : Array.isArray(d) ? d.map((x: { msg: string }) => x.msg).join("; ") : `HTTP ${res.status}`, fetchedAt };
    }
    return { ok: true, data: data as T, fetchedAt };
  } catch {
    return { ok: false, error: "ATLAS backend is unreachable", fetchedAt };
  }
}

// ------------------------------------------------------------ autopilot
export type AutopilotConfigT = {
  enabled: boolean; stopped: boolean; min_price: string; max_price: string; max_price_change_pct: number;
  max_discount_pct: number; max_discount_days: number; max_actions_per_day: number; max_new_products_per_day: number;
  allow_publish: boolean; daily_ai_budget_usd: string; max_steps_per_run: number; run_every_hours: number;
};
export type AgentRunT = { id: number; started_at: string; finished_at: string | null; trigger: string; status: string; summary: string | null; error: string | null; steps: number; est_cost_usd: number };
export type AgentActionT = { id: number; run_id: number | null; created_at: string; action: string; target: string | null; status: "executed" | "blocked" | "failed"; reason: string | null; detail: string | null; params: Record<string, unknown> | null; before: Record<string, unknown> | null; after: Record<string, unknown> | null };
export type AutopilotOverview = {
  config: AutopilotConfigT; active: boolean; ready: { shopify: boolean; claude: boolean };
  today: { actions: number; new_products: number; ai_spend_usd: number };
  needs_you: { product_id: string; title: string; created_at: string; has_file: boolean }[];
  products: { product_id: string; title: string; file_attached: boolean; published: boolean; created_at: string; concept: { subtitle?: string; sections?: string[] } | null }[];
  runs: AgentRunT[]; actions: AgentActionT[];
};
export type TrafficT = { status: "historical" | "missing"; as_of: string | null; sessions: number | null; cart_sessions: number | null; checkout_sessions: number | null; completed_sessions: number | null; conversion_rate_pct: number | null; sources: { source: string; sessions: number | null; conversion_rate_pct: number | null }[]; notes: string[] };

export const getAutopilot = () => apiGet<AutopilotOverview>("/api/autopilot");
export const getTraffic = (p: PeriodParams) => apiGet<TrafficT>(`/api/analytics/traffic?${periodQuery(p)}`);
export const getStoreSettings = () => apiGet<{ digital_only: boolean }>("/api/settings/store");
