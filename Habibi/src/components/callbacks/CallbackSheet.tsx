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
import { Lozenge } from "@/components/ui/lozenge";
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
      <aside className="flex h-full w-full max-w-[37.5rem] flex-col bg-surface shadow-overlay">
        <div className="shrink-0 border-b border-border px-200 py-150">
          <div className="flex items-start justify-between gap-100">
            <div className="min-w-0">
              <div className="flex items-center gap-100">
                <Link to="/customers/$customerId" params={{ customerId: cb.customerId }} className="truncate text-[0.875rem] font-semibold text-text hover:underline">
                  {cb.customerName}
                </Link>
                <span className="text-body-small text-text-subtlest">····{cb.accountTail} · {cb.id}</span>
              </div>
              <div className="mt-025 flex flex-wrap items-center gap-075 text-body-small text-text-subtle">
                <span className="inline-flex items-center gap-050"><SIcon className="h-3 w-3" /> {SOURCE_LABELS[cb.source]}</span>
                <span>·</span>
                <span>{REASON_LABELS[cb.reason]}</span>
                <span>·</span>
                <span>{cb.customerTimezone}</span>
              </div>
            </div>
            <Button variant="ghost" size="sm" className="h-400 w-400 shrink-0 p-0" onClick={onClose}><X className="h-4 w-4" /></Button>
          </div>

          <div className="mt-100 flex flex-wrap items-center gap-100">
            <Lozenge tone={STATUS_TONE[cb.status]}>
              {STATUS_LABELS[cb.status]}
            </Lozenge>
            <span className="text-body-small text-text-subtlest tabular-nums">{fmtLongDate(cb.scheduledAt)} · {cb.windowMins}m window</span>
            {dndAtCurrent && (
              <Lozenge tone="warning">
                <AlertTriangle className="h-3 w-3" /> Inside DND window
              </Lozenge>
            )}
          </div>

          <div className="mt-100 flex flex-wrap gap-075">
            {(cb.status === "scheduled" || cb.status === "reminded") && (
              <Button size="sm" className="h-400 text-body-small" onClick={doStart} disabled={busy}>
                <Phone className="mr-050 h-3.5 w-3.5" /> Start call
              </Button>
            )}
            {cb.originConversationId && (
              <Link to="/inbox">
                <Button size="sm" variant="outline" className="h-400 text-body-small">
                  <ExternalLink className="mr-050 h-3.5 w-3.5" /> Open conversation
                </Button>
              </Link>
            )}
            {cb.status !== "completed" && cb.status !== "cancelled" && (
              <Button size="sm" variant="ghost" className="h-400 text-body-small text-text-danger" onClick={doCancel} disabled={busy}>Cancel</Button>
            )}
          </div>
        </div>

        <div className="flex shrink-0 gap-050 border-b border-border px-100 pt-100">
          {(["details", "reminders", "timeline", "outcome"] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                "rounded-t-md px-150 py-075 text-body-small capitalize",
                tab === t ? "bg-background-brand-subtlest text-text-brand font-semibold" : "text-text-subtle hover:bg-surface-sunken",
              )}
            >
              {t}
            </button>
          ))}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-200">
          {tab === "details" && (
            <div className="space-y-200 text-body-small">
              <section>
                <div className="mb-050 text-body-small font-semibold text-text-subtlest">Why they asked</div>
                <div className="rounded-medium border border-border bg-surface-sunken/40 px-150 py-100 italic text-text-subtle">
                  {cb.transcriptSnippet || "(no snippet)"}
                </div>
              </section>

              <section className="grid grid-cols-2 gap-150">
                <div>
                  <div className="mb-050 text-body-small font-semibold text-text-subtlest">Queue</div>
                  <select
                    value={cb.queue}
                    onChange={(e) => doQueue(e.target.value)}
                    disabled={busy}
                    className="h-400 w-full rounded-medium border border-border bg-surface px-100 text-body-small"
                  >
                    {queueOptions.map((q) => <option key={q} value={q}>{q}</option>)}
                  </select>
                </div>
                <div>
                  <div className="mb-050 text-body-small font-semibold text-text-subtlest">Assignee</div>
                  <select
                    value={cb.assignee}
                    onChange={(e) => doAssign(e.target.value)}
                    disabled={busy}
                    className="h-400 w-full rounded-medium border border-border bg-surface px-100 text-body-small"
                  >
                    {assigneeOptions.map((a) => <option key={a} value={a}>{a}</option>)}
                  </select>
                </div>
                <div>
                  <div className="mb-050 text-body-small font-semibold text-text-subtlest">Priority</div>
                  <div className="flex gap-050">
                    {PRIORITIES.map((p) => (
                      <button
                        key={p}
                        disabled={busy}
                        onClick={() => doPriority(p)}
                        className={cn(
                          "flex-1 rounded-medium border px-050 py-050 text-body-small",
                          cb.priority === p ? "border-border-brand bg-background-brand-subtlest text-text-brand font-semibold" : "border-border text-text-subtle hover:bg-surface-sunken",
                        )}
                      >
                        {PRIORITY_LABELS[p]}
                      </button>
                    ))}
                  </div>
                </div>
                <div>
                  <div className="mb-050 text-body-small font-semibold text-text-subtlest">Preferred window</div>
                  <div className="h-400 rounded-medium border border-border bg-surface-sunken/30 px-100 flex items-center text-body-small text-text-subtle">
                    {cb.preferredWindow}
                  </div>
                </div>
              </section>

              <section>
                <div className="mb-050 text-body-small font-semibold text-text-subtlest">Reschedule</div>
                <div className="flex flex-wrap items-center gap-100">
                  <input
                    type="datetime-local"
                    value={rescheduleAt}
                    onChange={(e) => setRescheduleAt(e.target.value)}
                    disabled={busy}
                    className="h-400 rounded-medium border border-border bg-surface px-100 text-body-small"
                  />
                  <Button size="sm" className="h-400 text-body-small" onClick={doReschedule} disabled={busy}>Save</Button>
                  {rescheduleIsDnd && (
                    <Button size="sm" variant="outline" className="h-400 text-body-small border-border-warning text-text-warning-bolder" onClick={useNextAllowed} disabled={busy}>
                      <AlertTriangle className="mr-050 h-3 w-3" /> Use next DND-safe slot
                    </Button>
                  )}
                </div>
                {rescheduleIsDnd && (
                  <div className="mt-050 text-body-small text-text-warning-bolder">This slot is outside the customer's preferred window ({cb.preferredWindow}).</div>
                )}
              </section>
            </div>
          )}

          {tab === "reminders" && (
            <div className="space-y-150 text-body-small">
              <div className="flex flex-wrap gap-075">
                {CHANNELS.map((c) => (
                  <Button key={c} size="sm" variant="outline" className="h-400 text-body-small" onClick={() => doReminder(c)} disabled={busy}>
                    <Send className="mr-050 h-3 w-3" /> Send {CHANNEL_LABELS[c]}
                  </Button>
                ))}
              </div>
              <div className="rounded-medium border border-border">
                <div className="border-b border-border bg-surface-sunken/50 px-150 py-075 text-body-small font-semibold text-text">
                  Reminder history ({cb.reminders.length})
                </div>
                <ul className="divide-y divide-border">
                  {cb.reminders.map((r, i) => (
                    <li key={i} className="flex items-center justify-between px-150 py-100 text-body-small">
                      <div>
                        <div className="font-medium text-text">{CHANNEL_LABELS[r.channel]}</div>
                        <div className="text-body-small text-text-subtlest">{fmtLongDate(r.at)}</div>
                      </div>
                      <Lozenge
                        tone={r.status === "sent" ? "success" : r.status === "queued" ? "neutral" : "selected"}
                      >
                        {r.status}
                      </Lozenge>
                    </li>
                  ))}
                  {cb.reminders.length === 0 && (
                    <li className="px-150 py-200 text-center text-text-subtlest text-body-small">No reminders sent yet.</li>
                  )}
                </ul>
              </div>
            </div>
          )}

          {tab === "timeline" && (
            <ol className="space-y-100 text-body-small">
              {[...cb.events].reverse().map((e, i) => (
                <li key={i} className="flex gap-100">
                  <div className={cn(
                    "mt-050 h-100 w-100 shrink-0 rounded-full",
                    e.tone === "success" ? "bg-background-success-bold" : e.tone === "danger" ? "bg-background-danger-bold" : e.tone === "warn" ? "bg-background-warning-bold" : "bg-background-brand-bold",
                  )} />
                  <div className="min-w-0">
                    <div className="text-text">{e.label}</div>
                    <div className="text-body-small text-text-subtlest">{fmtLongDate(e.at)}{e.actor ? ` · ${e.actor}` : ""}</div>
                  </div>
                </li>
              ))}
            </ol>
          )}

          {tab === "outcome" && (
            <div className="space-y-150 text-body-small">
              {cb.status !== "in_progress" && cb.status !== "completed" && (
                <div className="rounded-medium border border-border bg-surface-sunken/40 px-150 py-100 text-text-subtle">
                  Outcome is captured once the call is in progress or completed. Use <em>Start call</em> above.
                </div>
              )}
              <div>
                <div className="mb-050 text-body-small font-semibold text-text-subtlest">Disposition</div>
                <div className="flex flex-wrap gap-075">
                  {DISPOS.map((d) => (
                    <button
                      key={d}
                      onClick={() => setDisposition(d)}
                      disabled={busy}
                      className={cn(
                        "rounded-medium border px-100 py-050 text-body-small",
                        disposition === d ? "border-border-brand bg-background-brand-subtlest text-text-brand font-semibold" : "border-border text-text-subtle hover:bg-surface-sunken",
                      )}
                    >
                      {DISPOSITION_LABELS[d]}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <div className="mb-050 text-body-small font-semibold text-text-subtlest">CRM note</div>
                <textarea
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  disabled={busy}
                  placeholder="Summary, next steps, agreed amount, etc."
                  className="min-h-[6rem] w-full rounded-medium border border-border bg-surface p-100 text-body-small"
                />
              </div>
              <Button
                size="sm"
                className="h-400 text-body-small"
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
