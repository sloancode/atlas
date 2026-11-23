import type { ReactNode } from "react";
import type { ConnectionState } from "@/lib/api";

export function PageHeader({
  code,
  title,
  subtitle,
  right,
}: {
  code: string;
  title: string;
  subtitle?: string;
  right?: ReactNode;
}) {
  return (
    <header className="mb-5 flex items-end justify-between gap-4 border-b border-border pb-4">
      <div>
        <div className="num mb-1 text-[11px] text-accent">{code}</div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 max-w-3xl text-dim">{subtitle}</p>}
      </div>
      {right}
    </header>
  );
}

export function Panel({
  title,
  right,
  children,
  className = "",
}: {
  title?: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-[3px] border border-border bg-panel ${className}`}>
      {title && (
        <div className="flex h-9 items-center justify-between border-b border-border px-3">
          <h2 className="text-[11px] font-medium uppercase tracking-[0.12em] text-dim">{title}</h2>
          {right}
        </div>
      )}
      <div className="p-3">{children}</div>
    </section>
  );
}

const STATE_STYLE: Record<ConnectionState, { label: string; cls: string }> = {
  connected: { label: "Connected", cls: "text-pos border-pos/40 bg-pos/10" },
  configured: { label: "Configured", cls: "text-info border-info/40 bg-info/10" },
  not_configured: { label: "Not configured", cls: "text-dim border-border-strong bg-panel-2" },
  error: { label: "Error", cls: "text-neg border-neg/40 bg-neg/10" },
  planned: { label: "Planned", cls: "text-faint border-border bg-panel-2" },
};

export function StateBadge({ state }: { state: ConnectionState }) {
  const s = STATE_STYLE[state];
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-sm border px-1.5 py-[1px] text-[10px] font-medium uppercase tracking-wide ${s.cls}`}
    >
      {s.label}
    </span>
  );
}

export type DataStatus =
  | "live"
  | "delayed"
  | "historical"
  | "estimated"
  | "incomplete"
  | "missing"
  | "simulated";

const DATA_STATUS_CLS: Record<DataStatus, string> = {
  live: "text-pos",
  delayed: "text-info",
  historical: "text-dim",
  estimated: "text-warn",
  incomplete: "text-warn",
  missing: "text-faint",
  simulated: "text-sim",
};

export function DataStatusTag({ status }: { status: DataStatus }) {
  return (
    <span className={`num text-[10px] uppercase tracking-wider ${DATA_STATUS_CLS[status]}`}>
      ● {status}
    </span>
  );
}

/** A metric tile. `value === null` renders as unavailable -- never as zero. */
export function MetricTile({
  label,
  value,
  status,
  note,
}: {
  label: string;
  value: string | null;
  status: DataStatus;
  note?: string;
}) {
  return (
    <div className="rounded-[3px] border border-border bg-panel px-3 py-2.5">
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-dim">{label}</span>
        <DataStatusTag status={value === null ? "missing" : status} />
      </div>
      <div className={`num mt-1.5 text-[22px] leading-none ${value === null ? "text-faint" : ""}`}>
        {value ?? "—"}
      </div>
      {note && <div className="mt-1.5 text-[11px] text-faint">{note}</div>}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-[3px] border border-dashed border-border-strong px-4 py-6 text-center">
      <div className="font-medium text-dim">{title}</div>
      {children && <div className="mx-auto mt-1.5 max-w-xl text-[12px] text-faint">{children}</div>}
    </div>
  );
}

export function Code({ children }: { children: ReactNode }) {
  return (
    <code className="num rounded-sm border border-border bg-panel-2 px-1 py-[1px] text-[11px] text-text">
      {children}
    </code>
  );
}
