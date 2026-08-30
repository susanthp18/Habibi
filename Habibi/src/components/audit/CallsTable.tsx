import { useMemo } from "react";
import {
  Phone,
  MessageSquare,
  MessageCircle,
  Bot,
  User,
  ArrowLeftRight,
  Flag,
  ShieldAlert,
  TrendingDown,
  VolumeX,
  AlertOctagon,
  Star,
  CalendarClock,
  Hash,
  Timer,
  Radio,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  formatDateTime,
  formatDuration,
  sentimentColor,
  type CallFlag,
  type CallRecord,
} from "@/data/audit-seed";
import { Lozenge, type LozengeTone } from "@/components/ui/lozenge";
import {
  RecordsAvatarMark,
  RecordsTable,
  type RecordsColumn,
} from "@/components/records/RecordsTable";
import { RecordsTag } from "@/components/records/RecordsTag";

interface Props {
  rows: CallRecord[];
  selected: Set<string>;
  onSelectedChange: (next: Set<string>) => void;
  openId: string | null;
  onOpen: (id: string) => void;
}

const CHANNEL_ICON = { voice: Phone, whatsapp: MessageCircle, sms: MessageSquare } as const;
const CHANNEL_LABEL = { voice: "Voice", whatsapp: "WhatsApp", sms: "SMS" } as const;

const FLAG_ICON: Record<CallFlag, { icon: typeof Flag; label: string; tone: string }> = {
  "compliance-miss": { icon: ShieldAlert, label: "Compliance miss", tone: "text-text-danger" },
  "sentiment-drop": { icon: TrendingDown, label: "Sentiment drop", tone: "text-text-danger" },
  escalation: { icon: ArrowLeftRight, label: "Escalated", tone: "text-text-warning" },
  silence: { icon: VolumeX, label: "Silence", tone: "text-text-subtlest" },
  "abuse-detected": { icon: AlertOctagon, label: "Abuse detected", tone: "text-text-danger" },
  "high-value": { icon: Star, label: "High value", tone: "text-text-brand" },
};

