import { Clock, CalendarClock } from "lucide-react";
import { ChannelChip } from "./ChannelChip";
import { ContactablePill } from "./ContactablePill";
import { daysUntil, type ConsentRecord } from "@/data/consent-seed";
import { Lozenge } from "@/components/ui/lozenge";

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
    <div className="min-w-0 overflow-hidden rounded-medium border border-border bg-surface">
      <div className="max-h-full overflow-auto">
        <table className="w-full text-body-small">
          <thead className="sticky top-0 z-10 bg-surface-sunken text-text-subtle">
            <tr className="text-left">
              <th className="px-150 py-100 font-medium">Customer</th>
              <th className="px-150 py-100 font-medium">Contactable</th>
              <th className="px-150 py-100 font-medium">Channels · this week</th>
              <th className="px-150 py-100 font-medium">Allowed window</th>
              <th className="px-150 py-100 font-medium">Consent expiry</th>
              <th className="px-150 py-100 font-medium">Last opt-out</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={6} className="px-150 py-400 text-center text-body-small text-text-subtlest">
                  No consent records match the current filters.
                </td>
              </tr>
            )}
            {rows.map((r) => {
              const daysLeft = daysUntil(r.consentExpiresAt);
              const expiryTone =
                daysLeft < 0 ? "text-text-danger" : daysLeft <= 30 ? "text-text-warning" : "text-text-subtle";
              const lastOptOut = r.optOutLog[r.optOutLog.length - 1];
              return (
                <tr
                  key={r.id}
                  onClick={() => onOpen(r.id)}
                  className={`cursor-pointer border-t border-border hover:bg-surface-sunken/60 ${
                    selectedId === r.id ? "bg-background-brand-subtlest/40" : ""
                  }`}
                >
                  <td className="px-150 py-100 align-top">
                    <div className="font-semibold text-text">{r.customerName}</div>
                    <div className="flex items-center gap-100 text-body-small text-text-subtlest">
                      <span className="font-mono">{r.accountId}</span>
                      <span>· {r.segment}</span>
                      {r.onDndRegistry && (
                        <Lozenge tone="danger">
                          DND registry
                        </Lozenge>
                      )}
                    </div>
                  </td>
                  <td className="px-150 py-100 align-top">
                    <ContactablePill record={r} />
                  </td>
                  <td className="px-150 py-100 align-top">
                    <div className="flex flex-wrap gap-050">
                      {r.channels.map((c) => <ChannelChip key={c.channel} cc={c} />)}
                    </div>
                  </td>
                  <td className="px-150 py-100 align-top">
                    <div className="inline-flex items-center gap-050 text-body-small text-text-subtle">
                      <Clock className="h-3 w-3" /> {formatWindow(r)}
                    </div>
                    <div className="text-body-small text-text-subtlest">{r.timezone}</div>
                  </td>
                  <td className={`px-150 py-100 align-top ${expiryTone}`}>
                    <div className="inline-flex items-center gap-050 text-body-small font-medium">
                      <CalendarClock className="h-3 w-3" />
                      {daysLeft < 0 ? `Expired ${-daysLeft}d ago` : `${daysLeft}d left`}
                    </div>
                    <div className="text-body-small text-text-subtlest">
                      {new Date(r.consentExpiresAt).toLocaleDateString()}
                    </div>
                  </td>
                  <td className="px-150 py-100 align-top text-body-small text-text-subtle">
                    {lastOptOut ? (
                      <div>
                        <div className="font-medium text-text">
                          {lastOptOut.channel === "all" ? "All channels" : lastOptOut.channel} · {lastOptOut.source}
                        </div>
                        <div className="text-body-small text-text-subtlest">
                          {new Date(lastOptOut.at).toLocaleDateString()} · {lastOptOut.actor}
                        </div>
                      </div>
                    ) : (
                      <span className="text-text-subtlest">—</span>
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
