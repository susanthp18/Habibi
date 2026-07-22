import { useMemo, useState } from "react";
import { Link } from "@tanstack/react-router";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  X,
  ExternalLink,
  CheckCircle2,
  XCircle,
  ShieldCheck,
  ShieldAlert,
  CalendarClock,
  Send,
  Phone,
  Mail,
  MessageSquare,
  ArrowRight,
  Trophy,
} from "lucide-react";
import {
  STAGE_LABELS,
  STAGE_ORDER,
  SOURCE_LABELS,
  TEAM_OPTIONS,
  fmtDateTime,
  fmtMoney,
  fmtRelative,
  listOwners,
  products,
  type FollowUpChannel,
  type Lead,
  type LeadStage,
  type Priority,
} from "@/data/upsell-seed";
import { addLeadFollowUp, markLeadFollowUpDone, patchLead } from "@/api/upsell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

interface Props {
  lead: Lead;
  onClose: () => void;
  onMutate: () => void;
}

type Tab = "overview" | "eligibility" | "followups" | "timeline";

const stageTone: Record<LeadStage, string> = {
  interested: "bg-brand-tint text-brand-primary-dark",
  contacted: "bg-indigo-100 text-indigo-700",
  qualified: "bg-amber-100 text-amber-700",
  won: "bg-emerald-100 text-emerald-700",
  lost: "bg-slate-200 text-slate-700",
};

const priorityTone: Record<Priority, string> = {
  high: "border-amber-500 bg-amber-50 text-amber-700",
  normal: "border-brand-primary bg-brand-tint text-brand-primary-dark",
  low: "border-slate-300 bg-slate-50 text-slate-700",
};

