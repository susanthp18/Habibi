import { Phone, MessageSquare, MessageCircle, Bot, User, ArrowLeftRight, Flag, ShieldAlert, TrendingDown, VolumeX, AlertOctagon, Star } from "lucide-react";
import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";
import {
  formatDateTime,
  formatDuration,
  sentimentColor,
  type CallFlag,
  type CallRecord,
} from "@/data/audit-seed";
import { Lozenge, type LozengeTone } from "@/components/ui/lozenge";

interface Props {
  rows: CallRecord[];
  selected: Set<string>;
  onToggle: (id: string) => void;
  onToggleAll: (all: boolean) => void;
  openId: string | null;
  onOpen: (id: string) => void;
}

const CHANNEL_ICON = { voice: Phone, whatsapp: MessageCircle, sms: MessageSquare } as const;
const FLAG_ICON: Record<CallFlag, { icon: typeof Flag; label: string; tone: string }> = {
  "compliance-miss": { icon: ShieldAlert, label: "Compliance miss", tone: "text-text-danger" },
  "sentiment-drop": { icon: TrendingDown, label: "Sentiment drop", tone: "text-text-danger" },
  escalation: { icon: ArrowLeftRight, label: "Escalated", tone: "text-text-warning" },
  silence: { icon: VolumeX, label: "Silence", tone: "text-text-subtlest" },
  "abuse-detected": { icon: AlertOctagon, label: "Abuse detected", tone: "text-text-danger" },
  "high-value": { icon: Star, label: "High value", tone: "text-text-brand" },
};

function Sparkline({ points }: { points: { t: number; v: number }[] }) {
  if (points.length < 2) return null;
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
    <svg width={w} height={h} className="overflow-visible">
      <line x1={0} y1={h / 2} x2={w} y2={h / 2} stroke="var(--border)" strokeDasharray="2 2" />
      <path d={path} fill="none" stroke={sentimentColor(avg)} strokeWidth={1.4} strokeLinecap="round" />
    </svg>
  );
}

function HandlerChip({ c }: { c: CallRecord }) {
  const { handledBy } = c;
  if (handledBy.kind === "bot") {
    return (
      <Lozenge tone="selected">
        <Bot className="h-3 w-3" /> {handledBy.bot}
      </Lozenge>
    );
  }
  if (handledBy.kind === "human") {
    return (
      <Lozenge tone="neutral" className="text-text">
        <User className="h-3 w-3" /> {handledBy.agent}
      </Lozenge>
    );
  }
  return (
    <Lozenge tone="warning">
      <ArrowLeftRight className="h-3 w-3" /> {handledBy.bot} → {handledBy.agent}
    </Lozenge>
  );
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

export function CallsTable({ rows, selected, onToggle, onToggleAll, openId, onOpen }: Props) {
  const allSelected = rows.length > 0 && rows.every((r) => selected.has(r.id));

  return (
    <div className="min-h-0 flex-1 overflow-auto">
      <table className="w-full min-w-[68.75rem] border-separate border-spacing-0 text-body">
        <thead className="sticky top-0 z-10 bg-surface-sunken text-body-small font-semibold text-text-subtlest">
          <tr>
            <th className="w-400 border-b border-border px-150 py-100 text-left">
              <Checkbox
                checked={allSelected}
                onCheckedChange={(v) => onToggleAll(!!v)}
                aria-label="Select all"
              />
            </th>
            <th className="border-b border-border px-150 py-100 text-left">When</th>
            <th className="border-b border-border px-150 py-100 text-left">Customer</th>
            <th className="border-b border-border px-150 py-100 text-left">Ch.</th>
            <th className="border-b border-border px-150 py-100 text-left">Handled by</th>
            <th className="border-b border-border px-150 py-100 text-right">Dur.</th>
            <th className="border-b border-border px-150 py-100 text-left">Disposition</th>
            <th className="border-b border-border px-150 py-100 text-left">Sentiment</th>
            <th className="border-b border-border px-150 py-100 text-left">Flags</th>
            <th className="border-b border-border px-150 py-100 text-left">Call ID</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => {
            const ChIcon = CHANNEL_ICON[c.channel];
            const isOpen = openId === c.id;
            return (
              <tr
                key={c.id}
                onClick={() => onOpen(c.id)}
                className={cn(
                  "cursor-pointer hover:bg-surface-sunken",
                  isOpen && "bg-background-brand-subtlest/50",
                )}
              >
                <td className="border-b border-border px-150 py-100" onClick={(e) => e.stopPropagation()}>
                  <Checkbox
                    checked={selected.has(c.id)}
                    onCheckedChange={() => onToggle(c.id)}
                    aria-label={`Select ${c.id}`}
                  />
                </td>
                <td className="border-b border-border px-150 py-100 whitespace-nowrap text-text-subtle">
                  {formatDateTime(c.startedAt)}
                </td>
                <td className="border-b border-border px-150 py-100">
                  <div className="font-medium text-text">{c.customerName}</div>
                  <div className="text-body-small text-text-subtlest">{c.phoneMasked} · {c.accountId}</div>
                </td>
                <td className="border-b border-border px-150 py-100">
                  <ChIcon className="h-4 w-4 text-text-subtle" aria-label={c.channel} />
                </td>
                <td className="border-b border-border px-150 py-100">
                  <HandlerChip c={c} />
                </td>
                <td className="border-b border-border px-150 py-100 text-right font-mono text-body-small text-text-subtle">
                  {formatDuration(c.duration)}
                </td>
                <td className="border-b border-border px-150 py-100">
                  <Lozenge tone={DISPOSITION_TONE[c.disposition] ?? "neutral"}>
                    {c.disposition}
                  </Lozenge>
                </td>
                <td className="border-b border-border px-150 py-100">
                  <Sparkline points={c.sentimentSeries} />
                </td>
                <td className="border-b border-border px-150 py-100">
                  <div className="flex items-center gap-050">
                    {c.flags.length === 0 ? (
                      <span className="text-body-small text-text-subtlest">—</span>
                    ) : (
                      c.flags.map((f) => {
                        const key = (typeof f === "string" ? f : (f as { flag?: string })?.flag) as CallFlag | undefined;
                        const meta = key ? FLAG_ICON[key] : undefined;
                        if (!meta) return null;
                        const Icon = meta.icon;
                        return (
                          <span key={key} title={meta.label} className={cn("inline-flex", meta.tone)}>
                            <Icon className="h-3.5 w-3.5" />
                          </span>
                        );
                      })
                    )}
                  </div>
                </td>
                <td className="border-b border-border px-150 py-100 font-mono text-body-small text-text-subtlest">
                  {c.id}
                </td>
              </tr>
            );
          })}
          {rows.length === 0 && (
            <tr>
              <td colSpan={10} className="px-300 py-800 text-center text-text-subtlest">
                No calls match these filters.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
