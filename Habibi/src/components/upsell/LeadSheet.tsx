import { useEffect, useMemo, useState } from "react";
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
import { Lozenge, type LozengeTone } from "@/components/ui/lozenge";
import {
  STAGE_LABELS,
  STAGE_ORDER,
  SOURCE_LABELS,
  TEAM_OPTIONS,
  fmtDateTime,
  fmtMoney,
  fmtRelative,
  fmtSentiment,
  moneyValue,
  listOwners,
  products,
  type FollowUpChannel,
  type Lead,
  type LeadStage,
  type Priority,
} from "@/data/upsell-seed";
import { addLeadFollowUp, leadContactChannel, markLeadFollowUpDone, patchLead, revalidateLead } from "@/api/upsell";
import { useProducts } from "@/api/products";
import { humanNames, useStaff } from "@/api/staff";
import { teamNames, useTeams } from "@/api/teams";
import { USE_MOCK } from "@/api/config";
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

const stageTone: Record<LeadStage, LozengeTone> = {
  interested: "selected",
  contacted: "discovery",
  qualified: "warning",
  won: "success",
  lost: "neutral",
};

const priorityTone: Record<Priority, LozengeTone> = {
  high: "warning",
  normal: "selected",
  low: "neutral",
};

// The stage picker is a segmented control, so its selected leg keeps plain classes —
// see the note in AssignedQueue on why a Lozenge is wrong inside a button.
const stageButtonClass: Record<LeadStage, string> = {
  interested: "bg-background-selected text-text-selected",
  contacted: "bg-background-discovery-subtler text-text-discovery-bolder",
  qualified: "bg-background-warning-subtler text-text-warning-bolder",
  won: "bg-background-success-subtler text-text-success-bolder",
  lost: "bg-background-neutral text-text",
};

