import { AlertTriangle, FileClock, Loader2, Send, Timer } from "lucide-react";
import { MetricsStrip as Strip } from "@/components/records/MetricsStrip";

interface Metrics {
  openCount: number;
  generatingCount: number;
  sentTodayCount: number;
  failedCount: number;
  avgFulfilMins: number;
}

export function MetricsStrip({ m }: { m: Metrics }) {
  return (
    <Strip
      tiles={[
        {
          label: "Open",
          value: m.openCount,
          icon: FileClock,
          tone: "brand",
          sub: "Requested + generating",
        },
        {
          label: "Generating",
          value: m.generatingCount,
          icon: Loader2,
          tone: "warning",
          sub: "In flight",
        },
        {
          label: "Sent today",
          value: m.sentTodayCount,
          icon: Send,
          tone: "success",
          sub: "Last 24h",
        },
        {
          label: "Failed",
          value: m.failedCount,
          icon: AlertTriangle,
          tone: "danger",
          sub: "Needs retry",
        },
        {
          label: "Avg fulfilment",
          value:
            m.avgFulfilMins < 60 ? `${m.avgFulfilMins}m` : `${(m.avgFulfilMins / 60).toFixed(1)}h`,
          icon: Timer,
          tone: "neutral",
          sub: "Request → delivered",
        },
      ]}
    />
  );
}
