import { useMemo, useState } from "react";
import { toast } from "sonner";
import { X, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  CHANNEL_LABELS,
  PRIORITY_LABELS,
  REASON_LABELS,
  customerOptions,
  isWithinDndWindow,
  type CbChannel,
  type CbPriority,
  type CbReason,
} from "@/data/callbacks-seed";
import { createCallback } from "@/api/callbacks";

const REASONS: CbReason[] = ["payment_discussion", "dispute_followup", "document_query", "hardship_review", "upsell_interest", "general"];
const CHANNELS: CbChannel[] = ["whatsapp", "sms", "email"];
const PRIORITIES: CbPriority[] = ["low", "normal", "high", "urgent"];

export interface CustomerOption {
  id: string;
  name: string;
  accountId: string;
  preferredWindow?: string;
  customerDnd?: boolean;
  timezone?: string;
}

function localTomorrowAt(hour = 11, minute = 0) {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  d.setHours(hour, minute, 0, 0);
  const pad = (n: number) => (n < 10 ? `0${n}` : `${n}`);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

interface Props {
  onClose: () => void;
  onCreated: () => void;
  /** Live: real customers from GET /customers. Mock: seed pool (pass undefined). */
  customers?: CustomerOption[];
  assignees: string[];
  queues: string[];
}

export function NewCallbackSheet({ onClose, onCreated, customers, assignees, queues }: Props) {
  const custs = useMemo(
    () => customers ?? customerOptions().map((c) => ({ ...c, preferredWindow: undefined, customerDnd: undefined })),
    [customers],
  );
  const [customerId, setCustomerId] = useState(custs[0]?.id ?? "");
  const [reason, setReason] = useState<CbReason>("payment_discussion");
  const [scheduledAt, setScheduledAt] = useState(localTomorrowAt(11, 0));
  const [windowMins, setWindowMins] = useState<30 | 60 | 120>(30);
  const [queue, setQueue] = useState(queues[0] ?? "Retail Collections");
  const [assignee, setAssignee] = useState(assignees[0] ?? "Unassigned");
  const [priority, setPriority] = useState<CbPriority>("normal");
  const [reminderChannels, setReminderChannels] = useState<CbChannel[]>(["whatsapp"]);
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);

  const selected = custs.find((c) => c.id === customerId);
  const iso = useMemo(() => new Date(scheduledAt).toISOString(), [scheduledAt]);
  const preview = {
    preferredWindow: selected?.preferredWindow ?? "10:00–19:00 IST",
    customerDnd: selected?.customerDnd ?? false,
    scheduledAt: iso,
  };
  const isDnd = isWithinDndWindow(preview, iso);

  const toggleChannel = (c: CbChannel) =>
    setReminderChannels((prev) => (prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]));

  const submit = async () => {
    if (!customerId) {
      toast.error("Pick a customer");
      return;
    }
    if (busy) return;
    setBusy(true);
    try {
      await createCallback({
        customerId,
        reason,
        scheduledAt: iso,
        windowMins,
        queue,
        assignee,
        reminderChannels,
        priority,
        notes: notes.trim() || undefined,
      });
      toast.success("Callback scheduled");
      onCreated();
      onClose();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Create failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex">
      <button aria-label="Close overlay" onClick={onClose} className="flex-1 bg-black/30" />
      <aside className="flex h-full w-full max-w-[520px] flex-col bg-surface-card shadow-xl">
        <div className="flex shrink-0 items-center justify-between border-b border-[var(--border-token)] px-4 py-3">
          <div>
            <div className="text-[15px] font-semibold text-brand-navy">New callback</div>
            <div className="text-[11px] text-text-muted">Schedule a call, assign an owner, and queue reminders.</div>
          </div>
          <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={onClose}><X className="h-4 w-4" /></Button>
        </div>

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4 text-[12.5px]">
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-text-muted">Customer</div>
              <select value={customerId} onChange={(e) => setCustomerId(e.target.value)} disabled={busy} className="h-8 w-full rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]">
                {custs.map((c) => <option key={c.id} value={c.id}>{c.name} · {c.accountId}</option>)}
              </select>
            </div>
            <div className="col-span-2">
              <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-text-muted">Reason</div>
              <div className="flex flex-wrap gap-1.5">
                {REASONS.map((r) => (
                  <button key={r} onClick={() => setReason(r)} disabled={busy} className={cn(
                    "rounded-md border px-2 py-1 text-[11px]",
                    reason === r ? "border-brand-primary bg-brand-tint text-brand-primary-dark font-semibold" : "border-[var(--border-token)] text-text-secondary hover:bg-surface-sunken",
                  )}>
                    {REASON_LABELS[r]}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-text-muted">Date & time</div>
              <input type="datetime-local" value={scheduledAt} onChange={(e) => setScheduledAt(e.target.value)} disabled={busy} className="h-8 w-full rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]" />
            </div>
            <div>
              <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-text-muted">Window</div>
              <select value={windowMins} onChange={(e) => setWindowMins(parseInt(e.target.value) as 30 | 60 | 120)} disabled={busy} className="h-8 w-full rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]">
                <option value={30}>30 minutes</option>
                <option value={60}>60 minutes</option>
                <option value={120}>2 hours</option>
              </select>
            </div>
            <div>
              <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-text-muted">Queue</div>
              <select value={queue} onChange={(e) => setQueue(e.target.value)} disabled={busy} className="h-8 w-full rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]">
                {queues.map((q) => <option key={q} value={q}>{q}</option>)}
              </select>
            </div>
            <div>
              <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-text-muted">Assignee</div>
              <select value={assignee} onChange={(e) => setAssignee(e.target.value)} disabled={busy} className="h-8 w-full rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]">
                {assignees.map((a) => <option key={a} value={a}>{a}</option>)}
              </select>
            </div>
            <div className="col-span-2">
              <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-text-muted">Priority</div>
              <div className="flex gap-1">
                {PRIORITIES.map((p) => (
                  <button key={p} onClick={() => setPriority(p)} disabled={busy} className={cn(
                    "flex-1 rounded-md border px-1 py-1 text-[11px]",
                    priority === p ? "border-brand-primary bg-brand-tint text-brand-primary-dark font-semibold" : "border-[var(--border-token)] text-text-secondary hover:bg-surface-sunken",
                  )}>
                    {PRIORITY_LABELS[p]}
                  </button>
                ))}
              </div>
            </div>
            <div className="col-span-2">
              <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-text-muted">Reminder channels</div>
              <div className="flex flex-wrap gap-1.5">
                {CHANNELS.map((c) => (
                  <button key={c} onClick={() => toggleChannel(c)} disabled={busy} className={cn(
                    "rounded-md border px-2 py-1 text-[11px]",
                    reminderChannels.includes(c) ? "border-brand-primary bg-brand-tint text-brand-primary-dark font-semibold" : "border-[var(--border-token)] text-text-secondary hover:bg-surface-sunken",
                  )}>
                    {CHANNEL_LABELS[c]}
                  </button>
                ))}
              </div>
            </div>
            <div className="col-span-2">
              <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-text-muted">Notes (optional)</div>
              <textarea value={notes} onChange={(e) => setNotes(e.target.value)} disabled={busy} placeholder="What the customer said, agreed context, etc." className="min-h-[72px] w-full rounded-md border border-[var(--border-token)] bg-surface-card p-2 text-[12px]" />
            </div>
          </div>

          {isDnd && (
            <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-[11.5px] text-amber-800">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <div>This slot falls inside the customer's DND / outside their preferred window. Consider a safer time.</div>
            </div>
          )}
        </div>

        <div className="flex shrink-0 items-center justify-end gap-2 border-t border-[var(--border-token)] px-4 py-3">
          <Button variant="ghost" size="sm" className="h-8 text-[12px]" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button size="sm" className="h-8 text-[12px]" onClick={() => void submit()} disabled={busy}>Schedule callback</Button>
        </div>
      </aside>
    </div>
  );
}
