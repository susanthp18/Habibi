import { useMemo } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  CALENDAR_END_HOUR,
  CALENDAR_START_HOUR,
  CAL_MINUTES,
  fmtDayShort,
  minutesFromStart,
  sameDay,
  weekDays,
  type Callback,
} from "@/data/callbacks-seed";
import { CallbackPill } from "./CallbackPill";

const SLOT_MINUTES = 30;
const ROW_H = 28; // px per 30-min slot
const TOTAL_H = (CAL_MINUTES / SLOT_MINUTES) * ROW_H;

function toISOAtDaySlot(day: Date, hour: number, minute: number): string {
  const d = new Date(day);
  d.setHours(hour, minute, 0, 0);
  return d.toISOString();
}

interface Props {
  list: Callback[];
  weekAnchor: Date;
  onPrevWeek: () => void;
  onNextWeek: () => void;
  onToday: () => void;
  onOpen: (id: string) => void;
  onDrop: (id: string, newISO: string) => void;
}

export function WeekCalendar({ list, weekAnchor, onPrevWeek, onNextWeek, onToday, onOpen, onDrop }: Props) {
  const days = useMemo(() => weekDays(weekAnchor), [weekAnchor]);
  const rangeLabel = `${days[0].toLocaleDateString(undefined, { month: "short", day: "numeric" })} – ${days[6].toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}`;

  const rows = Array.from({ length: CAL_MINUTES / SLOT_MINUTES }, (_, i) => i);
  const now = new Date();

  const byDay = days.map((day) =>
    list.filter((cb) => sameDay(new Date(cb.scheduledAt), day)).sort((a, b) => new Date(a.scheduledAt).getTime() - new Date(b.scheduledAt).getTime()),
  );

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  const handleDrop = (day: Date, hour: number, minute: number) => (e: React.DragEvent) => {
    e.preventDefault();
    const id = e.dataTransfer.getData("text/callback-id");
    if (!id) return;
    onDrop(id, toISOAtDaySlot(day, hour, minute));
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col rounded-lg border border-[var(--border-token)] bg-surface-card">
      <div className="flex shrink-0 items-center justify-between border-b border-[var(--border-token)] px-3 py-2">
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={onPrevWeek}><ChevronLeft className="h-4 w-4" /></Button>
          <Button variant="outline" size="sm" className="h-7 text-[11px]" onClick={onToday}>Today</Button>
          <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={onNextWeek}><ChevronRight className="h-4 w-4" /></Button>
          <div className="ml-1 text-[12px] font-semibold text-brand-navy">{rangeLabel}</div>
        </div>
        <div className="text-[10.5px] text-text-muted">
          {CALENDAR_START_HOUR.toString().padStart(2, "0")}:00 – {CALENDAR_END_HOUR.toString().padStart(2, "0")}:00 · Drag pills to reschedule
        </div>
      </div>

      {/* header row */}
      <div className="grid shrink-0 border-b border-[var(--border-token)]" style={{ gridTemplateColumns: "56px repeat(7, 1fr)" }}>
        <div className="border-r border-[var(--border-token)] bg-surface-sunken/50" />
        {days.map((d) => {
          const isToday = sameDay(d, new Date());
          const dayList = byDay[days.indexOf(d)];
          return (
            <div key={d.toISOString()} className={`border-r border-[var(--border-token)] px-2 py-1 text-center ${isToday ? "bg-brand-tint/40" : ""}`}>
              <div className={`text-[11px] font-semibold ${isToday ? "text-brand-primary-dark" : "text-brand-navy"}`}>{fmtDayShort(d)}</div>
              <div className="text-[10px] text-text-muted">{dayList.length} callback{dayList.length === 1 ? "" : "s"}</div>
            </div>
          );
        })}
      </div>

      {/* grid body — scrollable */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="relative grid" style={{ gridTemplateColumns: "56px repeat(7, 1fr)", height: TOTAL_H }}>
          {/* Time rail */}
          <div className="relative border-r border-[var(--border-token)] bg-surface-sunken/30">
            {rows.map((r) => {
              const totalMins = r * SLOT_MINUTES;
              const hour = CALENDAR_START_HOUR + Math.floor(totalMins / 60);
              const minute = totalMins % 60;
              if (minute !== 0) return null;
              return (
                <div key={r} className="absolute right-1 -translate-y-1/2 text-[10px] text-text-muted" style={{ top: r * ROW_H }}>
                  {hour.toString().padStart(2, "0")}:00
                </div>
              );
            })}
          </div>

          {/* Day columns */}
          {days.map((day, di) => {
            const isToday = sameDay(day, new Date());
            const nowMins = isToday ? (now.getHours() - CALENDAR_START_HOUR) * 60 + now.getMinutes() : -1;
            const nowTop = (nowMins / SLOT_MINUTES) * ROW_H;

            return (
              <div key={day.toISOString()} className="relative border-r border-[var(--border-token)]">
                {/* Slot grid lines + drop targets */}
                {rows.map((r) => {
                  const totalMins = r * SLOT_MINUTES;
                  const hour = CALENDAR_START_HOUR + Math.floor(totalMins / 60);
                  const minute = totalMins % 60;
                  return (
                    <div
                      key={r}
                      onDragOver={handleDragOver}
                      onDrop={handleDrop(day, hour, minute)}
                      className={`absolute inset-x-0 border-b ${minute === 0 ? "border-[var(--border-token)]" : "border-dashed border-[var(--border-token)]/40"}`}
                      style={{ top: r * ROW_H, height: ROW_H }}
                    />
                  );
                })}

                {/* Now line */}
                {isToday && nowMins >= 0 && nowMins <= CAL_MINUTES && (
                  <div className="pointer-events-none absolute inset-x-0 z-10 flex items-center" style={{ top: nowTop }}>
                    <div className="h-1.5 w-1.5 rounded-full bg-red-500" />
                    <div className="h-px flex-1 bg-red-500" />
                  </div>
                )}

                {/* Callback pills */}
                {byDay[di].map((cb) => {
                  const top = (minutesFromStart(cb.scheduledAt) / SLOT_MINUTES) * ROW_H;
                  const height = Math.max(24, (cb.windowMins / SLOT_MINUTES) * ROW_H - 2);
                  if (top < 0 || top > TOTAL_H) return null;
                  return (
                    <CallbackPill
                      key={cb.id}
                      cb={cb}
                      onOpen={() => onOpen(cb.id)}
                      onDragStart={(e) => e.dataTransfer.setData("text/callback-id", cb.id)}
                      style={{ top, height }}
                    />
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
