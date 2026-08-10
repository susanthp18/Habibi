import { CalendarClock, ShieldAlert, ShieldCheck } from "lucide-react";
import {
  fmtDateTime,
  fmtMoney,
  fmtRelative,
  leadValue,
  SOURCE_LABELS,
  STAGE_LABELS,
  type Lead,
  type LeadStage,
  type Sentiment,
} from "@/data/upsell-seed";
import { Lozenge, type LozengeTone } from "@/components/ui/lozenge";
import { cn } from "@/lib/utils";

interface Props {
  leads: Lead[];
  onOpen: (l: Lead) => void;
}

const stageTone: Record<LeadStage, LozengeTone> = {
  interested: "selected",
  contacted: "discovery",
  qualified: "warning",
  won: "success",
  lost: "neutral",
};

const sentimentDot: Record<Sentiment, string> = {
  positive: "bg-background-success-bold",
  neutral: "bg-background-accent-gray-subtle",
  negative: "bg-background-danger-bold",
};

export function LeadTable({ leads, onOpen }: Props) {
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-large border border-border bg-surface">
      <div className="grid shrink-0 grid-cols-[2fr_2fr_1fr_1fr_1.2fr_1.4fr_0.8fr] gap-100 border-b border-border bg-surface-sunken px-150 py-100 text-body-small font-semibold text-text-subtlest">
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
          <div className="p-300 text-center text-body-small text-text-subtlest">No leads match the filters.</div>
        ) : (
          leads.map((l) => {
            const failing = l.eligibilityFlags.filter((f) => !f.ok).length;
            return (
              <button
                key={l.id}
                onClick={() => onOpen(l)}
                className="grid w-full grid-cols-[2fr_2fr_1fr_1fr_1.2fr_1.4fr_0.8fr] items-center gap-100 border-b border-border px-150 py-100 text-left text-body-small transition-colors hover:bg-surface-sunken/70"
              >
                <div className="min-w-0">
                  <div className="truncate font-semibold text-text">{l.customerName}</div>
                  <div className="text-body-small text-text-subtlest">#{l.accountTail} · {l.id}</div>
                </div>
                <div className="min-w-0">
                  <div className="truncate text-text">{l.offer.label}</div>
                  <div className="text-body-small text-text-subtlest">{SOURCE_LABELS[l.source]} · {l.offer.indicativeROI}</div>
                </div>
                <div>
                  <Lozenge tone={stageTone[l.stage]}>
                    {STAGE_LABELS[l.stage]}
                  </Lozenge>
                </div>
                <div className="text-right tabular-nums">
                  <div className="font-semibold text-text">
                    {fmtMoney(leadValue(l))}
                  </div>
                  {failing > 0 ? (
                    <div className="inline-flex items-center gap-050 text-body-small text-text-warning-bolder">
                      <ShieldAlert className="h-3 w-3" /> {failing} flag{failing > 1 ? "s" : ""}
                    </div>
                  ) : (
                    <div className="inline-flex items-center gap-050 text-body-small text-text-success-bolder">
                      <ShieldCheck className="h-3 w-3" /> Eligible
                    </div>
                  )}
                </div>
                <div className="min-w-0">
                  <div className={cn("truncate", !l.owner || l.owner === "Unassigned" ? "italic text-text-subtlest" : "text-text")}>
                    {l.owner || "Unassigned"}
                  </div>
                  <div className="text-body-small text-text-subtlest">{l.team || "Unrouted"}</div>
                </div>
                <div className="min-w-0 text-text-subtle">
                  {l.nextFollowUpAt ? (
                    <span className="inline-flex items-center gap-050">
                      <CalendarClock className="h-3 w-3 text-text-subtlest" />
                      {fmtDateTime(l.nextFollowUpAt)}
                      <span className="text-text-subtlest">({fmtRelative(l.nextFollowUpAt)})</span>
                    </span>
                  ) : (
                    <span className="text-text-subtlest">—</span>
                  )}
                </div>
                <div className="flex items-center justify-end gap-075">
                  <span className={cn("h-1.5 w-1.5 rounded-full", sentimentDot[l.sentimentAtCapture])} aria-hidden />
                  <span className="capitalize text-text-subtle">{l.sentimentAtCapture}</span>
                </div>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
