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
    void run(async () => {
      await addNote(d, note);
      setNote("");
    }, "Note added");
  };
  const handleAttach = () => {
    const name = evName.trim() || `evidence-${Date.now()}.pdf`;
    void run(async () => {
      await attachEvidence(d, name);
      setEvName("");
    }, "Evidence attached");
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
    void run(async () => {
      await rejectDispute(d, rejectNotes.trim());
      setShowReject(false);
    }, "Dispute rejected");
  };

  const SIcon = d.source === "bot_voice" ? Mic : d.source === "bot_chat" ? MessageSquare : User;
  const assigneeOptions = [...new Set(["Unassigned", ...assignees])];

  return (
    <div className="fixed inset-0 z-40 flex">
      <button aria-label="Close overlay" onClick={onClose} className="flex-1 bg-black/30" />
      <aside className="flex h-full w-full max-w-[37.5rem] flex-col bg-surface shadow-overlay">
        {/* Header */}
        <div className="shrink-0 border-b border-border px-200 py-150">
          <div className="flex items-start justify-between gap-100">
            <div className="min-w-0">
              <div className="flex items-center gap-100">
                <Link
                  to="/customers/$customerId"
                  params={{ customerId: d.customerId }}
                  className="truncate text-body font-semibold text-text hover:underline"
                >
                  {d.customerName}
                </Link>
                <span className="text-body-small text-text-subtlest">
                  #{d.accountTail} · {d.id}
                </span>
              </div>
              <div className="mt-050 flex flex-wrap items-center gap-075">
                <span className="rounded bg-surface-sunken px-075 py-025 text-body-small font-medium text-text-subtle">
                  {TYPE_LABELS[d.type]}
                </span>
                <span className="rounded bg-background-brand-subtlest px-075 py-025 text-body-small font-semibold text-text-brand tabular-nums">
                  {fmtMoney(d.disputedAmount)}
                </span>
                <span className="rounded bg-surface-sunken px-075 py-025 text-body-small text-text-subtle">
                  {STATUS_LABELS[d.status]}
                </span>
                <SlaChip tone={d.sla} label={d.slaLabel} />
              </div>
            </div>
            <Button
              size="icon"
              variant="ghost"
              className="h-7 w-7"
              onClick={onClose}
              aria-label="Close"
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {/* Captured context */}
        <div className="shrink-0 border-b border-border bg-surface-sunken/60 px-200 py-150">
          <div className="flex items-center gap-100 text-body-small text-text-subtle">
            {d.source.startsWith("bot") ? (
              <Bot className="h-3.5 w-3.5" />
            ) : (
              <User className="h-3.5 w-3.5" />
            )}
            <SIcon className="h-3.5 w-3.5" />
            <span>{SOURCE_LABELS[d.source]}</span>
            <span>·</span>
            <span>{fmtDate(d.capturedAt, { dateStyle: "medium", timeStyle: "short" })}</span>
            {d.originConversationId && (
              <Link
                to="/inbox"
                className="ml-auto inline-flex items-center gap-050 text-text-brand hover:underline"
              >
                Open conversation <ExternalLink className="h-3 w-3" />
              </Link>
            )}
          </div>
          <p className="mt-100 rounded border border-border bg-surface px-150 py-100 text-body-small italic text-text">
            “{d.transcriptSnippet}”
          </p>
        </div>

        {/* Tabs */}
        <div className="shrink-0 border-b border-border px-100">
          <div className="flex gap-050">
            {(["details", "evidence", "timeline", "resolution"] as Tab[]).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={cn(
                  "border-b-2 px-150 py-100 text-body-small capitalize",
                  tab === t
                    ? "border-border-brand text-text-brand font-semibold"
                    : "border-transparent text-text-subtle hover:text-text",
                )}
              >
                {t}
                {t === "evidence" && d.evidence.length > 0 && (
                  <span className="ml-050 rounded bg-surface-sunken px-050 text-body-small text-text-subtlest">
                    {d.evidence.length}
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>

        {/* Body */}
        <div className="min-h-0 flex-1 overflow-y-auto px-200 py-150">
          {tab === "details" && (
            <div className="space-y-150">
              <Field label="Assignee">
                <select
                  value={d.assignee}
                  onChange={(e) => handleAssign(e.target.value)}
                  disabled={busy}
                  className="h-400 w-full rounded-medium border border-border bg-surface px-100 text-body-small"
                >
                  {assigneeOptions.map((a) => (
                    <option key={a} value={a}>
                      {a}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Status">
                <div className="flex flex-wrap gap-075">
                  {STATUS_ORDER.map((s) => (
                    <button
                      key={s}
                      onClick={() => handleMove(s)}
                      disabled={busy}
                      className={cn(
                        "rounded-full border px-100 py-050 text-body-small",
                        d.status === s
                          ? "border-border-brand bg-background-brand-subtlest text-text-brand font-semibold"
                          : "border-border bg-surface text-text-subtle hover:bg-surface-sunken",
                      )}
                    >
                      {STATUS_LABELS[s]}
                    </button>
                  ))}
                </div>
              </Field>
              <div className="grid grid-cols-2 gap-150">
                <Field label="Priority">
                  <div className="text-body capitalize text-text">{d.priority}</div>
                </Field>
                <Field label="Account">
                  <div className="text-body text-text">{d.accountId}</div>
                </Field>
                <Field label="Captured">
                  <div className="text-body text-text">
                    {fmtDate(d.capturedAt, { dateStyle: "medium", timeStyle: "short" })}
                  </div>
                </Field>
                <Field label="SLA due">
                  <div className="text-body text-text">
                    {fmtDate(d.slaDueAt, { dateStyle: "medium", timeStyle: "short" })}
                  </div>
                </Field>
              </div>

              <div className="rounded-medium border border-border bg-surface-sunken/40 p-150">
                <div className="text-body-small font-semibold text-text-subtlest">Add note</div>
                <Textarea
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="Log context, next steps, or customer contact attempts…"
                  className="mt-050 min-h-[4.375rem] text-body-small"
                />
                <div className="mt-100 flex justify-end">
                  <Button
                    size="sm"
                    className="h-7 text-body-small"
                    onClick={handleAddNote}
                    disabled={busy}
                  >
                    <Send className="mr-050 h-3 w-3" /> Log note
                  </Button>
                </div>
              </div>
            </div>
          )}

          {tab === "evidence" && (
            <div className="space-y-150">
              <div className="rounded-medium border border-dashed border-border p-150">
                <div className="text-body-small font-semibold text-text-subtlest">
                  Attach evidence
                </div>
                <div className="mt-100 flex gap-100">
                  <Input
                    value={evName}
                    onChange={(e) => setEvName(e.target.value)}
                    placeholder="e.g. payment-receipt.pdf"
                    className="h-400 text-body-small"
                  />
                  <Button
                    size="sm"
                    className="h-400 text-body-small"
                    onClick={handleAttach}
                    disabled={busy}
                  >
                    <Paperclip className="mr-050 h-3.5 w-3.5" /> Attach
                  </Button>
                </div>
                <div className="mt-050 text-body-small text-text-subtlest">
                  Simulated upload · files logged with actor and timestamp.
                </div>
              </div>

              {d.evidence.length === 0 ? (
                <div className="rounded border border-dashed border-border p-300 text-center text-body-small text-text-subtlest">
                  No evidence attached yet.
                </div>
              ) : (
                <ul className="space-y-075">
                  {d.evidence.map((e) => {
                    const Icon = evIcon(e.kind);
                    return (
                      <li
                        key={e.id}
                        className="flex items-center gap-100 rounded-medium border border-border bg-surface px-150 py-100"
                      >
                        <Icon className="h-4 w-4 text-text-subtle" />
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-body-small text-text">{e.name}</div>
                          <div className="text-body-small text-text-subtlest">
                            {e.uploadedBy} ·{" "}
                            {fmtDate(e.uploadedAt, { dateStyle: "medium", timeStyle: "short" })}
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
            <ol className="relative space-y-150 border-l border-border pl-200">
              {[...d.events].reverse().map((e, i) => (
                <li key={i} className="relative">
                  <span
                    className={cn(
                      "absolute -left-250 top-1 h-2.5 w-2.5 rounded-full ring-2 ring-surface",
                      e.tone === "success"
                        ? "bg-background-success-bold"
                        : e.tone === "warn"
                          ? "bg-background-warning-bold"
                          : e.tone === "danger"
                            ? "bg-background-danger-bold"
                            : "bg-background-brand-bold",
                    )}
                  />
                  <div className="text-body-small text-text">{e.label}</div>
                  <div className="text-body-small text-text-subtlest">
                    {e.actor ? `${e.actor} · ` : ""}
                    {fmtDate(e.at, { dateStyle: "medium", timeStyle: "short" })}
                  </div>
                </li>
              ))}
            </ol>
          )}

          {tab === "resolution" && (
            <div className="space-y-150">
              {closed ? (
                <div className="rounded-medium border border-border bg-surface-sunken/50 p-150">
                  <div className="text-body-small font-semibold text-text-subtlest">
                    {d.status === "resolved" ? "Resolved" : "Rejected"}
                  </div>
                  {d.resolutionCode && (
                    <div className="mt-050 text-body font-semibold text-text">
                      {RESOLUTION_LABELS[d.resolutionCode]}
                    </div>
                  )}
                  <div className="mt-050 text-body-small text-text">{d.resolutionNotes}</div>
                </div>
              ) : (
                <>
                  <Field label="Resolution code">
                    <select
                      value={resolutionCode}
                      onChange={(e) => setResolutionCode(e.target.value as ResolutionCode)}
                      className="h-400 w-full rounded-medium border border-border bg-surface px-100 text-body-small"
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
                      className="min-h-[5.625rem] text-body-small"
                    />
                  </Field>
                  <div className="flex justify-end gap-100">
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-400 text-body-small text-text-danger-bolder"
                      onClick={() => setShowReject((s) => !s)}
                      disabled={busy}
                    >
                      <XCircle className="mr-050 h-3.5 w-3.5" /> Reject instead
                    </Button>
                    <Button
                      size="sm"
                      className="h-400 text-body-small"
                      onClick={handleResolve}
                      disabled={busy}
                    >
                      <CheckCircle2 className="mr-050 h-3.5 w-3.5" /> Resolve & writeback
                    </Button>
                  </div>

                  {showReject && (
                    <div className="rounded-medium border border-border-danger-subtle bg-background-danger-subtler/60 p-150">
                      <div className="text-body-small font-semibold text-text-danger-bolder">
                        Reject reason
                      </div>
                      <Textarea
                        value={rejectNotes}
                        onChange={(e) => setRejectNotes(e.target.value)}
                        placeholder="Why is this dispute invalid?"
                        className="mt-050 min-h-[4.375rem] text-body-small"
                      />
                      <div className="mt-100 flex justify-end">
                        <Button
                          size="sm"
                          variant="destructive"
                          className="h-7 text-body-small"
                          onClick={handleReject}
                          disabled={busy}
                        >
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
          <div className="shrink-0 border-t border-border px-200 py-100">
            <div className="flex items-center gap-100">
              <span className="text-body-small text-text-subtlest">Move to</span>
              <div className="flex flex-wrap gap-050">
                {STATUS_ORDER.filter(
                  (s) => s !== d.status && s !== "resolved" && s !== "rejected",
                ).map((s) => (
                  <Button
                    key={s}
                    size="sm"
                    variant="outline"
                    className="h-7 text-body-small"
                    onClick={() => handleMove(s)}
                    disabled={busy}
                  >
                    {STATUS_LABELS[s]} <ArrowRight className="ml-050 h-3 w-3" />
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
      <div className="mb-050 text-body-small font-semibold text-text-subtlest">{label}</div>
      {children}
    </div>
  );
}
