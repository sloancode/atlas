"use client";

import { useMemo, useState } from "react";

export type BarDatum = { date: string; value: number; detail?: string };

const H = 200;
const PAD = { top: 12, right: 8, bottom: 22, left: 56 };

function niceStep(range: number): number {
  const raw = range / 4;
  const mag = Math.pow(10, Math.floor(Math.log10(raw || 1)));
  const n = raw / mag;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * mag;
}

/**
 * Single-series daily bar chart (no legend: the panel title names the series).
 * Positive bars use --viz-pos, negative (refund-heavy) days --viz-neg, both
 * validated for the dark surface. Bars are anchored to the zero baseline with
 * rounded data-ends; hover anywhere in a day's column shows a tooltip.
 */
export function DailyBarChart({
  data,
  format,
  label,
}: {
  data: BarDatum[];
  format: (v: number) => string;
  label: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const [width, setWidth] = useState(720);

  const { min, max, ticks } = useMemo(() => {
    const vals = data.map((d) => d.value);
    let lo = Math.min(0, ...vals);
    let hi = Math.max(0, ...vals);
    if (lo === hi) hi = 1;
    const step = niceStep(hi - lo);
    lo = Math.floor(lo / step) * step;
    hi = Math.ceil(hi / step) * step;
    const t: number[] = [];
    for (let v = lo; v <= hi + step / 2; v += step) t.push(Math.round(v * 100) / 100);
    return { min: lo, max: hi, ticks: t };
  }, [data]);

  const innerW = Math.max(width - PAD.left - PAD.right, 50);
  const innerH = H - PAD.top - PAD.bottom;
  const y = (v: number) => PAD.top + ((max - v) / (max - min)) * innerH;
  const band = innerW / Math.max(data.length, 1);
  const barW = Math.max(Math.min(band - 2, 28), 1); // >= 2px surface gap between bars
  const labelEvery = Math.ceil(data.length / 8);
  const zero = y(0);

  return (
    <div
      className="relative w-full"
      ref={(el) => {
        if (el && Math.abs(el.clientWidth - width) > 4) setWidth(el.clientWidth);
      }}
    >
      <svg width={width} height={H} role="img" aria-label={label} onMouseLeave={() => setHover(null)}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={width - PAD.right} y1={y(t)} y2={y(t)} stroke="var(--viz-grid)" strokeWidth={1} />
            <text x={PAD.left - 6} y={y(t) + 3} textAnchor="end" className="num" fontSize={10} fill="var(--text-faint)">
              {format(t)}
            </text>
          </g>
        ))}
        {data.map((d, i) => {
          const x = PAD.left + i * band + (band - barW) / 2;
          const top = Math.min(y(d.value), zero);
          const h = Math.abs(y(d.value) - zero);
          const r = Math.min(4, barW / 2, h);
          const neg = d.value < 0;
          // Rounded data-end only (top for positive, bottom for negative); flat at the baseline.
          const path = neg
            ? `M${x},${top} h${barW} v${h - r} a${r},${r} 0 0 1 -${r},${r} h-${barW - 2 * r} a${r},${r} 0 0 1 -${r},-${r} Z`
            : `M${x},${top + h} v-${h - r} a${r},${r} 0 0 1 ${r},-${r} h${barW - 2 * r} a${r},${r} 0 0 1 ${r},${r} v${h - r} Z`;
          return (
            <g key={d.date}>
              {h > 0 && (
                <path d={path} fill={neg ? "var(--viz-neg)" : "var(--viz-pos)"} opacity={hover === null || hover === i ? 1 : 0.55} />
              )}
              <rect
                x={PAD.left + i * band}
                y={PAD.top}
                width={band}
                height={innerH}
                fill="transparent"
                onMouseEnter={() => setHover(i)}
                onFocus={() => setHover(i)}
                tabIndex={0}
                aria-label={`${d.date}: ${format(d.value)}`}
              />
              {i % labelEvery === 0 && (
                <text x={PAD.left + i * band + band / 2} y={H - 6} textAnchor="middle" fontSize={10} fill="var(--text-faint)" className="num">
                  {d.date.slice(5)}
                </text>
              )}
            </g>
          );
        })}
        <line x1={PAD.left} x2={width - PAD.right} y1={zero} y2={zero} stroke="var(--border-strong)" strokeWidth={1} />
      </svg>
      {hover !== null && data[hover] && (
        <div
          className="pointer-events-none absolute z-10 rounded-sm border border-border-strong bg-panel-2 px-2 py-1 text-[11px] shadow-lg"
          style={{
            left: Math.min(PAD.left + hover * band + band / 2 + 8, width - 150),
            top: 4,
          }}
        >
          <div className="num text-faint">{data[hover].date}</div>
          <div className="num text-text">{format(data[hover].value)}</div>
          {data[hover].detail && <div className="text-dim">{data[hover].detail}</div>}
        </div>
      )}
    </div>
  );
}
