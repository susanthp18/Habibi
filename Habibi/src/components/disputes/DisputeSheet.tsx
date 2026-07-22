import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { toast } from "sonner";
import {
  X,
  Bot,
  User,
  Mic,
  MessageSquare,
  Paperclip,
  CheckCircle2,
  XCircle,
  ArrowRight,
  Send,
  FileText,
  Receipt,
  Image as ImageIcon,
  Music,
  ExternalLink,
} from "lucide-react";
import {
  RESOLUTION_LABELS,
  SOURCE_LABELS,
  STATUS_LABELS,
  STATUS_ORDER,
  TYPE_LABELS,
  fmtDate,
  fmtMoney,
  slaInfo,
  type Dispute,
  type DisputeStatus,
  type Evidence,
  type ResolutionCode,
} from "@/data/disputes-seed";
import {
  addNote,
  assignDispute,
  attachEvidence,
  moveDispute,
  rejectDispute,
  resolveDispute,
} from "@/api/disputes";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { SlaChip } from "./SlaChip";

interface Props {
  dispute: Dispute;
  onClose: () => void;
  onMutate: () => void;
  /** Live: real people from the /staff roster. Mock: derived from seed rows. */
  assignees: string[];
}

type Tab = "details" | "evidence" | "timeline" | "resolution";

function evIcon(kind: Evidence["kind"]) {
  if (kind === "receipt") return Receipt;
  if (kind === "screenshot") return ImageIcon;
  if (kind === "statement") return FileText;
  if (kind === "audio") return Music;
  return FileText;
}

