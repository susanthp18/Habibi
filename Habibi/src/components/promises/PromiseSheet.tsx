import { useEffect, useMemo, useState } from "react";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  fmtDate,
  fmtMoney,
  listCustomerSlim,
  type Promise,
  type PromiseChannel,
  type PromiseSource,
  type PromiseStatus,
  type ReminderStatus,
} from "@/data/promises-seed";

// --- Create sheet ---
export interface CreateInput {
  customerId: string;
  customerName: string;
  accountTail: string;
  amount: number;
  promisedDate: string;
  channel: PromiseChannel;
  source: PromiseSource;
  owner: string;
  reminder: ReminderStatus;
  notes?: string;
}

export interface CustomerOption {
  id: string;
  name: string;
  accountId: string;
  outstanding: number;
}

interface CreateProps {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onSubmit: (input: CreateInput) => void;
  owners: string[];
  /** Real customers to pick from (live mode). Falls back to seed roster when omitted. */
  customers?: CustomerOption[];
}

const todayISO = () => {
  const d = new Date();
  d.setDate(d.getDate() + 3);
  return d.toISOString().slice(0, 10);
};

export function CreatePromiseSheet({ open, onOpenChange, onSubmit, owners, customers: customersProp }: CreateProps) {
  const customers = useMemo<CustomerOption[]>(
    () => (customersProp && customersProp.length ? customersProp : listCustomerSlim()),
    [customersProp],
  );
  const [customerId, setCustomerId] = useState(customers[0]?.id ?? "");
  const [amount, setAmount] = useState("5000");
  const [date, setDate] = useState(todayISO());
  const [channel, setChannel] = useState<PromiseChannel>("whatsapp");
  const [source, setSource] = useState<PromiseSource>("agent");
  const [owner, setOwner] = useState(owners[0] ?? "AI Bot");
  const [reminder, setReminder] = useState<ReminderStatus>("scheduled");
  const [notes, setNotes] = useState("");

  useEffect(() => {
    if (open) {
      setCustomerId(customers[0]?.id ?? "");
      setAmount("5000");
      setDate(todayISO());
      setChannel("whatsapp");
      setSource("agent");
      setOwner(owners[0] ?? "AI Bot");
      setReminder("scheduled");
      setNotes("");
    }
  }, [open, owners, customers]);

  const submit = () => {
    const cust = customers.find((c) => c.id === customerId);
    if (!cust) return;
    const amt = Number(amount);
    if (!amt || amt <= 0) return;
    const iso = new Date(`${date}T10:00:00`).toISOString();
    onSubmit({
      customerId: cust.id,
      customerName: cust.name,
      accountTail: cust.accountId.slice(-4),
      amount: amt,
      promisedDate: iso,
      channel,
      source,
      owner,
      reminder,
      notes: notes || undefined,
    });
    onOpenChange(false);
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-[440px]">
        <SheetHeader>
          <SheetTitle>New promise-to-pay</SheetTitle>
          <SheetDescription>Capture a commitment and Collections AI will handle reminders.</SheetDescription>
        </SheetHeader>
        <div className="mt-4 space-y-3">
          <Field label="Customer">
            <Select value={customerId} onValueChange={setCustomerId}>
              <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
              <SelectContent className="max-h-[280px]">
                {customers.map((c) => (
                  <SelectItem key={c.id} value={c.id}>
                    {c.name} · #{c.accountId.slice(-4)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Amount (₹)">
              <Input type="number" value={amount} onChange={(e) => setAmount(e.target.value)} className="h-9" />
            </Field>
            <Field label="Promised date">
              <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="h-9" />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Channel">
              <Select value={channel} onValueChange={(v) => setChannel(v as PromiseChannel)}>
                <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="voice">Voice call</SelectItem>
                  <SelectItem value="whatsapp">WhatsApp</SelectItem>
                  <SelectItem value="sms">SMS</SelectItem>
                  <SelectItem value="chat">Chat</SelectItem>
                  <SelectItem value="email">Email</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            <Field label="Source">
              <Select value={source} onValueChange={(v) => setSource(v as PromiseSource)}>
                <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="bot">Bot-captured</SelectItem>
                  <SelectItem value="agent">Agent-captured</SelectItem>
                  <SelectItem value="self">Self-serve</SelectItem>
                </SelectContent>
              </Select>
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Owner">
              <Select value={owner} onValueChange={setOwner}>
                <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {owners.map((o) => (<SelectItem key={o} value={o}>{o}</SelectItem>))}
                </SelectContent>
              </Select>
            </Field>
            <Field label="Reminders">
              <Select value={reminder} onValueChange={(v) => setReminder(v as ReminderStatus)}>
                <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="off">Off</SelectItem>
                  <SelectItem value="scheduled">24h before</SelectItem>
                  <SelectItem value="sent">Same-day nudge</SelectItem>
                </SelectContent>
              </Select>
            </Field>
          </div>
          <Field label="Notes (optional)">
            <Textarea rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Context, promised source of funds, etc." />
          </Field>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={submit}>Capture promise</Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <Label className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">{label}</Label>
      {children}
    </div>
  );
}

// --- Detail drawer ---
interface DetailProps {
  promise: Promise | null;
  onOpenChange: (v: boolean) => void;
  onMark: (p: Promise, status: PromiseStatus, opts?: { paidAmount?: number }) => void;
  onReschedule: (p: Promise, newDate: string) => void;
}

export function PromiseDetailSheet({ promise, onOpenChange, onMark, onReschedule }: DetailProps) {
  const [partialAmt, setPartialAmt] = useState("");
  const [rescheduleDate, setRescheduleDate] = useState("");

  useEffect(() => {
    if (promise) {
      setPartialAmt(String(Math.round(promise.amount / 2)));
      setRescheduleDate(promise.promisedDate.slice(0, 10));
    }
  }, [promise]);

  if (!promise) return null;

  return (
    <Sheet open={!!promise} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-[460px]">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            {promise.customerName}
            <Badge variant="outline" className="text-[10px]">{promise.id}</Badge>
          </SheetTitle>
          <SheetDescription>
            {fmtMoney(promise.amount)} · promised {fmtDate(promise.promisedDate)}
          </SheetDescription>
        </SheetHeader>

        <div className="mt-4 space-y-4">
          <div className="grid grid-cols-2 gap-3 rounded-lg border border-[var(--border-token)] bg-surface-sunken/50 p-3 text-[12px]">
            <Meta label="Status" value={promise.status.replace("_", " ")} />
            <Meta label="Channel" value={promise.channel} />
            <Meta label="Source" value={promise.source} />
            <Meta label="Owner" value={promise.owner} />
            <Meta label="Reminder" value={promise.reminderStatus} />
            <Meta label="Account" value={`#${promise.accountTail}`} />
          </div>

          {promise.notes && (
            <div className="rounded-md border border-[var(--border-token)] bg-surface-card p-3 text-[12px] text-text-secondary">
              {promise.notes}
            </div>
          )}

          <div>
            <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-text-muted">Timeline</div>
            <ol className="space-y-2">
              {promise.events.map((ev, i) => (
                <li key={i} className="flex items-start gap-2 text-[12px]">
                  <span
                    className={`mt-1 inline-block h-2 w-2 shrink-0 rounded-full ${
                      ev.tone === "success"
                        ? "bg-emerald-500"
                        : ev.tone === "warn"
                          ? "bg-orange-500"
                          : ev.tone === "danger"
                            ? "bg-red-500"
                            : "bg-brand-primary"
                    }`}
                  />
                  <div className="flex-1">
                    <div className="text-text-primary">{ev.label}</div>
                    <div className="text-[10.5px] text-text-muted">
                      {new Date(ev.at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}
                    </div>
                  </div>
                </li>
              ))}
            </ol>
          </div>

          {(promise.status === "upcoming" || promise.status === "due_today") && (
            <>
              <div className="rounded-md border border-[var(--border-token)] p-3">
                <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-text-muted">Mark outcome</div>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" onClick={() => onMark(promise, "kept")} className="bg-emerald-600 hover:bg-emerald-700 text-white">
                    Mark kept · {fmtMoney(promise.amount)}
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => onMark(promise, "broken")} className="border-red-200 text-red-700 hover:bg-red-50">
                    Mark broken
                  </Button>
                </div>
                <div className="mt-3 flex items-end gap-2">
                  <div className="flex-1">
                    <Label className="text-[11px] text-text-muted">Partial amount received</Label>
                    <Input type="number" value={partialAmt} onChange={(e) => setPartialAmt(e.target.value)} className="mt-1 h-9" />
                  </div>
                  <Button size="sm" variant="outline" onClick={() => onMark(promise, "partial", { paidAmount: Number(partialAmt) || 0 })}>
                    Mark partial
                  </Button>
                </div>
              </div>

              <div className="rounded-md border border-[var(--border-token)] p-3">
                <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-text-muted">Reschedule</div>
                <div className="flex items-end gap-2">
                  <div className="flex-1">
                    <Label className="text-[11px] text-text-muted">New promised date</Label>
                    <Input type="date" value={rescheduleDate} onChange={(e) => setRescheduleDate(e.target.value)} className="mt-1 h-9" />
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      const iso = new Date(`${rescheduleDate}T10:00:00`).toISOString();
                      onReschedule(promise, iso);
                    }}
                  >
                    Reschedule
                  </Button>
                </div>
              </div>
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10.5px] font-semibold uppercase tracking-wider text-text-muted">{label}</div>
      <div className="capitalize text-text-primary">{value}</div>
    </div>
  );
}
