export function money(v: number | null | undefined, currency: string | null = "USD"): string | null {
  if (v === null || v === undefined) return null;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: currency || "USD",
    maximumFractionDigits: Math.abs(v) >= 10000 ? 0 : 2,
  }).format(v);
}

export function num(v: number | null | undefined, digits = 0): string | null {
  if (v === null || v === undefined) return null;
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(v);
}

export function pct(v: number | null | undefined, signed = false): string | null {
  if (v === null || v === undefined) return null;
  const s = `${Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(1)}%`;
  return signed && v > 0 ? `+${s}` : s;
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00` : iso);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
}

export function formatKpi(kind: string, v: number | null, currency: string | null): string | null {
  if (kind === "money") return money(v, currency);
  if (kind === "percent") return pct(v);
  return num(v);
}