function Sparkline({ points }: { points: { t: number; v: number }[] }) {
  if (!points || points.length < 2)
    return <span className="text-body-small text-text-subtlest">—</span>;
  const w = 72;
  const h = 20;
  const xs = points.map((p) => p.t);
  const xMax = Math.max(...xs);
  const path = points
    .map((p, i) => {
      const x = (p.t / (xMax || 1)) * w;
      const y = h / 2 - (p.v * h) / 2;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const avg = points.reduce((s, p) => s + p.v, 0) / points.length;
  return (
    <svg width={w} height={h} className="overflow-visible" aria-hidden>
      <line x1={0} y1={h / 2} x2={w} y2={h / 2} stroke="var(--border)" strokeDasharray="2 2" />
      <path
        d={path}
        fill="none"
        stroke={sentimentColor(avg)}
        strokeWidth={1.4}
        strokeLinecap="round"
      />
    </svg>
  );
}

function HandlerChip({ c }: { c: CallRecord }) {
  const { handledBy } = c;
  if (handledBy?.kind === "bot") {
    return (
      <Lozenge tone="selected">
        <Bot className="h-3 w-3" /> {handledBy.bot ?? "Bot"}
      </Lozenge>
    );
  }
  if (handledBy?.kind === "human") {
    return (
      <Lozenge tone="neutral" className="text-text">
        <User className="h-3 w-3" /> {handledBy.agent ?? "Agent"}
      </Lozenge>
    );
  }
  if (handledBy?.kind === "handoff") {
    return (
      <Lozenge tone="warning">
        <ArrowLeftRight className="h-3 w-3" /> {handledBy.bot} → {handledBy.agent}
      </Lozenge>
    );
  }
  return <span className="text-body-small text-text-subtlest">—</span>;
}

const DISPOSITION_TONE: Record<string, LozengeTone> = {
  "PTP Captured": "success",
  "Payment Made": "success",
  "Info Query Resolved": "selected",
  "Dispute Raised": "danger",
  "Callback Scheduled": "neutral",
  Escalated: "warning",
  "No Answer": "neutral",
  Voicemail: "neutral",
  "DND — Not Contacted": "neutral",
};

export function CallsTable({ rows, selected, onSelectedChange, openId, onOpen }: Props) {
  const columns = useMemo<RecordsColumn<CallRecord>[]>(
    () => [
      {
        id: "customer",
        header: "Customer",
        headerIcon: <User className="h-3.5 w-3.5" />,
        sticky: true,
        sortable: true,
        sortValue: (c) => c.customerName,
        className: "min-w-[14rem]",
        cell: (c) => (
          <button
            type="button"
            onClick={() => onOpen(c.id)}
            className={cn(
              "flex min-w-0 items-center gap-100 text-left",
              openId === c.id && "text-text-brand",
            )}
          >
            <RecordsAvatarMark label={c.customerName || "?"} />
            <span className="min-w-0">
              <span className="block truncate text-sm font-medium text-text-brand hover:underline">
                {c.customerName || "Unknown"}
              </span>
              <span className="block truncate text-body-small text-text-subtlest">
                {c.phoneMasked} · {c.accountId}
              </span>
            </span>
          </button>
        ),
        footer: (visible) => (
          <span>
            <span className="font-semibold tabular text-text">{visible.length}</span>{" "}
            <span className="text-text-subtlest">calls</span>
          </span>
        ),
      },
      {
        id: "when",
        header: "When",
        headerIcon: <CalendarClock className="h-3.5 w-3.5" />,
        sortable: true,
        sortValue: (c) => (c.startedAt ? new Date(c.startedAt).getTime() : 0),
        cell: (c) => (
          <span className="whitespace-nowrap text-text-subtle">{formatDateTime(c.startedAt)}</span>
        ),
      },
      {
        id: "channel",
        header: "Channel",
        headerIcon: <Radio className="h-3.5 w-3.5" />,
        sortable: true,
        sortValue: (c) => c.channel,
        cell: (c) => {
          const ChIcon = CHANNEL_ICON[c.channel] ?? Phone;
          return (
            <span className="inline-flex items-center gap-050">
              <ChIcon className="h-4 w-4 text-text-subtle" aria-hidden />
              <RecordsTag name={CHANNEL_LABEL[c.channel] ?? c.channel} />
            </span>
          );
        },
        footer: (visible) => {
          const voice = visible.filter((c) => c.channel === "voice").length;
          return <span className="text-text-subtlest">{voice} voice</span>;
        },
      },
      {
        id: "handledBy",
        header: "Handled by",
        headerIcon: <Bot className="h-3.5 w-3.5" />,
        sortable: true,
        sortValue: (c) => c.handledBy?.kind ?? "",
        cell: (c) => <HandlerChip c={c} />,
      },
      {
        id: "duration",
        header: "Dur.",
        headerIcon: <Timer className="h-3.5 w-3.5" />,
        sortable: true,
        sortValue: (c) => c.duration ?? 0,
        align: "right",
        cell: (c) => (
          <span className="font-mono text-body-small text-text-subtle">
            {formatDuration(c.duration)}
          </span>
        ),
        footer: (visible) => {
          if (!visible.length) return <span className="text-text-subtlest">—</span>;
          const avg = Math.round(
            visible.reduce((s, c) => s + (c.duration || 0), 0) / visible.length,
          );
          return <span className="tabular">{formatDuration(avg)} avg</span>;
        },
      },
      {
        id: "disposition",
        header: "Disposition",
        sortable: true,
        sortValue: (c) => c.disposition ?? "",
        cell: (c) => (
          <Lozenge tone={DISPOSITION_TONE[c.disposition] ?? "neutral"}>
            {c.disposition || "—"}
          </Lozenge>
        ),
      },
      {
        id: "sentiment",
        header: "Sentiment",
        sortable: true,
        sortValue: (c) => c.avgSentiment ?? 0,
        cell: (c) => <Sparkline points={c.sentimentSeries ?? []} />,
        footer: (visible) => {
          const withS = visible.filter((c) => typeof c.avgSentiment === "number");
          if (!withS.length) return <span className="text-text-subtlest">—</span>;
          const avg = withS.reduce((s, c) => s + c.avgSentiment, 0) / withS.length;
          return (
            <span className="tabular">
              {avg >= 0 ? "+" : ""}
              {avg.toFixed(2)} avg
            </span>
          );
        },
      },
      {
        id: "flags",
        header: "Flags",
        cell: (c) => {
          const flags = c.flags ?? [];
          if (flags.length === 0)
            return <span className="text-body-small text-text-subtlest">—</span>;
          return (
            <div className="flex items-center gap-050">
              {flags.map((f, idx) => {
                const key = (typeof f === "string" ? f : (f as { flag?: string })?.flag) as
                  CallFlag | undefined;
                const meta = key ? FLAG_ICON[key] : undefined;
                if (!meta) return null;
                const Icon = meta.icon;
                return (
                  <span
                    key={`${key}-${idx}`}
                    title={meta.label}
                    className={cn("inline-flex", meta.tone)}
                  >
                    <Icon className="h-3.5 w-3.5" />
                  </span>
                );
              })}
            </div>
          );
        },
        footer: (visible) => {
          const flagged = visible.filter((c) => (c.flags?.length ?? 0) > 0).length;
          return <span className="text-text-subtlest">{flagged} flagged</span>;
        },
      },
      {
        id: "id",
        header: "Call ID",
        headerIcon: <Hash className="h-3.5 w-3.5" />,
        sortable: true,
        sortValue: (c) => c.id,
        cell: (c) => (
          <button
            type="button"
            onClick={() => onOpen(c.id)}
            className="font-mono text-body-small text-text-subtlest hover:text-text-brand hover:underline"
          >
            {c.id}
          </button>
        ),
        footer: () =>
          selected.size > 0 ? (
            <span className="text-text-subtlest">{selected.size} selected</span>
          ) : (
            <span className="text-text-subtlest">—</span>
          ),
      },
    ],
    [onOpen, openId, selected.size],
  );

  return (
    <RecordsTable
      rows={rows}
      getRowId={(c) => c.id}
      columns={columns}
      selectable
      selected={selected}
      onSelectedChange={onSelectedChange}
      emptyMessage="No calls match these filters."
      ariaLabel="Call audit table"
      defaultSort={{ id: "when", dir: -1 }}
      className="h-full min-h-0"
    />
  );
}
