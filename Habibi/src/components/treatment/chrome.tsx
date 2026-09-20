/** The Decision-intelligence screen's shared chrome: panels, stats, gates and tones. */
import { type ReactNode } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { AlertTriangle, Inbox, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { LoadingState } from "@/components/ui/loading-state";
import { type LozengeTone } from "@/components/ui/lozenge";
import { SectionMessage } from "@/components/ui/section-message";
import { fmtNum, fmtRate } from "@/api/treatment";

// ---------------------------------------------------------------------------
// Shared state scaffolding
//
// Loading, empty and error are rendered by one component so no section can
// quietly skip one. The error branch renders INSTEAD of the data — a failed
// live call must never fall through to a half-populated table, because a
// plausible-looking number with no backend behind it is worse than a gap.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Shared state scaffolding
//
// Loading, empty and error are rendered by one component so no section can
// quietly skip one. The error branch renders INSTEAD of the data — a failed
// live call must never fall through to a half-populated table, because a
// plausible-looking number with no backend behind it is worse than a gap.
// ---------------------------------------------------------------------------

export function ErrorPanel({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <div className="flex flex-col gap-150 py-200">
      <SectionMessage variant="error" icon={AlertTriangle} title="Couldn’t load this section">
        {error instanceof Error ? error.message : "The backend did not return a usable response."}
      </SectionMessage>
      <div>
        <Button size="sm" variant="outline" onClick={onRetry}>
          <RefreshCw className="mr-075 h-3.5 w-3.5" /> Try again
        </Button>
      </div>
    </div>
  );
}

export function EmptyPanel({
  title,
  body,
  icon: Icon = Inbox,
}: {
  title: string;
  body: string;
  icon?: typeof Inbox;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-100 rounded-large border border-dashed border-border py-600 text-center">
      <Icon aria-hidden className="size-6 text-icon-subtlest" />
      <p className="heading-xsmall text-text">{title}</p>
      <p className="max-w-md text-body-small text-text-subtle">{body}</p>
    </div>
  );
}

export function StateGate<T>({
  query,
  loadingLabel,
  isEmpty,
  emptyTitle = "Nothing here yet",
  emptyBody = "Once the engine logs against this window, it will show up here.",
  emptyIcon,
  children,
}: {
  query: UseQueryResult<T>;
  loadingLabel: string;
  isEmpty?: (data: T) => boolean;
  emptyTitle?: string;
  emptyBody?: string;
  emptyIcon?: typeof Inbox;
  children: (data: T) => ReactNode;
}) {
  if (query.isError) {
    return <ErrorPanel error={query.error} onRetry={() => void query.refetch()} />;
  }
  if (query.isPending || query.data === undefined) {
    return (
      <div className="grid place-items-center py-600">
        <LoadingState label={loadingLabel} />
      </div>
    );
  }
  if (isEmpty?.(query.data)) {
    return <EmptyPanel title={emptyTitle} body={emptyBody} icon={emptyIcon} />;
  }
  return <>{children(query.data)}</>;
}

// ---------------------------------------------------------------------------
// Small presentational pieces
// ---------------------------------------------------------------------------

export function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-025 rounded-large border border-border bg-surface p-150">
      <span className="text-body-small text-text-subtle">{label}</span>
      <span className="heading-small tabular-nums text-text">{value}</span>
      {hint ? <span className="text-body-tiny text-text-subtlest">{hint}</span> : null}
    </div>
  );
}

export function Panel({
  title,
  description,
  children,
  actions,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <section className="flex min-w-0 flex-col gap-150 rounded-large border border-border bg-surface p-200">
      <div className="flex items-start justify-between gap-150">
        <div className="min-w-0">
          <h2 className="heading-xsmall text-text">{title}</h2>
          {description ? <p className="text-body-small text-text-subtle">{description}</p> : null}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

/** Share-of-total bar list. Widths are relative to the largest row, not to the
 *  sum, so a long tail stays readable instead of collapsing to slivers. */

export function BarList({ rows }: { rows: Array<{ key: string; label: string; count: number }> }) {
  const max = Math.max(...rows.map((r) => r.count), 1);
  const total = rows.reduce((sum, r) => sum + r.count, 0);
  return (
    <ul className="flex flex-col gap-100">
      {rows.map((row) => (
        <li key={row.key} className="flex flex-col gap-025">
          <div className="flex items-baseline justify-between gap-100 text-body-small">
            <span className="min-w-0 truncate text-text">{row.label}</span>
            <span className="shrink-0 tabular-nums text-text-subtle">
              {fmtNum(row.count)} · {fmtRate(total ? row.count / total : null)}
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-small bg-background-neutral">
            <div
              className="h-full rounded-small bg-background-brand-bold"
              style={{ width: `${Math.max((row.count / max) * 100, 2)}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

export const HOLD_TONE: Record<string, LozengeTone> = {
  hardship: "warning",
  dispute: "information",
  complaint: "warning",
  bereavement: "discovery",
  legal: "danger",
  no_upsell: "warning",
};

export const SERVING_TONE: Record<string, LozengeTone> = {
  ok: "success",
  unregistered: "warning",
  stale: "warning",
  missing: "danger",
};

export const MODEL_STATUS_TONE: Record<string, LozengeTone> = {
  champion: "success",
  challenger: "information",
  retired: "neutral",
};

export const VERDICT_TONE: Record<string, LozengeTone> = {
  promoted: "success",
  rejected: "danger",
  skipped: "neutral",
};

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
