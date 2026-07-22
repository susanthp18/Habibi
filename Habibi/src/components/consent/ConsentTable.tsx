import { Clock, CalendarClock } from "lucide-react";
import { ChannelChip } from "./ChannelChip";
import { ContactablePill } from "./ContactablePill";
import { daysUntil, type ConsentRecord } from "@/data/consent-seed";

const DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function formatWindow(rec: ConsentRecord) {
  const days = rec.allowedWindow.days;
  const isWeekdays = days.length === 5 && days.every((d, i) => d === i + 1);
  const isDaily = days.length === 7;
  const range = `${String(rec.allowedWindow.startHour).padStart(2, "0")}:00–${String(rec.allowedWindow.endHour).padStart(2, "0")}:00`;
  const daySpan = isDaily ? "Daily" : isWeekdays ? "Weekdays" : days.map((d) => DAY_LABELS[d]).join(", ");
  return `${daySpan} · ${range}`;
}

export function ConsentTable({
  rows,
  onOpen,
  selectedId,
}: {
  rows: ConsentRecord[];
  onOpen: (id: string) => void;
  selectedId: string | null;
}) {
  return (
    <div className="min-w-0 overflow-hidden rounded-md border border-[var(--border-token)] bg-surface-card">
      <div className="max-h-full overflow-auto">
        <table className="w-full text-[12px]">
          <thead className="sticky top-0 z-10 bg-surface-sunken text-text-secondary">
            <tr className="text-left">
              <th className="px-3 py-2 font-medium">Customer</th>
              <th className="px-3 py-2 font-medium">Contactable</th>
              <th className="px-3 py-2 font-medium">Channels · this week</th>
              <th className="px-3 py-2 font-medium">Allowed window</th>
              <th className="px-3 py-2 font-medium">Consent expiry</th>
              <th className="px-3 py-2 font-medium">Last opt-out</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-8 text-center text-[12px] text-text-muted">
                  No consent records match the current filters.
                </td>
              </tr>
            )}
            {rows.map((r) => {
              const daysLeft = daysUntil(r.consentExpiresAt);
              const expiryTone =
                daysLeft < 0 ? "text-[color:var(--danger)]" : daysLeft <= 30 ? "text-[color:var(--warning)]" : "text-text-secondary";
              const lastOptOut = r.optOutLog[r.optOutLog.length - 1];
              return (
                <tr
                  key={r.id}
                  onClick={() => onOpen(r.id)}
                  className={`cursor-pointer border-t border-[var(--border-token)] hover:bg-surface-sunken/60 ${
                    selectedId === r.id ? "bg-brand-tint/40" : ""
                  }`}
                >
                  <td className="px-3 py-2 align-top">
                    <div className="font-semibold text-brand-navy">{r.customerName}</div>
                    <div className="flex items-center gap-2 text-[10px] text-text-muted">
                      <span className="font-mono">{r.accountId}</span>
                      <span>· {r.segment}</span>
                      {r.onDndRegistry && (
                        <span className="rounded-full bg-[color:var(--danger-bg)] px-1.5 py-0.5 text-[9px] font-semibold uppercase text-[color:var(--danger)]">
                          DND registry
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-2 align-top">
                    <ContactablePill record={r} />
                  </td>
                  <td className="px-3 py-2 align-top">
                    <div className="flex flex-wrap gap-1">
                      {r.channels.map((c) => <ChannelChip key={c.channel} cc={c} />)}
                    </div>
                  </td>
                  <td className="px-3 py-2 align-top">
                    <div className="inline-flex items-center gap-1 text-[11px] text-text-secondary">
                      <Clock className="h-3 w-3" /> {formatWindow(r)}
                    </div>
                    <div className="text-[10px] text-text-muted">{r.timezone}</div>
                  </td>
                  <td className={`px-3 py-2 align-top ${expiryTone}`}>
                    <div className="inline-flex items-center gap-1 text-[11px] font-medium">
                      <CalendarClock className="h-3 w-3" />
                      {daysLeft < 0 ? `Expired ${-daysLeft}d ago` : `${daysLeft}d left`}
                    </div>
                    <div className="text-[10px] text-text-muted">
                      {new Date(r.consentExpiresAt).toLocaleDateString()}
                    </div>
                  </td>
                  <td className="px-3 py-2 align-top text-[11px] text-text-secondary">
                    {lastOptOut ? (
                      <div>
                        <div className="font-medium text-brand-navy">
                          {lastOptOut.channel === "all" ? "All channels" : lastOptOut.channel} · {lastOptOut.source}
                        </div>
                        <div className="text-[10px] text-text-muted">
                          {new Date(lastOptOut.at).toLocaleDateString()} · {lastOptOut.actor}
                        </div>
                      </div>
                    ) : (
                      <span className="text-text-muted">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
