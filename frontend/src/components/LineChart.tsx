"use client";

import { useMemo, useState } from "react";

export type Series = { key: string; label: string; color: string; dash?: string; values: (number | null)[] };

const H = 240;
const PAD = { top: 10, right: 12, bottom: 22, left: 56 };

/**
 * Multi-series line chart with legend, crosshair and tooltip.
 * One y-axis only. Identity is never color-alone: series differ by dash style
 * too, and the legend names each one.
 */
export function LineChart({
  dates, series, format, label,
}: { dates: string[]; series: Series[]; format: (v: number) => string; label: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const [width, setWidth] = useState(800);

  const { min, max, ticks } = useMemo(() => {
    const vals = series.flatMap((s) => s.values.filter((v): v is number => v !== null));
    if (!vals.length) return { min: 0, max: 1, ticks: [0, 1] };
    let lo = Math.min(...vals), hi = Math.max(...vals);
    const padv = (hi - lo) * 0.05 || Math.abs(hi) * 0.05 || 1;
    lo -= padv; hi += padv;
    const step = (hi - lo) / 4;
    return { min: lo, max: hi, ticks: [0, 1, 2, 3, 4].map((i) => lo + step * i) };
  }, [series]);

  const innerW = Math.max(width - PAD.left - PAD.right, 50);
  const innerH = H - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (dates.length <= 1 ? 0 : (i / (dates.length - 1)) * innerW);
  const y = (v: number) => PAD.top + ((max - v) / (max - min)) * innerH;
  const path = (vals: (number | null)[]) => {
    let d = "", pen = false;
    vals.forEach((v, i) => {
      if (v === null) { pen = false; return; }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
      pen = true;
    });
    return d;
  };
  const labelEvery = Math.ceil(dates.length / 7);

  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-4 text-[11px] text-dim" aria-label="Legend">
        {series.map((s) => (
          <span key={s.key} className="flex items-center gap-1.5">
            <svg width="22" height="6" aria-hidden><line x1="0" y1="3" x2="22" y2="3" stroke={s.color} strokeWidth="2" strokeDasharray={s.dash} /></svg>
            {s.label}
          </span>
        ))}
      </div>
      <div className="relative w-full" ref={(el) => { if (el && Math.abs(el.clientWidth - width) > 4) setWidth(el.clientWidth); }}>
        <svg width={width} height={H} role="img" aria-label={label}
          onMouseMove={(e) => {
            const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
            const i = Math.round(((e.clientX - r.left - PAD.left) / innerW) * (dates.length - 1));
            setHover(i >= 0 && i < dates.length ? i : null);
          }}
          onMouseLeave={() => setHover(null)}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={PAD.left} x2={width - PAD.right} y1={y(t)} y2={y(t)} stroke="var(--viz-grid)" />
              <text x={PAD.left - 6} y={y(t) + 3} textAnchor="end" fontSize={10} fill="var(--text-faint)" className="num">{format(t)}</text>
            </g>
          ))}
          {dates.map((d, i) => i % labelEvery === 0 && (
            <text key={d} x={x(i)} y={H - 6} textAnchor="middle" fontSize={10} fill="var(--text-faint)" className="num">{d.slice(2, 7)}</text>
          ))}
          {series.map((s) => (
            <path key={s.key} d={path(s.values)} fill="none" stroke={s.color} strokeWidth={2} strokeDasharray={s.dash} strokeLinejoin="round" />
          ))}
          {hover !== null && (
            <g>
              <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + innerH} stroke="var(--border-strong)" />
              {series.map((s) => s.values[hover] !== null && (
                <circle key={s.key} cx={x(hover)} cy={y(s.values[hover] as number)} r={4} fill={s.color} stroke="var(--panel)" strokeWidth={2} />
              ))}
            </g>
          )}
        </svg>
        {hover !== null && (
          <div className="pointer-events-none absolute z-10 rounded-sm border border-border-strong bg-panel-2 px-2 py-1 text-[11px] shadow-lg"
            style={{ left: Math.min(x(hover) + 10, width - 170), top: 6 }}>
            <div className="num text-faint">{dates[hover]}</div>
            {series.map((s) => (
              <div key={s.key} className="flex justify-between gap-3">
                <span className="text-dim">{s.label}</span>
                <span className="num text-text">{s.values[hover] === null ? "—" : format(s.values[hover] as number)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
