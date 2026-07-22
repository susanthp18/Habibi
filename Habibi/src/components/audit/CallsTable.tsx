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
  "compliance-miss": { icon: ShieldAlert, label: "Compliance miss", tone: "text-[var(--danger)]" },
  "sentiment-drop": { icon: TrendingDown, label: "Sentiment drop", tone: "text-[var(--danger)]" },
  escalation: { icon: ArrowLeftRight, label: "Escalated", tone: "text-[var(--warning)]" },
  silence: { icon: VolumeX, label: "Silence", tone: "text-text-muted" },
  "abuse-detected": { icon: AlertOctagon, label: "Abuse detected", tone: "text-[var(--danger)]" },
  "high-value": { icon: Star, label: "High value", tone: "text-brand-primary" },
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
      <line x1={0} y1={h / 2} x2={w} y2={h / 2} stroke="var(--border-token)" strokeDasharray="2 2" />
      <path d={path} fill="none" stroke={sentimentColor(avg)} strokeWidth={1.4} strokeLinecap="round" />
    </svg>
  );
}

function HandlerChip({ c }: { c: CallRecord }) {
  const { handledBy } = c;
  if (handledBy.kind === "bot") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-brand-tint px-2 py-0.5 text-[11px] font-medium text-brand-primary-dark">
        <Bot className="h-3 w-3" /> {handledBy.bot}
      </span>
    );
  }
  if (handledBy.kind === "human") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-surface-sunken px-2 py-0.5 text-[11px] font-medium text-text-primary">
        <User className="h-3 w-3" /> {handledBy.agent}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-[var(--warning-bg)] px-2 py-0.5 text-[11px] font-medium text-[var(--warning)]">
      <ArrowLeftRight className="h-3 w-3" /> {handledBy.bot} → {handledBy.agent}
    </span>
  );
}

const DISPOSITION_TONE: Record<string, string> = {
  "PTP Captured": "bg-[var(--success-bg)] text-[var(--success)]",
  "Payment Made": "bg-[var(--success-bg)] text-[var(--success)]",
  "Info Query Resolved": "bg-brand-tint text-brand-primary-dark",
  "Dispute Raised": "bg-[var(--danger-bg)] text-[var(--danger)]",
  "Callback Scheduled": "bg-surface-sunken text-text-primary",
  Escalated: "bg-[var(--warning-bg)] text-[var(--warning)]",
  "No Answer": "bg-surface-sunken text-text-muted",
  Voicemail: "bg-surface-sunken text-text-muted",
  "DND — Not Contacted": "bg-surface-sunken text-text-muted",
};

export function CallsTable({ rows, selected, onToggle, onToggleAll, openId, onOpen }: Props) {
  const allSelected = rows.length > 0 && rows.every((r) => selected.has(r.id));

  return (
    <div className="min-h-0 flex-1 overflow-auto">
      <table className="w-full min-w-[1100px] border-separate border-spacing-0 text-[13px]">
        <thead className="sticky top-0 z-10 bg-surface-sunken text-[11px] font-semibold uppercase tracking-wide text-text-muted">
          <tr>
            <th className="w-8 border-b border-[var(--border-token)] px-3 py-2 text-left">
              <Checkbox
                checked={allSelected}
                onCheckedChange={(v) => onToggleAll(!!v)}
                aria-label="Select all"
              />
            </th>
            <th className="border-b border-[var(--border-token)] px-3 py-2 text-left">When</th>
            <th className="border-b border-[var(--border-token)] px-3 py-2 text-left">Customer</th>
            <th className="border-b border-[var(--border-token)] px-3 py-2 text-left">Ch.</th>
            <th className="border-b border-[var(--border-token)] px-3 py-2 text-left">Handled by</th>
            <th className="border-b border-[var(--border-token)] px-3 py-2 text-right">Dur.</th>
            <th className="border-b border-[var(--border-token)] px-3 py-2 text-left">Disposition</th>
            <th className="border-b border-[var(--border-token)] px-3 py-2 text-left">Sentiment</th>
            <th className="border-b border-[var(--border-token)] px-3 py-2 text-left">Flags</th>
            <th className="border-b border-[var(--border-token)] px-3 py-2 text-left">Call ID</th>
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
                  isOpen && "bg-brand-tint/50",
                )}
              >
                <td className="border-b border-[var(--border-token)] px-3 py-2" onClick={(e) => e.stopPropagation()}>
                  <Checkbox
                    checked={selected.has(c.id)}
                    onCheckedChange={() => onToggle(c.id)}
                    aria-label={`Select ${c.id}`}
                  />
                </td>
                <td className="border-b border-[var(--border-token)] px-3 py-2 whitespace-nowrap text-text-secondary">
                  {formatDateTime(c.startedAt)}
                </td>
                <td className="border-b border-[var(--border-token)] px-3 py-2">
                  <div className="font-medium text-text-primary">{c.customerName}</div>
                  <div className="text-[11px] text-text-muted">{c.phoneMasked} · {c.accountId}</div>
                </td>
                <td className="border-b border-[var(--border-token)] px-3 py-2">
                  <ChIcon className="h-4 w-4 text-text-secondary" aria-label={c.channel} />
                </td>
                <td className="border-b border-[var(--border-token)] px-3 py-2">
                  <HandlerChip c={c} />
                </td>
                <td className="border-b border-[var(--border-token)] px-3 py-2 text-right font-mono text-[12px] text-text-secondary">
                  {formatDuration(c.duration)}
                </td>
                <td className="border-b border-[var(--border-token)] px-3 py-2">
                  <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium", DISPOSITION_TONE[c.disposition] ?? "bg-surface-sunken text-text-primary")}>
                    {c.disposition}
                  </span>
                </td>
                <td className="border-b border-[var(--border-token)] px-3 py-2">
                  <Sparkline points={c.sentimentSeries} />
                </td>
                <td className="border-b border-[var(--border-token)] px-3 py-2">
                  <div className="flex items-center gap-1">
                    {c.flags.length === 0 ? (
                      <span className="text-[11px] text-text-muted">—</span>
                    ) : (
                      c.flags.map((f) => {
                        const meta = FLAG_ICON[f];
                        const Icon = meta.icon;
                        return (
                          <span key={f} title={meta.label} className={cn("inline-flex", meta.tone)}>
                            <Icon className="h-3.5 w-3.5" />
                          </span>
                        );
                      })
                    )}
                  </div>
                </td>
                <td className="border-b border-[var(--border-token)] px-3 py-2 font-mono text-[11px] text-text-muted">
                  {c.id}
                </td>
              </tr>
            );
          })}
          {rows.length === 0 && (
            <tr>
              <td colSpan={10} className="px-6 py-16 text-center text-text-muted">
                No calls match these filters.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
