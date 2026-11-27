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
  category: "broker" | "market_data" | "filings" | "ai";
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

export type DataStatusValue =
  | "live" | "delayed" | "historical" | "estimated" | "incomplete" | "missing" | "simulated";

export type VerifiedItem = {
  type: "fact" | "estimate" | "interpretation";
  text: string;
  citations: string[];
  verified: boolean;
  issues: string[];
  cited_values: Record<string, unknown>;
};


export const BACKEND_URL = BACKEND;

// ---------------------------------------------------------------- research
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

export const getSnapshot = (symbol: string) => apiGet<Snapshot>(`/api/markets/research/${encodeURIComponent(symbol)}`);
export const getResearchReports = (symbol: string) =>
  apiGet<{ id: number; generated_at: string; report: ResearchAI }[]>(`/api/markets/research/${encodeURIComponent(symbol)}/reports`);
export const getPresets = () =>
  apiGet<{ presets: Record<string, { label: string; description: string; rules: { metric: string; op: string; value: unknown }[] }>; metrics: Record<string, string> }>("/api/markets/scanner/presets");
export const getWatchlists = (withPrices = false) => apiGet<WatchlistT[]>(`/api/markets/watchlists${withPrices ? "?with_prices=true" : ""}`);

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

// ---------------------------------------------------------------- trading bot
export type BotPosition = {
  symbol: string; qty: string; avg_entry_price: string; current_price: string | null; market_value: string | null;
  unrealized_pl: string | null; unrealized_plpc: string | null; side: string;
};
export type BotOrder = {
  id: string; client_order_id: string | null; symbol: string; side: string; type: string; qty: string | null;
  filled_qty: string | null; status: string; stop_price: string | null; filled_avg_price: string | null;
  time_in_force: string | null; submitted_at: string | null; filled_at: string | null;
};
export type PlanAction = {
  action: "buy" | "short" | "sell" | "cover" | "stop" | "cancel" | "crypto_buy" | "crypto_sell" | "crypto_stop";
  symbol: string; reason: string; side?: string; qty?: number; type?: string; time_in_force?: string;
  order_class?: string; stop_price?: number; limit_price?: number; stop_loss_stop_price?: number;
  take_profit_limit_price?: number; order_id?: string; client_order_id?: string;
};
export type BotPlan = {
  actions: PlanAction[];
  skipped: { symbol: string; reason: string }[];
  summary: {
    now_et: string; equity: number; day_pnl_pct: number; drawdown_pct: number; gross_exposure_pct: number;
    positions: number; longs: number; shorts: number; entries_today: number; new_trades_blocked: string | null;
    candidates_scanned: number; signals: string[];
    crypto: { holdings: string[]; value: number; signals: string[]; blocked: string | null };
  };
};
export type BotRules = {
  risk_per_trade_pct: number; max_position_pct: number; max_gross_pct: number; max_positions: number;
  max_new_trades_per_day: number; daily_loss_cap_pct: number; drawdown_pause_pct: number;
  min_equity_for_day_trading: number; allow_short: boolean; min_price: number; min_avg_dollar_volume: number;
  min_news_score: number; news_pattern_points: number; momentum_pattern_points: number; gap_pct: number;
  rel_volume: number; breakout_days: number; atr_days: number; stop_atr_mult: number; min_stop_pct: number;
  max_stop_pct: number; target_r: number; fallback_stop_pct: number; max_hold_days: number;
  stale_min_gain_pct: number; cooldown_minutes: number; first_entry_et: string; last_entry_et: string;
  order_prefix: string; crypto_pairs: string[]; crypto_max_position_pct: number; crypto_max_total_pct: number;
  crypto_ema_fast: number; crypto_ema_slow: number; crypto_breakout_bars: number; crypto_max_24h_gain_pct: number;
  crypto_stop_atr_mult: number; crypto_min_stop_pct: number; crypto_max_stop_pct: number;
  crypto_cooldown_minutes: number; crypto_min_order_usd: number;
};
export type BotOverview =
  | { configured: false; message: string; rules: BotRules }
  | {
      configured: true; source: string; retrieved_at: string;
      account: { status: string; equity: string; cash: string; buying_power: string; last_equity: string; portfolio_value: string };
      clock: { is_open: boolean; next_open: string; next_close: string; timestamp?: string };
      positions: BotPosition[]; open_orders: BotOrder[]; recent_orders: BotOrder[];
      equity_history: { t: string; equity: number }[];
      plan: BotPlan | null; plan_error: string | null; plan_note: string; rules: BotRules;
    };
export type JournalEntry = BotPlan & { planned_at: string };

export async function getBotOverview(): Promise<ApiResult<BotOverview>> {
  const fetchedAt = new Date().toISOString();
  try {
    const res = await fetch(`${BACKEND}/api/bot/overview`, { cache: "no-store" });
    const body = await res.json().catch(() => null);
    if (!res.ok) return { ok: false, error: typeof body?.detail === "string" ? body.detail : `HTTP ${res.status}`, fetchedAt };
    return { ok: true, data: body as BotOverview, fetchedAt };
  } catch {
    return { ok: false, error: "ATLAS backend is unreachable", fetchedAt };
  }
}
export const getBotJournal = (limit = 50) => apiGet<JournalEntry[]>(`/api/bot/journal?limit=${limit}`);
