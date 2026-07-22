import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { StackedPoint } from "@/data/dashboard-seed";

function fmtDate(d: string) {
  const dt = new Date(d);
  return dt.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function CallVolumeChart({ data }: { data: StackedPoint[] }) {
  return (
    <div className="flex h-full flex-col rounded-lg border border-border bg-surface-card p-4 shadow-card">
      <div className="mb-2">
        <h3 className="text-sm font-semibold text-brand-navy">Call volume by channel</h3>
        <p className="text-xs text-text-secondary">Voice · WhatsApp · Chat (last 30 days)</p>
      </div>
      <div className="min-h-0 flex-1">
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
                background: "var(--surface-card)",
                border: "1px solid var(--border)",
                borderRadius: 8,
                fontSize: 12,
              }}
              labelFormatter={(v) => fmtDate(String(v))}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} iconType="circle" />
            <Bar dataKey="voice" stackId="a" fill="var(--brand-primary)" name="Voice" radius={[0, 0, 0, 0]} />
            <Bar dataKey="whatsapp" stackId="a" fill="var(--success)" name="WhatsApp" />
            <Bar dataKey="chat" stackId="a" fill="var(--warning)" name="Chat" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
