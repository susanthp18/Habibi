import type { StackedPoint } from "@/data/dashboard-seed";
import { ChartCard, ChartEmpty, ChartStage, ModernBars, SnapshotPill } from "@/components/charts";

function fmtDate(d: string) {
  const dt = new Date(d);
  return dt.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

const COLORS = {
  voice: "#1868db",
  whatsapp: "#5b7f24",
  chat: "#e06c00",
};

export function CallVolumeChart({ data }: { data: StackedPoint[] }) {
  const bars = data.map((d) => ({
    label: fmtDate(d.date),
    value: d.voice + d.whatsapp + d.chat,
    stack: [
      { key: "voice", value: d.voice, color: COLORS.voice, label: "Voice" },
      { key: "whatsapp", value: d.whatsapp, color: COLORS.whatsapp, label: "WhatsApp" },
      { key: "chat", value: d.chat, color: COLORS.chat, label: "Chat" },
    ],
  }));

  return (
    <ChartCard
      title="Call volume by channel"
      subtitle="Voice · WhatsApp · Chat & SMS"
      action={<SnapshotPill />}
    >
      <div className="mb-100 flex flex-wrap gap-150 text-body-tiny text-text-subtle">
        {(
          [
            ["Voice", COLORS.voice],
            ["WhatsApp", COLORS.whatsapp],
            ["Chat", COLORS.chat],
          ] as const
        ).map(([label, color]) => (
          <span key={label} className="inline-flex items-center gap-050">
            <span className="size-1.5 rounded-full" style={{ background: color }} />
            {label}
          </span>
        ))}
      </div>
      <ChartStage className="min-h-0 flex-1">
        {data.length === 0 ? (
          <ChartEmpty>No interactions in this period.</ChartEmpty>
        ) : (
          <div className="box-border flex h-full min-h-[12rem] items-stretch p-150">
            <ModernBars data={bars} className="h-full w-full" height={220} />
          </div>
        )}
      </ChartStage>
    </ChartCard>
  );
}
