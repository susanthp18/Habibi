import { useMemo } from "react";
import { CalendarClock, Clock, Shield, User } from "lucide-react";
import { ChannelChip } from "./ChannelChip";
import { ContactablePill } from "./ContactablePill";
import { contactableSummary, daysUntil, type ConsentRecord } from "@/data/consent-seed";
import { Lozenge } from "@/components/ui/lozenge";
import {
  RecordsAvatarMark,
  RecordsTable,
  type RecordsColumn,
} from "@/components/records/RecordsTable";
import { RecordsTag } from "@/components/records/RecordsTag";

const DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function formatWindow(rec: ConsentRecord) {
  const days = rec.allowedWindow?.days ?? [];
  const isWeekdays = days.length === 5 && days.every((d, i) => d === i + 1);
  const isDaily = days.length === 7;
  const start = rec.allowedWindow?.startHour ?? 0;
  const end = rec.allowedWindow?.endHour ?? 0;
  const range = `${String(start).padStart(2, "0")}:00–${String(end).padStart(2, "0")}:00`;
  const daySpan = isDaily
    ? "Daily"
    : isWeekdays
      ? "Weekdays"
      : days.map((d) => DAY_LABELS[d]).join(", ");
  return `${daySpan} · ${range}`;
}

const CONTACTABLE_RANK = { green: 3, amber: 2, red: 1 } as const;

export function ConsentTable({
  rows,
  onOpen,
  selectedId: _selectedId,
}: {
  rows: ConsentRecord[];
  onOpen: (id: string) => void;
  selectedId: string | null;
}) {
  const columns = useMemo<RecordsColumn<ConsentRecord>[]>(
    () => [
      {
        id: "customer",
        header: "Customer",
        headerIcon: <User className="h-3.5 w-3.5" />,
        sticky: true,
        sortable: true,
        sortValue: (r) => r.customerName,
        className: "min-w-[14rem]",
        cell: (r) => (
          <button
            type="button"
            onClick={() => onOpen(r.id)}
            className="flex min-w-0 items-center gap-100 text-left"
          >
            <RecordsAvatarMark label={r.customerName || "?"} />
            <span className="min-w-0">
              <span className="block truncate text-sm font-medium text-text-brand hover:underline">
                {r.customerName}
              </span>
              <span className="flex flex-wrap items-center gap-050 text-body-small text-text-subtlest">
                <span className="font-mono">{r.accountId}</span>
                <RecordsTag name={r.segment || "—"} />
                {r.onDndRegistry ? <Lozenge tone="danger">DND registry</Lozenge> : null}
              </span>
            </span>
          </button>
        ),
        footer: (visible) => (
          <span>
            <span className="font-semibold tabular text-text">{visible.length}</span>{" "}
            <span className="text-text-subtlest">records</span>
          </span>
        ),
      },
      {
        id: "contactable",
        header: "Contactable",
        headerIcon: <Shield className="h-3.5 w-3.5" />,
        sortable: true,
        sortValue: (r) => CONTACTABLE_RANK[contactableSummary(r).status] ?? 0,
        cell: (r) => <ContactablePill record={r} />,
        footer: (visible) => {
          const ok = visible.filter((r) => contactableSummary(r).status === "green").length;
          return <span className="text-text-subtlest">{ok} contactable</span>;
        },
      },
      {
        id: "channels",
        header: "Channels · this week",
        cell: (r) => (
          <div className="flex flex-wrap gap-050">
            {(r.channels ?? []).map((c) => (
              <ChannelChip key={c.channel} cc={c} />
            ))}
          </div>
        ),
      },
      {
        id: "window",
        header: "Allowed window",
        headerIcon: <Clock className="h-3.5 w-3.5" />,
        cell: (r) => (
          <div>
            <div className="inline-flex items-center gap-050 text-body-small text-text-subtle">
              <Clock className="h-3 w-3" /> {formatWindow(r)}
            </div>
            <div className="text-body-small text-text-subtlest">{r.timezone}</div>
          </div>
        ),
      },
      {
        id: "expiry",
        header: "Consent expiry",
        headerIcon: <CalendarClock className="h-3.5 w-3.5" />,
        sortable: true,
        sortValue: (r) => (r.consentExpiresAt ? new Date(r.consentExpiresAt).getTime() : 0),
        cell: (r) => {
          const daysLeft = daysUntil(r.consentExpiresAt);
          const expiryTone =
            daysLeft < 0
              ? "text-text-danger"
              : daysLeft <= 30
                ? "text-text-warning"
                : "text-text-subtle";
          return (
            <div className={expiryTone}>
              <div className="inline-flex items-center gap-050 text-body-small font-medium">
                <CalendarClock className="h-3 w-3" />
                {daysLeft < 0 ? `Expired ${-daysLeft}d ago` : `${daysLeft}d left`}
              </div>
              <div className="text-body-small text-text-subtlest">
                {r.consentExpiresAt ? new Date(r.consentExpiresAt).toLocaleDateString() : "—"}
              </div>
            </div>
          );
        },
        footer: (visible) => {
          const expiring = visible.filter((r) => {
            const d = daysUntil(r.consentExpiresAt);
            return d >= 0 && d <= 30;
          }).length;
          return <span className="text-text-subtlest">{expiring} expiring</span>;
        },
      },
      {
        id: "optout",
        header: "Last opt-out",
        cell: (r) => {
          const lastOptOut = r.optOutLog?.[r.optOutLog.length - 1];
          if (!lastOptOut) return <span className="text-text-subtlest">—</span>;
          return (
            <div className="text-body-small text-text-subtle">
              <div className="font-medium text-text">
                {lastOptOut.channel === "all" ? "All channels" : lastOptOut.channel} ·{" "}
                {lastOptOut.source}
              </div>
              <div className="text-body-small text-text-subtlest">
                {new Date(lastOptOut.at).toLocaleDateString()} · {lastOptOut.actor}
              </div>
            </div>
          );
        },
      },
    ],
    [onOpen],
  );

  return (
    <RecordsTable
      rows={rows}
      getRowId={(r) => r.id}
      columns={columns}
      emptyMessage="No consent records match the current filters."
      ariaLabel="Consent registry table"
      defaultSort={{ id: "customer", dir: 1 }}
      className="h-full min-h-0"
    />
  );
}