export function LeadSheet({ lead, onClose, onMutate }: Props) {
  const [tab, setTab] = useState<Tab>("overview");
  // Live rosters, not the hardcoded seed arrays. Assigning from this drawer
  // called resolveActor(name), which THROWS when the name is not in the DB —
  // so every reassignment in live mode failed on a name only the seed knew.
  const { data: staff = [] } = useStaff();
  const { data: teams = [] } = useTeams();
  const { data: catalog = [] } = useProducts();
  const owners = useMemo(
    () => (USE_MOCK ? listOwners() : [...humanNames(staff), "Unassigned"]),
    [staff],
  );
  const teamOptions = useMemo(
    () => (USE_MOCK ? TEAM_OPTIONS : teamNames(teams)),
    [teams],
  );
  const productOptions = useMemo(
    () => (catalog.length > 0 ? catalog : products),
    [catalog],
  );

  const [productId, setProductId] = useState(lead.offer.productId);
  const [amount, setAmount] = useState(String(lead.offer.indicativeAmount));
  const [roi, setRoi] = useState(lead.offer.indicativeROI);

  const [wonOpen, setWonOpen] = useState(false);
  const [wonAmt, setWonAmt] = useState(String(moneyValue(lead.estimatedValue) || ""));
  const [lostOpen, setLostOpen] = useState(false);
  const [lossReason, setLossReason] = useState("");

  // Follow-up form
  const [fuDate, setFuDate] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    d.setMinutes(0, 0, 0);
    return d.toISOString().slice(0, 16);
  });
  const [fuChannel, setFuChannel] = useState<FollowUpChannel>(() => leadContactChannel(lead.source));
  const [fuNote, setFuNote] = useState("");

  useEffect(() => {
    setFuChannel(leadContactChannel(lead.source));
  }, [lead.id, lead.source]);

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
  // Eligibility was evaluated once, at capture. Consent and DPD move; the
  // badge on this drawer does not, so a rep could work a lead the customer has
  // since opted out of. This re-checks against today's facts before they dial.
  const revalidateMutation = useMutation({
    mutationFn: () => revalidateLead(lead, fuChannel),
    onSuccess: (result) => {
      onMutate();
      if (result.eligible) toast.success("Still eligible");
      else toast.error(`No longer eligible — ${result.blockReason ?? "blocked"}`);
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Re-check failed"),
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
        className="flex h-full w-full max-w-[37.5rem] flex-col bg-surface shadow-overlay"
      >
        {/* Header */}
        <div className="shrink-0 border-b border-border p-200">
          <div className="flex items-start justify-between gap-100">
            <div className="min-w-0">
              <div className="flex items-center gap-100">
                <Lozenge tone={stageTone[lead.stage]}>
                  {STAGE_LABELS[lead.stage]}
                </Lozenge>
                <span className="text-body-small text-text-subtlest">{lead.id}</span>
              </div>
              <h2 className="mt-050 truncate text-[0.875rem] font-semibold text-text">{lead.customerName}</h2>
              <div className="text-body-small text-text-subtle">
                {lead.offer.label} · {fmtMoney(lead.estimatedValue)} · {lead.offer.indicativeROI}
              </div>
            </div>
            <button onClick={onClose} className="rounded p-050 text-text-subtlest hover:bg-surface-sunken">
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="mt-150 flex items-center gap-100 text-body-small">
            <Link
              to="/customers/$customerId"
              params={{ customerId: lead.customerId }}
              className="inline-flex items-center gap-050 text-text-brand hover:underline"
            >
              Open Customer 360 <ExternalLink className="h-3 w-3" />
            </Link>
            <span className="text-text-subtlest">·</span>
            <span className="text-text-subtle">#{lead.accountTail}</span>
            <span className="text-text-subtlest">·</span>
            <span className="text-text-subtle">Captured {fmtRelative(lead.capturedAt)}</span>
          </div>
        </div>

        {/* Tabs */}
        <div className="shrink-0 border-b border-border">
          <div className="flex gap-050 px-150 py-075">
            {(["overview", "eligibility", "followups", "timeline"] as Tab[]).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={cn(
                  "rounded px-150 py-050 text-body-small capitalize",
                  tab === t ? "bg-background-brand-subtlest text-text-brand" : "text-text-subtle hover:bg-surface-sunken",
                )}
              >
                {t === "followups" ? "Follow-ups" : t}
              </button>
            ))}
          </div>
        </div>

        {/* Body */}
        <div className="min-h-0 flex-1 overflow-y-auto p-200">
          {tab === "overview" && (
            <div className="space-y-200">
              {/* Stage stepper */}
              <div>
                <div className="mb-075 text-body-small font-semibold text-text-subtlest">Stage</div>
                <div className="flex items-center gap-050">
                  {STAGE_ORDER.map((s) => (
                    <button
                      key={s}
                      onClick={() => doStage(s)}
                      disabled={s === lead.stage}
                      className={cn(
                        "flex-1 rounded px-100 py-075 text-body-small transition-colors",
                        s === lead.stage
                          ? cn(stageButtonClass[s], "cursor-default font-semibold")
                          : "border border-border bg-surface text-text-subtle hover:bg-surface-sunken",
                      )}
                    >
                      {STAGE_LABELS[s]}
                    </button>
                  ))}
                </div>
              </div>

              {/* Source + snippet */}
              <div className="rounded-medium border border-border bg-surface-sunken/50 p-150">
                <div className="flex items-center justify-between text-body-small text-text-subtlest">
                  <span>Source · {SOURCE_LABELS[lead.source]}{lead.sourceCallId ? ` · ${lead.sourceCallId}` : ""}</span>
                  <span className="capitalize">Sentiment: {lead.sentimentAtCapture} ({fmtSentiment(lead.sentimentScore)})</span>
                </div>
                <p className="mt-075 text-body-small italic text-text-subtle">“{lead.transcriptSnippet}”</p>
              </div>

              {/* Offer editor */}
              <div>
                <div className="mb-075 text-body-small font-semibold text-text-subtlest">Offer</div>
                <div className="grid grid-cols-2 gap-100">
                  <select
                    value={productId}
                    onChange={(e) => {
                      setProductId(e.target.value);
                      const p = productOptions.find((x) => x.id === e.target.value);
                      if (p) setRoi(p.indicativeROI);
                    }}
                    className="col-span-2 h-400 rounded-medium border border-border bg-surface px-100 text-body-small"
                  >
                    {productOptions.map((p) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                  <Input value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="Indicative amount" className="h-400 text-body-small" />
                  <Input value={roi} onChange={(e) => setRoi(e.target.value)} placeholder="Indicative ROI" className="h-400 text-body-small" />
                </div>
                <Button size="sm" className="mt-100 h-7 text-body-small" onClick={saveOffer}>
                  Save offer
                </Button>
              </div>

              {/* Owner + team + priority */}
              <div className="grid grid-cols-2 gap-100">
                <div>
                  <div className="mb-050 text-body-small font-semibold text-text-subtlest">Owner</div>
                  <select
                    value={lead.owner ?? "Unassigned"}
                    onChange={(e) => {
                      leadMutation.mutate({ owner: e.target.value });
                      toast.success(`Assigned to ${e.target.value}`);
                    }}
                    className="h-400 w-full rounded-medium border border-border bg-surface px-100 text-body-small"
                  >
                    {owners.map((o) => (
                      <option key={o} value={o}>{o}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <div className="mb-050 text-body-small font-semibold text-text-subtlest">Team</div>
                  <select
                    value={lead.team ?? ""}
                    onChange={(e) => {
                      leadMutation.mutate({ team: e.target.value as (typeof TEAM_OPTIONS)[number] });
                      toast.success(`Routed to ${e.target.value}`);
                    }}
                    className="h-400 w-full rounded-medium border border-border bg-surface px-100 text-body-small"
                  >
                    {teamOptions.map((t) => (
                      <option key={t} value={t}>{t}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <div className="mb-050 text-body-small font-semibold text-text-subtlest">Priority</div>
                <div className="flex items-center gap-050">
                  {(["high", "normal", "low"] as Priority[]).map((p) => (
                    <Lozenge
                      key={p}
                      tone={lead.priority === p ? priorityTone[p] : "neutral"}
                      className={cn("capitalize", lead.priority !== p && "opacity-60")}
                    >
                      {p}
                    </Lozenge>
                  ))}
                </div>
              </div>

              {lead.stage === "won" && lead.wonAmount && (
                <div className="rounded-medium border border-border-success-subtle bg-background-success-subtler p-150 text-body-small text-text-success-bolder">
                  <div className="flex items-center gap-075 font-semibold">
                    <Trophy className="h-4 w-4" /> Won · {fmtMoney(lead.wonAmount)}
                  </div>
                  <div className="mt-025 text-body-small text-text-success-bolder">Closed {lead.closedAt ? fmtRelative(lead.closedAt) : ""}.</div>
                </div>
              )}
              {lead.stage === "lost" && lead.lossReason && (
                <div className="rounded-medium border border-border-accent-gray-subtle bg-background-accent-gray-subtlest p-150 text-body-small text-text-accent-gray-bolder">
                  <div className="font-semibold">Lost</div>
                  <div className="mt-025 text-body-small">{lead.lossReason}</div>
                </div>
              )}
            </div>
          )}

          {tab === "eligibility" && (
            <div className="space-y-100">
              <div className="flex items-center justify-between gap-100 rounded-medium border border-border bg-surface-sunken/50 p-150 text-body-small text-text-subtle">
                {failing.length === 0 ? (
                  <span className="inline-flex items-center gap-050 text-text-success-bolder">
                    <ShieldCheck className="h-4 w-4" /> All eligibility checks passed.
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-050 text-text-warning-bolder">
                    <ShieldAlert className="h-4 w-4" /> {failing.length} flag{failing.length > 1 ? "s" : ""} needs review before disbursement.
                  </span>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7 shrink-0 text-body-small"
                  disabled={revalidateMutation.isPending}
                  onClick={() => revalidateMutation.mutate()}
                >
                  {revalidateMutation.isPending ? "Re-checking…" : "Re-check now"}
                </Button>
              </div>
              <p className="px-050 text-body-small text-text-subtlest">
                Checked when the lead was captured. Consent and DPD change — re-check before contacting.
              </p>
              {lead.eligibilityFlags.map((f, i) => (
                <div
                  key={i}
                  className={cn(
                    "flex items-start gap-100 rounded-medium border p-150",
                    f.ok ? "border-border-success-subtle bg-background-success-subtler/40" : "border-border-warning bg-background-warning-subtler/50",
                  )}
                >
                  {f.ok ? (
                    <CheckCircle2 className="mt-025 h-4 w-4 shrink-0 text-text-success" />
                  ) : (
                    <XCircle className="mt-025 h-4 w-4 shrink-0 text-text-warning" />
                  )}
                  <div>
                    <div className="text-[0.75rem] font-medium text-text">{f.label}</div>
                    <div className="text-body-small text-text-subtle">{f.detail}</div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {tab === "followups" && (
            <div className="space-y-200">
              <div className="rounded-medium border border-border p-150">
                <div className="mb-100 text-body-small font-semibold text-text-subtlest">Schedule follow-up</div>
                <div className="grid grid-cols-2 gap-100">
                  <input
                    type="datetime-local"
                    value={fuDate}
                    onChange={(e) => setFuDate(e.target.value)}
                    className="h-400 rounded-medium border border-border bg-surface px-100 text-body-small"
                  />
                  <select
                    value={fuChannel}
                    onChange={(e) => setFuChannel(e.target.value as FollowUpChannel)}
                    className="h-400 rounded-medium border border-border bg-surface px-100 text-body-small"
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
                  className="mt-100 text-body-small"
                />
                <Button size="sm" className="mt-100 h-7 text-body-small" onClick={submitFollowUp}>
                  <Send className="mr-050 h-3 w-3" /> Schedule
                </Button>
              </div>

              <div>
                <div className="mb-075 text-body-small font-semibold text-text-subtlest">History</div>
                {lead.followUps.length === 0 ? (
                  <div className="rounded border border-dashed border-border p-200 text-center text-body-small text-text-subtlest">
                    No follow-ups yet.
                  </div>
                ) : (
                  <div className="space-y-075">
                    {lead.followUps.map((f, i) => {
                      const Icon = f.channel === "voice" ? Phone : f.channel === "email" ? Mail : f.channel === "sms" ? MessageSquare : MessageSquare;
                      return (
                        <div
                          key={i}
                          className={cn(
                            "flex items-center gap-100 rounded-medium border p-100 text-body-small",
                            f.done ? "border-border-success-subtle bg-background-success-subtler/40 text-text-success-bolder" : "border-border bg-surface",
                          )}
                        >
                          <Icon className="h-3.5 w-3.5 text-text-subtlest" />
                          <div className="flex-1">
                            <div className={cn(f.done && "line-through opacity-70")}>
                              {fmtDateTime(f.at)} <span className="text-text-subtlest">· {f.channel}</span>
                            </div>
                            {f.note && <div className="text-text-subtle">{f.note}</div>}
                          </div>
                          {!f.done && (
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-300 px-100 text-body-small text-text-brand"
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
            <div className="space-y-100">
              {lead.events.map((e, i) => (
                <div key={i} className="flex items-start gap-100 rounded-medium border border-border bg-surface p-150">
                  <div className="mt-050 grid h-250 w-250 shrink-0 place-items-center rounded-full bg-background-brand-subtlest">
                    <CalendarClock className="h-3 w-3 text-text-brand" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-100 text-body-small">
                      <span className="font-medium text-text capitalize">{e.kind.replace(/_/g, " ")}</span>
                      <span className="text-text-subtlest">{fmtRelative(e.at)}</span>
                    </div>
                    {e.note && <div className="text-body-small text-text-subtle">{e.note}</div>}
                    <div className="text-body-small text-text-subtlest">by {e.by}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="shrink-0 border-t border-border bg-surface-sunken/40 p-150">
          {wonOpen ? (
            <div className="flex items-end gap-100">
              <div className="flex-1">
                <div className="mb-050 text-body-small font-semibold text-text-subtlest">Disbursed amount</div>
                <Input value={wonAmt} onChange={(e) => setWonAmt(e.target.value)} className="h-400 text-body-small" />
              </div>
              <Button size="sm" className="h-400 bg-background-success-bold text-white hover:bg-background-success-bold-pressed" onClick={submitWon}>
                Confirm won
              </Button>
              <Button size="sm" variant="ghost" className="h-400" onClick={() => setWonOpen(false)}>
                Cancel
              </Button>
            </div>
          ) : lostOpen ? (
            <div className="flex items-end gap-100">
              <div className="flex-1">
                <div className="mb-050 text-body-small font-semibold text-text-subtlest">Loss reason</div>
                <Input value={lossReason} onChange={(e) => setLossReason(e.target.value)} placeholder="e.g. Rate not competitive" className="h-400 text-body-small" />
              </div>
              <Button size="sm" className="h-400" onClick={submitLost}>
                Confirm lost
              </Button>
              <Button size="sm" variant="ghost" className="h-400" onClick={() => setLostOpen(false)}>
                Cancel
              </Button>
            </div>
          ) : (
            <div className="flex flex-wrap items-center justify-end gap-100">
              {lead.stage === "interested" && (
                <Button size="sm" className="h-400 text-body-small" onClick={() => doStage("contacted")}>
                  <ArrowRight className="mr-050 h-3.5 w-3.5" /> Mark contacted
                </Button>
              )}
              {(lead.stage === "interested" || lead.stage === "contacted") && (
                <Button size="sm" variant="outline" className="h-400 text-body-small" onClick={() => doStage("qualified")}>
                  Mark qualified
                </Button>
              )}
              {lead.stage !== "won" && lead.stage !== "lost" && (
                <>
                  <Button size="sm" className="h-400 bg-background-success-bold text-white text-body-small hover:bg-background-success-bold-pressed" onClick={() => setWonOpen(true)}>
                    <Trophy className="mr-050 h-3.5 w-3.5" /> Won
                  </Button>
                  <Button size="sm" variant="outline" className="h-400 text-body-small" onClick={() => setLostOpen(true)}>
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
