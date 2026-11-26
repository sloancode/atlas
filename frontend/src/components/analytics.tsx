import { pct } from "@/lib/format";

export function Change({ value }: { value: number | null }) {
  if (value === null) return <span className="text-faint">n/a</span>;
  const cls = value > 0 ? "text-pos" : value < 0 ? "text-neg" : "text-dim";
  const arrow = value > 0 ? "▲" : value < 0 ? "▼" : "■";
  return (
    <span className={`num ${cls}`}>
      {arrow} {pct(value, true)}
    </span>
  );
}
