import { CalendarClock, ShieldAlert, ShieldCheck } from "lucide-react";
import {
  fmtDateTime,
  fmtMoney,
  fmtRelative,
  SOURCE_LABELS,
  STAGE_LABELS,
  type Lead,
  type LeadStage,
  type Sentiment,
} from "@/data/upsell-seed";
import { cn } from "@/lib/utils";

interface Props {
  leads: Lead[];
  onOpen: (l: Lead) => void;
}

const stageTone: Record<LeadStage, string> = {
  interested: "bg-brand-tint text-brand-primary-dark",
  contacted: "bg-indigo-50 text-indigo-700",
  qualified: "bg-amber-50 text-amber-700",
  won: "bg-emerald-50 text-emerald-700",
  lost: "bg-slate-100 text-slate-600",
};

const sentimentDot: Record<Sentiment, string> = {
  positive: "bg-emerald-500",
  neutral: "bg-slate-400",
  negative: "bg-red-500",
};

export function LeadTable({ leads, onOpen }: Props) {
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-[var(--border-token)] bg-surface-card">
      <div className="grid shrink-0 grid-cols-[2fr_2fr_1fr_1fr_1.2fr_1.4fr_0.8fr] gap-2 border-b border-[var(--border-token)] bg-surface-sunken px-3 py-2 text-[10.5px] font-semibold uppercase tracking-wider text-text-muted">
        <div>Customer</div>
        <div>Offer</div>
        <div>Stage</div>
        <div className="text-right">Value</div>
        <div>Owner · Team</div>
        <div>Next follow-up</div>
        <div className="text-right">Sentiment</div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {leads.length === 0 ? (
          <div className="p-6 text-center text-[12px] text-text-muted">No leads match the filters.</div>
        ) : (
          leads.map((l) => {
            const failing = l.eligibilityFlags.filter((f) => !f.ok).length;
            return (
              <button
                key={l.id}
                onClick={() => onOpen(l)}
                className="grid w-full grid-cols-[2fr_2fr_1fr_1fr_1.2fr_1.4fr_0.8fr] items-center gap-2 border-b border-[var(--border-token)] px-3 py-2 text-left text-[12px] transition-colors hover:bg-surface-sunken/70"
              >
                <div className="min-w-0">
                  <div className="truncate font-semibold text-brand-navy">{l.customerName}</div>
                  <div className="text-[10.5px] text-text-muted">#{l.accountTail} · {l.id}</div>
                </div>
                <div className="min-w-0">
                  <div className="truncate text-brand-navy">{l.offer.label}</div>
                  <div className="text-[10.5px] text-text-muted">{SOURCE_LABELS[l.source]} · {l.offer.indicativeROI}</div>
                </div>
                <div>
                  <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-[10.5px] font-medium", stageTone[l.stage])}>
                    {STAGE_LABELS[l.stage]}
                  </span>
                </div>
                <div className="text-right tabular-nums">
                  <div className="font-semibold text-brand-navy">
                    {fmtMoney(l.stage === "won" ? l.wonAmount ?? l.estimatedValue : l.estimatedValue)}
                  </div>
                  {failing > 0 ? (
                    <div className="inline-flex items-center gap-1 text-[10.5px] text-amber-700">
                      <ShieldAlert className="h-3 w-3" /> {failing} flag{failing > 1 ? "s" : ""}
                    </div>
                  ) : (
                    <div className="inline-flex items-center gap-1 text-[10.5px] text-emerald-700">
                      <ShieldCheck className="h-3 w-3" /> Eligible
                    </div>
                  )}
                </div>
                <div className="min-w-0">
                  <div className={cn("truncate", l.owner === "Unassigned" ? "italic text-text-muted" : "text-brand-navy")}>
                    {l.owner}
                  </div>
                  <div className="text-[10.5px] text-text-muted">{l.team}</div>
                </div>
                <div className="min-w-0 text-text-secondary">
                  {l.nextFollowUpAt ? (
                    <span className="inline-flex items-center gap-1">
                      <CalendarClock className="h-3 w-3 text-text-muted" />
                      {fmtDateTime(l.nextFollowUpAt)}
                      <span className="text-text-muted">({fmtRelative(l.nextFollowUpAt)})</span>
                    </span>
                  ) : (
                    <span className="text-text-muted">—</span>
                  )}
                </div>
                <div className="flex items-center justify-end gap-1.5">
                  <span className={cn("h-1.5 w-1.5 rounded-full", sentimentDot[l.sentimentAtCapture])} aria-hidden />
                  <span className="capitalize text-text-secondary">{l.sentimentAtCapture}</span>
                </div>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