export function DisputeSheet({ dispute: d, onClose, onMutate, assignees }: Props) {
  const [tab, setTab] = useState<Tab>("details");
  const [note, setNote] = useState("");
  const [evName, setEvName] = useState("");
  const [resolutionCode, setResolutionCode] = useState<ResolutionCode>("valid_reverse_charge");
  const [resolutionNotes, setResolutionNotes] = useState("");
  const [rejectNotes, setRejectNotes] = useState("");
  const [showReject, setShowReject] = useState(false);
  const [busy, setBusy] = useState(false);

  const sla = slaInfo(d);
  const closed = d.status === "resolved" || d.status === "rejected";

  const run = async (fn: () => Promise<void>, okMsg: string, opts?: { warn?: string }) => {
    if (busy) return;
    setBusy(true);
    try {
      await fn();
      toast.success(okMsg);
      if (opts?.warn) toast.message(opts.warn);
      onMutate();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  };

  const handleMove = (next: DisputeStatus) => {
    void run(() => moveDispute(d, next), `Moved to ${STATUS_LABELS[next]}`);
  };
  const handleAssign = (a: string) => {
    void run(() => assignDispute(d, a), `Assigned to ${a}`);
  };
  const handleAddNote = () => {
    if (!note.trim()) return;
    void run(
      async () => {
        await addNote(d, note);
        setNote("");
      },
      "Note added",
    );
  };
  const handleAttach = () => {
    const name = evName.trim() || `evidence-${Date.now()}.pdf`;
    void run(
      async () => {
        await attachEvidence(d, name);
        setEvName("");
      },
      "Evidence attached",
    );
  };
  const handleResolve = () => {
    if (!resolutionNotes.trim()) {
      toast.error("Resolution notes are required");
      return;
    }
    void run(
      () => resolveDispute(d, resolutionCode, resolutionNotes.trim()),
      "Resolved · written back to CRM",
    );
  };
  const handleReject = () => {
    if (!rejectNotes.trim()) {
      toast.error("Reason is required to reject");
      return;
    }
    void run(
      async () => {
        await rejectDispute(d, rejectNotes.trim());
        setShowReject(false);
      },
      "Dispute rejected",
    );
  };

  const SIcon = d.source === "bot_voice" ? Mic : d.source === "bot_chat" ? MessageSquare : User;
  const assigneeOptions = [...new Set(["Unassigned", ...assignees])];

  return (
    <div className="fixed inset-0 z-40 flex">
      <button aria-label="Close overlay" onClick={onClose} className="flex-1 bg-black/30" />
      <aside className="flex h-full w-full max-w-[540px] flex-col bg-surface-card shadow-xl">
        {/* Header */}
        <div className="shrink-0 border-b border-[var(--border-token)] px-4 py-3">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <Link
                  to="/customers/$customerId"
                  params={{ customerId: d.customerId }}
                  className="truncate text-[15px] font-semibold text-brand-navy hover:underline"
                >
                  {d.customerName}
                </Link>
                <span className="text-[11px] text-text-muted">#{d.accountTail} · {d.id}</span>
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                <span className="rounded bg-surface-sunken px-1.5 py-0.5 text-[11px] font-medium text-text-secondary">
                  {TYPE_LABELS[d.type]}
                </span>
                <span className="rounded bg-brand-tint px-1.5 py-0.5 text-[11px] font-semibold text-brand-primary-dark tabular-nums">
                  {fmtMoney(d.disputedAmount)}
                </span>
                <span className="rounded bg-surface-sunken px-1.5 py-0.5 text-[11px] text-text-secondary">
                  {STATUS_LABELS[d.status]}
                </span>
                <SlaChip tone={sla.tone} label={sla.label} />
              </div>
            </div>
            <Button size="icon" variant="ghost" className="h-7 w-7" onClick={onClose} aria-label="Close">
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {/* Captured context */}
        <div className="shrink-0 border-b border-[var(--border-token)] bg-surface-sunken/60 px-4 py-3">
          <div className="flex items-center gap-2 text-[11px] text-text-secondary">
            {d.source.startsWith("bot") ? <Bot className="h-3.5 w-3.5" /> : <User className="h-3.5 w-3.5" />}
            <SIcon className="h-3.5 w-3.5" />
            <span>{SOURCE_LABELS[d.source]}</span>
            <span>·</span>
            <span>{fmtDate(d.capturedAt, { dateStyle: "medium", timeStyle: "short" })}</span>
            {d.originConversationId && (
              <Link to="/inbox" className="ml-auto inline-flex items-center gap-1 text-brand-primary hover:underline">
                Open conversation <ExternalLink className="h-3 w-3" />
              </Link>
            )}
          </div>
          <p className="mt-2 rounded border border-[var(--border-token)] bg-surface-card px-2.5 py-2 text-[12px] italic text-text-primary">
            “{d.transcriptSnippet}”
          </p>
        </div>

        {/* Tabs */}
        <div className="shrink-0 border-b border-[var(--border-token)] px-2">
          <div className="flex gap-1">
            {(["details", "evidence", "timeline", "resolution"] as Tab[]).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={cn(
                  "border-b-2 px-3 py-2 text-[12px] capitalize",
                  tab === t
                    ? "border-brand-primary text-brand-primary-dark font-semibold"
                    : "border-transparent text-text-secondary hover:text-brand-navy",
                )}
              >
                {t}
                {t === "evidence" && d.evidence.length > 0 && (
                  <span className="ml-1 rounded bg-surface-sunken px-1 text-[10px] text-text-muted">{d.evidence.length}</span>
                )}
              </button>
            ))}
          </div>
        </div>

        {/* Body */}
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
          {tab === "details" && (
            <div className="space-y-3">
              <Field label="Assignee">
                <select
                  value={d.assignee}
                  onChange={(e) => handleAssign(e.target.value)}
                  disabled={busy}
                  className="h-8 w-full rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
                >
                  {assigneeOptions.map((a) => (
                    <option key={a} value={a}>
                      {a}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Status">
                <div className="flex flex-wrap gap-1.5">
                  {STATUS_ORDER.map((s) => (
                    <button
                      key={s}
                      onClick={() => handleMove(s)}
                      disabled={busy}
                      className={cn(
                        "rounded-full border px-2 py-1 text-[11px]",
                        d.status === s
                          ? "border-brand-primary bg-brand-tint text-brand-primary-dark font-semibold"
                          : "border-[var(--border-token)] bg-surface-card text-text-secondary hover:bg-surface-sunken",
                      )}
                    >
                      {STATUS_LABELS[s]}
                    </button>
                  ))}
                </div>
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Priority">
                  <div className="text-[13px] capitalize text-brand-navy">{d.priority}</div>
                </Field>
                <Field label="Account">
                  <div className="text-[13px] text-brand-navy">{d.accountId}</div>
                </Field>
                <Field label="Captured">
                  <div className="text-[13px] text-brand-navy">
                    {fmtDate(d.capturedAt, { dateStyle: "medium", timeStyle: "short" })}
                  </div>
                </Field>
                <Field label="SLA due">
                  <div className="text-[13px] text-brand-navy">
                    {fmtDate(d.slaDueAt, { dateStyle: "medium", timeStyle: "short" })}
                  </div>
                </Field>
              </div>

              <div className="rounded-md border border-[var(--border-token)] bg-surface-sunken/40 p-2.5">
                <div className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">Add note</div>
                <Textarea
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="Log context, next steps, or customer contact attempts…"
                  className="mt-1 min-h-[70px] text-[12px]"
                />
                <div className="mt-2 flex justify-end">
                  <Button size="sm" className="h-7 text-[11px]" onClick={handleAddNote} disabled={busy}>
                    <Send className="mr-1 h-3 w-3" /> Log note
                  </Button>
                </div>
              </div>
            </div>
          )}

          {tab === "evidence" && (
            <div className="space-y-3">
              <div className="rounded-md border border-dashed border-[var(--border-token)] p-3">
                <div className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">Attach evidence</div>
                <div className="mt-2 flex gap-2">
                  <Input
                    value={evName}
                    onChange={(e) => setEvName(e.target.value)}
                    placeholder="e.g. payment-receipt.pdf"
                    className="h-8 text-[12px]"
                  />
                  <Button size="sm" className="h-8 text-[12px]" onClick={handleAttach} disabled={busy}>
                    <Paperclip className="mr-1 h-3.5 w-3.5" /> Attach
                  </Button>
                </div>
                <div className="mt-1 text-[10.5px] text-text-muted">Simulated upload · files logged with actor and timestamp.</div>
              </div>

              {d.evidence.length === 0 ? (
                <div className="rounded border border-dashed border-[var(--border-token)] p-6 text-center text-[12px] text-text-muted">
                  No evidence attached yet.
                </div>
              ) : (
                <ul className="space-y-1.5">
                  {d.evidence.map((e) => {
                    const Icon = evIcon(e.kind);
                    return (
                      <li key={e.id} className="flex items-center gap-2 rounded-md border border-[var(--border-token)] bg-surface-card px-2.5 py-2">
                        <Icon className="h-4 w-4 text-text-secondary" />
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-[12.5px] text-brand-navy">{e.name}</div>
                          <div className="text-[10.5px] text-text-muted">
                            {e.uploadedBy} · {fmtDate(e.uploadedAt, { dateStyle: "medium", timeStyle: "short" })}
                          </div>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          )}

          {tab === "timeline" && (
            <ol className="relative space-y-3 border-l border-[var(--border-token)] pl-4">
              {[...d.events].reverse().map((e, i) => (
                <li key={i} className="relative">
                  <span
                    className={cn(
                      "absolute -left-[21px] top-1 h-2.5 w-2.5 rounded-full ring-2 ring-surface-card",
                      e.tone === "success"
                        ? "bg-emerald-500"
                        : e.tone === "warn"
                          ? "bg-amber-500"
                          : e.tone === "danger"
                            ? "bg-red-500"
                            : "bg-brand-primary",
                    )}
                  />
                  <div className="text-[12.5px] text-brand-navy">{e.label}</div>
                  <div className="text-[10.5px] text-text-muted">
                    {e.actor ? `${e.actor} · ` : ""}
                    {fmtDate(e.at, { dateStyle: "medium", timeStyle: "short" })}
                  </div>
                </li>
              ))}
            </ol>
          )}

          {tab === "resolution" && (
            <div className="space-y-3">
              {closed ? (
                <div className="rounded-md border border-[var(--border-token)] bg-surface-sunken/50 p-3">
                  <div className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                    {d.status === "resolved" ? "Resolved" : "Rejected"}
                  </div>
                  {d.resolutionCode && (
                    <div className="mt-1 text-[13px] font-semibold text-brand-navy">
                      {RESOLUTION_LABELS[d.resolutionCode]}
                    </div>
                  )}
                  <div className="mt-1 text-[12px] text-text-primary">{d.resolutionNotes}</div>
                </div>
              ) : (
                <>
                  <Field label="Resolution code">
                    <select
                      value={resolutionCode}
                      onChange={(e) => setResolutionCode(e.target.value as ResolutionCode)}
                      className="h-8 w-full rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
                    >
                      {(Object.keys(RESOLUTION_LABELS) as ResolutionCode[]).map((k) => (
                        <option key={k} value={k}>
                          {RESOLUTION_LABELS[k]}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label="Resolution notes">
                    <Textarea
                      value={resolutionNotes}
                      onChange={(e) => setResolutionNotes(e.target.value)}
                      placeholder="Summary of investigation and outcome — written back to CRM."
                      className="min-h-[90px] text-[12px]"
                    />
                  </Field>
                  <div className="flex justify-end gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-8 text-[12px] text-red-700"
                      onClick={() => setShowReject((s) => !s)}
                      disabled={busy}
                    >
                      <XCircle className="mr-1 h-3.5 w-3.5" /> Reject instead
                    </Button>
                    <Button size="sm" className="h-8 text-[12px]" onClick={handleResolve} disabled={busy}>
                      <CheckCircle2 className="mr-1 h-3.5 w-3.5" /> Resolve & writeback
                    </Button>
                  </div>

                  {showReject && (
                    <div className="rounded-md border border-red-200 bg-red-50/60 p-3">
                      <div className="text-[11px] font-semibold uppercase tracking-wider text-red-700">Reject reason</div>
                      <Textarea
                        value={rejectNotes}
                        onChange={(e) => setRejectNotes(e.target.value)}
                        placeholder="Why is this dispute invalid?"
                        className="mt-1 min-h-[70px] text-[12px]"
                      />
                      <div className="mt-2 flex justify-end">
                        <Button size="sm" variant="destructive" className="h-7 text-[11px]" onClick={handleReject} disabled={busy}>
                          Confirm reject
                        </Button>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        {!closed && (
          <div className="shrink-0 border-t border-[var(--border-token)] px-4 py-2">
            <div className="flex items-center gap-2">
              <span className="text-[11px] text-text-muted">Move to</span>
              <div className="flex flex-wrap gap-1">
                {STATUS_ORDER.filter((s) => s !== d.status && s !== "resolved" && s !== "rejected").map((s) => (
                  <Button
                    key={s}
                    size="sm"
                    variant="outline"
                    className="h-7 text-[11px]"
                    onClick={() => handleMove(s)}
                    disabled={busy}
                  >
                    {STATUS_LABELS[s]} <ArrowRight className="ml-1 h-3 w-3" />
                  </Button>
                ))}
              </div>
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">{label}</div>
      {children}
    </div>
  );
}
