import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { StackedPoint } from "@/data/dashboard-seed";

function fmtDate(d: string) {
  const dt = new Date(d);
  return dt.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function CallVolumeChart({ data }: { data: StackedPoint[] }) {
  return (
    <div className="flex h-full flex-col rounded-large border border-border bg-surface p-200">
      <div className="mb-100">
        <h3 className="text-sm font-semibold text-text">Call volume by channel</h3>
        <p className="text-xs text-text-subtle">Voice · WhatsApp · Chat &amp; SMS</p>
      </div>
      <div className="min-h-0 flex-1">
        {data.length === 0 ? (
          <div className="flex h-full min-h-[200px] items-center justify-center text-body-small text-text-subtle">
            No interactions in this period.
          </div>
        ) : (
        <ResponsiveContainer width="100%" height="100%" minHeight={200}>
          <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
            <XAxis
              dataKey="date"
              tickFormatter={fmtDate}
              tick={{ fontSize: 11, fill: "var(--text-secondary)" }}
              axisLine={false}
              tickLine={false}
              minTickGap={24}
            />
            <YAxis tick={{ fontSize: 11, fill: "var(--text-secondary)" }} axisLine={false} tickLine={false} width={36} />
            <Tooltip
              contentStyle={{
                background: "var(--surface)",
                border: "1px solid var(--border)",
                borderRadius: 8,
                fontSize: 12,
              }}
              labelFormatter={(v) => fmtDate(String(v))}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} iconType="circle" />
            <Bar dataKey="voice" stackId="a" fill="var(--background-brand-bold)" name="Voice" radius={[0, 0, 0, 0]} />
            <Bar dataKey="whatsapp" stackId="a" fill="var(--chart-success-bold)" name="WhatsApp" />
            <Bar dataKey="chat" stackId="a" fill="var(--chart-warning-bold)" name="Chat" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
