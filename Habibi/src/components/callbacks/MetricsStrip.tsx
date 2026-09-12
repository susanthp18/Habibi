import { CalendarClock, CheckCircle2, PhoneOff, Timer, UserX } from "lucide-react";
import { MetricsStrip as Strip } from "@/components/records/MetricsStrip";

interface Metrics {
  scheduledToday: number;
  dueNextHour: number;
  missed7d: number;
  completionRate: number;
  unassigned: number;
}

export function MetricsStrip({ m }: { m: Metrics }) {
  return (
    <Strip
      tiles={[
        {
          label: "Scheduled today",
          value: m.scheduledToday,
          icon: CalendarClock,
          tone: "brand",
          sub: "Open + reminded",
        },
        {
          label: "Due next hour",
          value: m.dueNextHour,
          icon: Timer,
          tone: "warning",
          sub: "Prep or dial",
        },
        {
          label: "Missed (7d)",
          value: m.missed7d,
          icon: PhoneOff,
          tone: "danger",
          sub: "Needs recovery",
        },
        {
          label: "Completion (7d)",
          value: `${m.completionRate}%`,
          icon: CheckCircle2,
          tone: "success",
          sub: "Completed / total",
        },
        {
          label: "Unassigned",
          value: m.unassigned,
          icon: UserX,
          tone: "neutral",
          sub: "Awaiting owner",
        },
      ]}
    />
  );
}
