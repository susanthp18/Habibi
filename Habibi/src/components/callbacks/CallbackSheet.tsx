import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { toast } from "sonner";
import { X, Send, Phone, ExternalLink, AlertTriangle, Bot, User, Mic } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  CHANNEL_LABELS,
  DISPOSITION_LABELS,
  PRIORITY_LABELS,
  REASON_LABELS,
  SOURCE_LABELS,
  STATUS_LABELS,
  STATUS_TONE,
  fmtLongDate,
  isWithinDndWindow,
  nextAllowedSlot,
  type Callback,
  type CbChannel,
  type CbDisposition,
  type CbPriority,
} from "@/data/callbacks-seed";
import {
  assignCallback,
  cancelCallback,
  markCompleted,
  reassignQueue,
  rescheduleCallback,
  sendReminder,
  setPriority,
  startCall,
} from "@/api/callbacks";

type Tab = "details" | "reminders" | "timeline" | "outcome";

const CHANNELS: CbChannel[] = ["whatsapp", "sms", "email"];
const DISPOS: CbDisposition[] = ["reached", "no_answer", "ptp_captured", "not_interested", "callback_again"];
const PRIORITIES: CbPriority[] = ["low", "normal", "high", "urgent"];

function localDateTimeInput(iso: string) {
  const d = new Date(iso);
  const pad = (n: number) => (n < 10 ? `0${n}` : `${n}`);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

interface Props {
  cb: Callback;
  onClose: () => void;
  onMutate: () => void;
  /** Live: real DB humans (+ Unassigned). Mock: seed AGENTS. */
  assignees: string[];
  /** Live: real DB teams. Mock: seed QUEUES. */
  queues: string[];
}

export function CallbackSheet({ cb, onClose, onMutate, assignees, queues }: Props) {
  const [tab, setTab] = useState<Tab>(cb.status === "in_progress" || cb.status === "completed" ? "outcome" : "details");
  const [rescheduleAt, setRescheduleAt] = useState(localDateTimeInput(cb.scheduledAt));
  const [disposition, setDisposition] = useState<CbDisposition>(cb.disposition ?? "reached");
  const [notes, setNotes] = useState(cb.outcomeNotes ?? "");
  const [busy, setBusy] = useState(false);

  const SIcon = cb.source === "bot_voice" ? Mic : cb.source === "bot_chat" ? Bot : User;
  const dndAtCurrent = cb.dndActive;

  const run = async (fn: () => Promise<void>, okMsg: string) => {
    if (busy) return;
    setBusy(true);
    try {
      await fn();
      toast.success(okMsg);
      onMutate();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  };

  const doReschedule = () => {
    const iso = new Date(rescheduleAt).toISOString();
    void run(() => rescheduleCallback(cb, iso), `Rescheduled to ${fmtLongDate(iso)}`);
  };

  const useNextAllowed = () => {
    const iso = nextAllowedSlot(cb, new Date(cb.scheduledAt));
    setRescheduleAt(localDateTimeInput(iso));
    void run(() => rescheduleCallback(cb, iso), `Moved to next DND-safe slot · ${fmtLongDate(iso)}`);
  };

  const doAssign = (a: string) => {
    void run(() => assignCallback(cb, a), `Assigned to ${a}`);
  };
  const doQueue = (q: string) => {
    void run(() => reassignQueue(cb, q), `Moved to ${q}`);
  };
  const doPriority = (p: CbPriority) => {
    void run(() => setPriority(cb, p), `Priority → ${PRIORITY_LABELS[p]}`);
  };
  const doReminder = (c: CbChannel) => {
    void run(() => sendReminder(cb, c), `Reminder sent · ${CHANNEL_LABELS[c]}`);
  };
  const doStart = () => {
    void run(async () => {
      await startCall(cb);
      setTab("outcome");
    }, "Call started · opening cockpit");
  };
  const doComplete = () => {
    void run(async () => {
      await markCompleted(cb, disposition, notes);
      onClose();
    }, `Callback completed · ${DISPOSITION_LABELS[disposition]}`);
  };
  const doCancel = () => {
    void run(async () => {
      await cancelCallback(cb, "Cancelled by agent");
      onClose();
    }, "Cancelled");
  };

  const rescheduleIsDnd = isWithinDndWindow(cb, new Date(rescheduleAt).toISOString());
  const assigneeOptions = [...new Set(assignees.includes(cb.assignee) ? assignees : [cb.assignee, ...assignees])];
  const queueOptions = [...new Set(queues.includes(cb.queue) ? queues : [cb.queue, ...queues])];

  return (
    <div className="fixed inset-0 z-40 flex">
      <button aria-label="Close overlay" onClick={onClose} className="flex-1 bg-black/30" />
      <aside className="flex h-full w-full max-w-[580px] flex-col bg-surface-card shadow-xl">
        <div className="shrink-0 border-b border-[var(--border-token)] px-4 py-3">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <Link to="/customers/$customerId" params={{ customerId: cb.customerId }} className="truncate text-[15px] font-semibold text-brand-navy hover:underline">
                  {cb.customerName}
                </Link>
                <span className="text-[11px] text-text-muted">····{cb.accountTail} · {cb.id}</span>
              </div>
              <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-text-secondary">
                <span className="inline-flex items-center gap-1"><SIcon className="h-3 w-3" /> {SOURCE_LABELS[cb.source]}</span>
                <span>·</span>
                <span>{REASON_LABELS[cb.reason]}</span>
                <span>·</span>
                <span>{cb.customerTimezone}</span>
              </div>
            </div>
            <Button variant="ghost" size="sm" className="h-8 w-8 shrink-0 p-0" onClick={onClose}><X className="h-4 w-4" /></Button>
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className={cn("inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold", STATUS_TONE[cb.status])}>
              {STATUS_LABELS[cb.status]}
            </span>
            <span className="text-[11px] text-text-muted tabular-nums">{fmtLongDate(cb.scheduledAt)} · {cb.windowMins}m window</span>
            {dndAtCurrent && (
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[10.5px] font-semibold text-amber-800">
                <AlertTriangle className="h-3 w-3" /> Inside DND window
              </span>
            )}
          </div>

          <div className="mt-2 flex flex-wrap gap-1.5">
            {(cb.status === "scheduled" || cb.status === "reminded") && (
              <Button size="sm" className="h-8 text-[12px]" onClick={doStart} disabled={busy}>
                <Phone className="mr-1 h-3.5 w-3.5" /> Start call
              </Button>
            )}
            {cb.originConversationId && (
              <Link to="/inbox">
                <Button size="sm" variant="outline" className="h-8 text-[12px]">
                  <ExternalLink className="mr-1 h-3.5 w-3.5" /> Open conversation
                </Button>
              </Link>
            )}
            {cb.status !== "completed" && cb.status !== "cancelled" && (
              <Button size="sm" variant="ghost" className="h-8 text-[12px] text-red-600" onClick={doCancel} disabled={busy}>Cancel</Button>
            )}
          </div>
        </div>

        <div className="flex shrink-0 gap-1 border-b border-[var(--border-token)] px-2 pt-2">
          {(["details", "reminders", "timeline", "outcome"] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                "rounded-t-md px-3 py-1.5 text-[12px] capitalize",
                tab === t ? "bg-brand-tint text-brand-primary-dark font-semibold" : "text-text-secondary hover:bg-surface-sunken",
              )}
            >
              {t}
            </button>
          ))}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {tab === "details" && (
            <div className="space-y-4 text-[12.5px]">
              <section>
                <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-text-muted">Why they asked</div>
                <div className="rounded-md border border-[var(--border-token)] bg-surface-sunken/40 px-3 py-2 italic text-text-secondary">
                  {cb.transcriptSnippet || "(no snippet)"}
                </div>
              </section>

              <section className="grid grid-cols-2 gap-3">
                <div>
                  <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-text-muted">Queue</div>
                  <select
                    value={cb.queue}
                    onChange={(e) => doQueue(e.target.value)}
                    disabled={busy}
                    className="h-8 w-full rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
                  >
                    {queueOptions.map((q) => <option key={q} value={q}>{q}</option>)}
                  </select>
                </div>
                <div>
                  <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-text-muted">Assignee</div>
                  <select
                    value={cb.assignee}
                    onChange={(e) => doAssign(e.target.value)}
                    disabled={busy}
                    className="h-8 w-full rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
                  >
                    {assigneeOptions.map((a) => <option key={a} value={a}>{a}</option>)}
                  </select>
                </div>
                <div>
                  <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-text-muted">Priority</div>
                  <div className="flex gap-1">
                    {PRIORITIES.map((p) => (
                      <button
                        key={p}
                        disabled={busy}
                        onClick={() => doPriority(p)}
                        className={cn(
                          "flex-1 rounded-md border px-1 py-1 text-[11px]",
                          cb.priority === p ? "border-brand-primary bg-brand-tint text-brand-primary-dark font-semibold" : "border-[var(--border-token)] text-text-secondary hover:bg-surface-sunken",
                        )}
                      >
                        {PRIORITY_LABELS[p]}
                      </button>
                    ))}
                  </div>
                </div>
                <div>
                  <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-text-muted">Preferred window</div>
                  <div className="h-8 rounded-md border border-[var(--border-token)] bg-surface-sunken/30 px-2 flex items-center text-[12px] text-text-secondary">
                    {cb.preferredWindow}
                  </div>
                </div>
              </section>

              <section>
                <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-text-muted">Reschedule</div>
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    type="datetime-local"
                    value={rescheduleAt}
                    onChange={(e) => setRescheduleAt(e.target.value)}
                    disabled={busy}
                    className="h-8 rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
                  />
                  <Button size="sm" className="h-8 text-[12px]" onClick={doReschedule} disabled={busy}>Save</Button>
                  {rescheduleIsDnd && (
                    <Button size="sm" variant="outline" className="h-8 text-[11.5px] border-amber-400 text-amber-800" onClick={useNextAllowed} disabled={busy}>
                      <AlertTriangle className="mr-1 h-3 w-3" /> Use next DND-safe slot
                    </Button>
                  )}
                </div>
                {rescheduleIsDnd && (
                  <div className="mt-1 text-[10.5px] text-amber-700">This slot is outside the customer's preferred window ({cb.preferredWindow}).</div>
                )}
              </section>
            </div>
          )}

          {tab === "reminders" && (
            <div className="space-y-3 text-[12.5px]">
              <div className="flex flex-wrap gap-1.5">
                {CHANNELS.map((c) => (
                  <Button key={c} size="sm" variant="outline" className="h-8 text-[12px]" onClick={() => doReminder(c)} disabled={busy}>
                    <Send className="mr-1 h-3 w-3" /> Send {CHANNEL_LABELS[c]}
                  </Button>
                ))}
              </div>
              <div className="rounded-md border border-[var(--border-token)]">
                <div className="border-b border-[var(--border-token)] bg-surface-sunken/50 px-3 py-1.5 text-[11px] font-semibold text-brand-navy">
                  Reminder history ({cb.reminders.length})
                </div>
                <ul className="divide-y divide-[var(--border-token)]">
                  {cb.reminders.map((r, i) => (
                    <li key={i} className="flex items-center justify-between px-3 py-2 text-[12px]">
                      <div>
                        <div className="font-medium text-text-primary">{CHANNEL_LABELS[r.channel]}</div>
                        <div className="text-[10.5px] text-text-muted">{fmtLongDate(r.at)}</div>
                      </div>
                      <span className={cn("rounded-full px-2 py-0.5 text-[10.5px] font-semibold", r.status === "sent" ? "bg-emerald-100 text-emerald-800" : r.status === "queued" ? "bg-slate-100 text-slate-600" : "bg-brand-tint text-brand-primary-dark")}>
                        {r.status}
                      </span>
                    </li>
                  ))}
                  {cb.reminders.length === 0 && (
                    <li className="px-3 py-4 text-center text-text-muted text-[11px]">No reminders sent yet.</li>
                  )}
                </ul>
              </div>
            </div>
          )}

          {tab === "timeline" && (
            <ol className="space-y-2 text-[12px]">
              {[...cb.events].reverse().map((e, i) => (
                <li key={i} className="flex gap-2">
                  <div className={cn(
                    "mt-1 h-2 w-2 shrink-0 rounded-full",
                    e.tone === "success" ? "bg-emerald-500" : e.tone === "danger" ? "bg-red-500" : e.tone === "warn" ? "bg-amber-500" : "bg-brand-primary",
                  )} />
                  <div className="min-w-0">
                    <div className="text-text-primary">{e.label}</div>
                    <div className="text-[10.5px] text-text-muted">{fmtLongDate(e.at)}{e.actor ? ` · ${e.actor}` : ""}</div>
                  </div>
                </li>
              ))}
            </ol>
          )}

          {tab === "outcome" && (
            <div className="space-y-3 text-[12.5px]">
              {cb.status !== "in_progress" && cb.status !== "completed" && (
                <div className="rounded-md border border-[var(--border-token)] bg-surface-sunken/40 px-3 py-2 text-text-secondary">
                  Outcome is captured once the call is in progress or completed. Use <em>Start call</em> above.
                </div>
              )}
              <div>
                <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-text-muted">Disposition</div>
                <div className="flex flex-wrap gap-1.5">
                  {DISPOS.map((d) => (
                    <button
                      key={d}
                      onClick={() => setDisposition(d)}
                      disabled={busy}
                      className={cn(
                        "rounded-md border px-2 py-1 text-[11.5px]",
                        disposition === d ? "border-brand-primary bg-brand-tint text-brand-primary-dark font-semibold" : "border-[var(--border-token)] text-text-secondary hover:bg-surface-sunken",
                      )}
                    >
                      {DISPOSITION_LABELS[d]}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-text-muted">CRM note</div>
                <textarea
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  disabled={busy}
                  placeholder="Summary, next steps, agreed amount, etc."
                  className="min-h-[96px] w-full rounded-md border border-[var(--border-token)] bg-surface-card p-2 text-[12px]"
                />
              </div>
              <Button
                size="sm"
                className="h-8 text-[12px]"
                onClick={doComplete}
                disabled={busy || (cb.status !== "in_progress" && cb.status !== "completed")}
              >
                Complete & writeback to CRM
              </Button>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