export function LeadSheet({ lead, onClose, onMutate }: Props) {
  const [tab, setTab] = useState<Tab>("overview");
  const owners = listOwners();

  const [productId, setProductId] = useState(lead.offer.productId);
  const [amount, setAmount] = useState(String(lead.offer.indicativeAmount));
  const [roi, setRoi] = useState(lead.offer.indicativeROI);

  const [wonOpen, setWonOpen] = useState(false);
  const [wonAmt, setWonAmt] = useState(String(lead.estimatedValue));
  const [lostOpen, setLostOpen] = useState(false);
  const [lossReason, setLossReason] = useState("");

  // Follow-up form
  const [fuDate, setFuDate] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    d.setMinutes(0, 0, 0);
    return d.toISOString().slice(0, 16);
  });
  const [fuChannel, setFuChannel] = useState<FollowUpChannel>("voice");
  const [fuNote, setFuNote] = useState("");

  const failing = useMemo(() => lead.eligibilityFlags.filter((f) => !f.ok), [lead]);
  const leadMutation = useMutation({
    mutationFn: (patch: Parameters<typeof patchLead>[1]) => patchLead(lead, patch),
    onSuccess: () => onMutate(),
    onError: (error) => toast.error(error instanceof Error ? error.message : "Lead update failed"),
  });
  const followUpMutation = useMutation({
    mutationFn: (input: { at: string; channel: FollowUpChannel; note: string }) => addLeadFollowUp(lead, input),
    onSuccess: () => onMutate(),
    onError: (error) => toast.error(error instanceof Error ? error.message : "Follow-up scheduling failed"),
  });
  const followUpDoneMutation = useMutation({
    mutationFn: ({ followUp, index }: { followUp: Lead["followUps"][number]; index: number }) => markLeadFollowUpDone(lead, followUp, index),
    onSuccess: () => onMutate(),
    onError: (error) => toast.error(error instanceof Error ? error.message : "Follow-up update failed"),
  });

  const doStage = (s: LeadStage) => {
    if (s === "won") {
      setWonOpen(true);
      return;
    }
    if (s === "lost") {
      setLostOpen(true);
      return;
    }
    leadMutation.mutate({ stage: s }, { onSuccess: () => toast.success(`Moved to ${STAGE_LABELS[s]}`) });
  };

  const saveOffer = () => {
    const n = Number(amount);
    if (!n || n <= 0) {
      toast.error("Enter a valid amount");
      return;
    }
    leadMutation.mutate({ offer: { productId, indicativeAmount: n, indicativeROI: roi } }, { onSuccess: () => toast.success("Offer updated") });
  };

  const submitFollowUp = () => {
    if (!fuDate) return;
    followUpMutation.mutate(
      { at: new Date(fuDate).toISOString(), channel: fuChannel, note: fuNote || "Follow-up scheduled." },
      {
        onSuccess: () => {
          setFuNote("");
          toast.success("Follow-up scheduled");
        },
      },
    );
  };

  const submitWon = () => {
    const n = Number(wonAmt);
    if (!n || n <= 0) {
      toast.error("Enter disbursed amount");
      return;
    }
    leadMutation.mutate({ stage: "won", wonAmount: n });
    setWonOpen(false);
    toast.success(`Marked won · ${fmtMoney(n)}`);
  };

  const submitLost = () => {
    if (!lossReason.trim()) {
      toast.error("Reason required");
      return;
    }
    leadMutation.mutate({ stage: "lost", lossReason: lossReason.trim() });
    setLostOpen(false);
    toast(`Marked lost`);
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex h-full w-full max-w-[560px] flex-col bg-surface-card shadow-2xl"
      >
        {/* Header */}
        <div className="shrink-0 border-b border-[var(--border-token)] p-4">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className={cn("rounded-full px-2 py-0.5 text-[10.5px] font-medium", stageTone[lead.stage])}>
                  {STAGE_LABELS[lead.stage]}
                </span>
                <span className="text-[11px] text-text-muted">{lead.id}</span>
              </div>
              <h2 className="mt-1 truncate text-[16px] font-semibold text-brand-navy">{lead.customerName}</h2>
              <div className="text-[11.5px] text-text-secondary">
                {lead.offer.label} · {fmtMoney(lead.estimatedValue)} · {lead.offer.indicativeROI}
              </div>
            </div>
            <button onClick={onClose} className="rounded p-1 text-text-muted hover:bg-surface-sunken">
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="mt-3 flex items-center gap-2 text-[11.5px]">
            <Link
              to="/customers/$customerId"
              params={{ customerId: lead.customerId }}
              className="inline-flex items-center gap-1 text-brand-primary hover:underline"
            >
              Open Customer 360 <ExternalLink className="h-3 w-3" />
            </Link>
            <span className="text-text-muted">·</span>
            <span className="text-text-secondary">#{lead.accountTail}</span>
            <span className="text-text-muted">·</span>
            <span className="text-text-secondary">Captured {fmtRelative(lead.capturedAt)}</span>
          </div>
        </div>

        {/* Tabs */}
        <div className="shrink-0 border-b border-[var(--border-token)]">
          <div className="flex gap-1 px-3 py-1.5">
            {(["overview", "eligibility", "followups", "timeline"] as Tab[]).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={cn(
                  "rounded px-2.5 py-1 text-[12px] capitalize",
                  tab === t ? "bg-brand-tint text-brand-primary-dark" : "text-text-secondary hover:bg-surface-sunken",
                )}
              >
                {t === "followups" ? "Follow-ups" : t}
              </button>
            ))}
          </div>
        </div>

        {/* Body */}
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {tab === "overview" && (
            <div className="space-y-4">
              {/* Stage stepper */}
              <div>
                <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-text-muted">Stage</div>
                <div className="flex items-center gap-1">
                  {STAGE_ORDER.map((s) => (
                    <button
                      key={s}
                      onClick={() => doStage(s)}
                      disabled={s === lead.stage}
                      className={cn(
                        "flex-1 rounded px-2 py-1.5 text-[11.5px] transition-colors",
                        s === lead.stage
                          ? cn(stageTone[s], "cursor-default font-semibold")
                          : "border border-[var(--border-token)] bg-surface-card text-text-secondary hover:bg-surface-sunken",
                      )}
                    >
                      {STAGE_LABELS[s]}
                    </button>
                  ))}
                </div>
              </div>

              {/* Source + snippet */}
              <div className="rounded-md border border-[var(--border-token)] bg-surface-sunken/50 p-3">
                <div className="flex items-center justify-between text-[11px] text-text-muted">
                  <span>Source · {SOURCE_LABELS[lead.source]}{lead.sourceCallId ? ` · ${lead.sourceCallId}` : ""}</span>
                  <span className="capitalize">Sentiment: {lead.sentimentAtCapture} ({Math.round(lead.sentimentScore * 100)}%)</span>
                </div>
                <p className="mt-1.5 text-[12.5px] italic text-text-secondary">“{lead.transcriptSnippet}”</p>
              </div>

              {/* Offer editor */}
              <div>
                <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-text-muted">Offer</div>
                <div className="grid grid-cols-2 gap-2">
                  <select
                    value={productId}
                    onChange={(e) => {
                      setProductId(e.target.value);
                      const p = products.find((x) => x.id === e.target.value);
                      if (p) setRoi(p.indicativeROI);
                    }}
                    className="col-span-2 h-8 rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
                  >
                    {products.map((p) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                  <Input value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="Indicative amount" className="h-8 text-[12px]" />
                  <Input value={roi} onChange={(e) => setRoi(e.target.value)} placeholder="Indicative ROI" className="h-8 text-[12px]" />
                </div>
                <Button size="sm" className="mt-2 h-7 text-[11.5px]" onClick={saveOffer}>
                  Save offer
                </Button>
              </div>

              {/* Owner + team + priority */}
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">Owner</div>
                  <select
                    value={lead.owner}
                    onChange={(e) => {
                      leadMutation.mutate({ owner: e.target.value });
                      toast.success(`Assigned to ${e.target.value}`);
                    }}
                    className="h-8 w-full rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
                  >
                    {owners.map((o) => (
                      <option key={o} value={o}>{o}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">Team</div>
                  <select
                    value={lead.team}
                    onChange={(e) => {
                      leadMutation.mutate({ team: e.target.value as (typeof TEAM_OPTIONS)[number] });
                      toast.success(`Routed to ${e.target.value}`);
                    }}
                    className="h-8 w-full rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
                  >
                    {TEAM_OPTIONS.map((t) => (
                      <option key={t} value={t}>{t}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">Priority</div>
                <div className="flex items-center gap-1">
                  {(["high", "normal", "low"] as Priority[]).map((p) => (
                    <span
                      key={p}
                      className={cn(
                        "rounded-full border px-2 py-0.5 text-[11px] capitalize",
                        lead.priority === p ? priorityTone[p] : "border-[var(--border-token)] text-text-muted",
                      )}
                    >
                      {p}
                    </span>
                  ))}
                </div>
              </div>

              {lead.stage === "won" && lead.wonAmount && (
                <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-[12px] text-emerald-800">
                  <div className="flex items-center gap-1.5 font-semibold">
                    <Trophy className="h-4 w-4" /> Won · {fmtMoney(lead.wonAmount)}
                  </div>
                  <div className="mt-0.5 text-[11px] text-emerald-700">Closed {lead.closedAt ? fmtRelative(lead.closedAt) : ""}.</div>
                </div>
              )}
              {lead.stage === "lost" && lead.lossReason && (
                <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-[12px] text-slate-700">
                  <div className="font-semibold">Lost</div>
                  <div className="mt-0.5 text-[11.5px]">{lead.lossReason}</div>
                </div>
              )}
            </div>
          )}

          {tab === "eligibility" && (
            <div className="space-y-2">
              <div className="rounded-md border border-[var(--border-token)] bg-surface-sunken/50 p-3 text-[11.5px] text-text-secondary">
                {failing.length === 0 ? (
                  <span className="inline-flex items-center gap-1 text-emerald-700">
                    <ShieldCheck className="h-4 w-4" /> All eligibility checks passed.
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-amber-700">
                    <ShieldAlert className="h-4 w-4" /> {failing.length} flag{failing.length > 1 ? "s" : ""} needs review before disbursement.
                  </span>
                )}
              </div>
              {lead.eligibilityFlags.map((f, i) => (
                <div
                  key={i}
                  className={cn(
                    "flex items-start gap-2 rounded-md border p-2.5",
                    f.ok ? "border-emerald-200 bg-emerald-50/40" : "border-amber-300 bg-amber-50/50",
                  )}
                >
                  {f.ok ? (
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                  ) : (
                    <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                  )}
                  <div>
                    <div className="text-[12.5px] font-medium text-brand-navy">{f.label}</div>
                    <div className="text-[11px] text-text-secondary">{f.detail}</div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {tab === "followups" && (
            <div className="space-y-4">
              <div className="rounded-md border border-[var(--border-token)] p-3">
                <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-text-muted">Schedule follow-up</div>
                <div className="grid grid-cols-2 gap-2">
                  <input
                    type="datetime-local"
                    value={fuDate}
                    onChange={(e) => setFuDate(e.target.value)}
                    className="h-8 rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
                  />
                  <select
                    value={fuChannel}
                    onChange={(e) => setFuChannel(e.target.value as FollowUpChannel)}
                    className="h-8 rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
                  >
                    <option value="voice">Voice</option>
                    <option value="whatsapp">WhatsApp</option>
                    <option value="email">Email</option>
                    <option value="sms">SMS</option>
                  </select>
                </div>
                <Textarea
                  value={fuNote}
                  onChange={(e) => setFuNote(e.target.value)}
                  rows={2}
                  placeholder="Talking points, docs to send, etc."
                  className="mt-2 text-[12px]"
                />
                <Button size="sm" className="mt-2 h-7 text-[11.5px]" onClick={submitFollowUp}>
                  <Send className="mr-1 h-3 w-3" /> Schedule
                </Button>
              </div>

              <div>
                <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-text-muted">History</div>
                {lead.followUps.length === 0 ? (
                  <div className="rounded border border-dashed border-[var(--border-token)] p-4 text-center text-[11.5px] text-text-muted">
                    No follow-ups yet.
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    {lead.followUps.map((f, i) => {
                      const Icon = f.channel === "voice" ? Phone : f.channel === "email" ? Mail : f.channel === "sms" ? MessageSquare : MessageSquare;
                      return (
                        <div
                          key={i}
                          className={cn(
                            "flex items-center gap-2 rounded-md border p-2 text-[11.5px]",
                            f.done ? "border-emerald-200 bg-emerald-50/40 text-emerald-800" : "border-[var(--border-token)] bg-surface-card",
                          )}
                        >
                          <Icon className="h-3.5 w-3.5 text-text-muted" />
                          <div className="flex-1">
                            <div className={cn(f.done && "line-through opacity-70")}>
                              {fmtDateTime(f.at)} <span className="text-text-muted">· {f.channel}</span>
                            </div>
                            {f.note && <div className="text-text-secondary">{f.note}</div>}
                          </div>
                          {!f.done && (
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-6 px-2 text-[10.5px] text-brand-primary"
                              onClick={() => {
                                followUpDoneMutation.mutate({ followUp: f, index: i });
                                toast.success("Follow-up marked done");
                              }}
                            >
                              Mark done
                            </Button>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          )}

          {tab === "timeline" && (
            <div className="space-y-2">
              {lead.events.map((e, i) => (
                <div key={i} className="flex items-start gap-2 rounded-md border border-[var(--border-token)] bg-surface-card p-2.5">
                  <div className="mt-1 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-brand-tint">
                    <CalendarClock className="h-3 w-3 text-brand-primary-dark" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2 text-[11.5px]">
                      <span className="font-medium text-brand-navy capitalize">{e.kind.replace(/_/g, " ")}</span>
                      <span className="text-text-muted">{fmtRelative(e.at)}</span>
                    </div>
                    {e.note && <div className="text-[11.5px] text-text-secondary">{e.note}</div>}
                    <div className="text-[10.5px] text-text-muted">by {e.by}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="shrink-0 border-t border-[var(--border-token)] bg-surface-sunken/40 p-3">
          {wonOpen ? (
            <div className="flex items-end gap-2">
              <div className="flex-1">
                <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wider text-text-muted">Disbursed amount</div>
                <Input value={wonAmt} onChange={(e) => setWonAmt(e.target.value)} className="h-8 text-[12px]" />
              </div>
              <Button size="sm" className="h-8 bg-emerald-600 text-white hover:bg-emerald-700" onClick={submitWon}>
                Confirm won
              </Button>
              <Button size="sm" variant="ghost" className="h-8" onClick={() => setWonOpen(false)}>
                Cancel
              </Button>
            </div>
          ) : lostOpen ? (
            <div className="flex items-end gap-2">
              <div className="flex-1">
                <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wider text-text-muted">Loss reason</div>
                <Input value={lossReason} onChange={(e) => setLossReason(e.target.value)} placeholder="e.g. Rate not competitive" className="h-8 text-[12px]" />
              </div>
              <Button size="sm" className="h-8" onClick={submitLost}>
                Confirm lost
              </Button>
              <Button size="sm" variant="ghost" className="h-8" onClick={() => setLostOpen(false)}>
                Cancel
              </Button>
            </div>
          ) : (
            <div className="flex flex-wrap items-center justify-end gap-2">
              {lead.stage === "interested" && (
                <Button size="sm" className="h-8 text-[12px]" onClick={() => doStage("contacted")}>
                  <ArrowRight className="mr-1 h-3.5 w-3.5" /> Mark contacted
                </Button>
              )}
              {(lead.stage === "interested" || lead.stage === "contacted") && (
                <Button size="sm" variant="outline" className="h-8 text-[12px]" onClick={() => doStage("qualified")}>
                  Mark qualified
                </Button>
              )}
              {lead.stage !== "won" && lead.stage !== "lost" && (
                <>
                  <Button size="sm" className="h-8 bg-emerald-600 text-white text-[12px] hover:bg-emerald-700" onClick={() => setWonOpen(true)}>
                    <Trophy className="mr-1 h-3.5 w-3.5" /> Won
                  </Button>
                  <Button size="sm" variant="outline" className="h-8 text-[12px]" onClick={() => setLostOpen(true)}>
                    Lost
                  </Button>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
