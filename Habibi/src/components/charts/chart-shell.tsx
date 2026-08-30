import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

export function ChartCard({
  title,
  subtitle,
  action,
  className,
  children,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "flex h-full flex-col rounded-large border border-border bg-surface p-200 shadow-raised",
        className,
      )}
    >
      <div className="mb-100 flex items-start justify-between gap-150">
        <div className="min-w-0">
          <h3 className="text-body font-semibold tracking-tight text-text">{title}</h3>
          {subtitle ? (
            <p className="mt-025 text-body-small text-text-subtlest">{subtitle}</p>
          ) : null}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
      {children}
    </div>
  );
}

export function ChartStage({
  children,
  className,
  toolbar,
  ...pointerProps
}: {
  children: ReactNode;
  className?: string;
  toolbar?: ReactNode;
} & HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "flex min-h-0 flex-1 flex-col overflow-hidden rounded-medium bg-surface-sunken shadow-raised",
        className,
      )}
    >
      {toolbar ? (
        <div className="flex shrink-0 items-center justify-between border-b border-border px-150 py-075">
          {toolbar}
        </div>
      ) : null}
      <div className="chart-stage relative min-h-0 flex-1" {...pointerProps}>
        {children}
      </div>
    </div>
  );
}

export function ChartTooltip({
  time,
  rows,
}: {
  time?: string;
  rows: { label: string; value: string; color: string }[];
}) {
  return (
    <div className="chart-tooltip">
      {time ? <span className="chart-tooltip-time">{time}</span> : null}
      {rows.map((row) => (
        <div key={row.label} className="chart-tooltip-row">
          <span className="chart-tooltip-label">
            <span className="chart-tooltip-dot" style={{ background: row.color }} />
            <span className="chart-tooltip-name">{row.label}</span>
          </span>
          <strong className="chart-tooltip-value">{row.value}</strong>
        </div>
      ))}
    </div>
  );
}

export function ChartEmpty({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-full min-h-[12.5rem] items-center justify-center text-body-small text-text-subtlest">
      {children}
    </div>
  );
}

export function SnapshotPill({ children = "Snapshot" }: { children?: ReactNode }) {
  return (
    <span className="rounded-full bg-surface px-100 py-025 text-body-micro font-medium text-text-subtle shadow-raised">
      {children}
    </span>
  );
}
