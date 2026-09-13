import { useEffect, useId, useState } from "react";
import { bindControlId } from "@/components/ui/bind-control-id";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectField,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  PROMISE_REVISION_REASONS,
  type Promise,
  type PromiseChannel,
  type PromiseRevisionReason,
  type ReviseInput,
  type PromiseStatus,
  type ReminderStatus,
  type CreateInput,
  type CustomerOption,
} from "@/api/types/promises";
import { fmtDate, fmtMoney } from "@/lib/format";
import { REVISION_REASON_LABELS } from "@/lib/promises";

// --- Create sheet ---

interface CreateProps {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onSubmit: (input: CreateInput) => void;
  owners: string[];
  customers: CustomerOption[];
}

const todayISO = () => {
  const d = new Date();
  d.setDate(d.getDate() + 3);
  return d.toISOString().slice(0, 10);
};

export function CreatePromiseSheet({
  open,
  onOpenChange,
  onSubmit,
  owners,
  customers,
}: CreateProps) {
  const [customerId, setCustomerId] = useState(customers[0]?.id ?? "");
  const [amount, setAmount] = useState("5000");
  const [date, setDate] = useState(todayISO());
  const [channel, setChannel] = useState<PromiseChannel>("whatsapp");
  const [owner, setOwner] = useState(owners[0] ?? "AI Bot");
  // A new promise's reminder is off or queued; "scheduled" and "sent" are what
  // the reminder worker writes back, not what an operator declares.
  const [reminder, setReminder] = useState<ReminderStatus>("queued");
  const [notes, setNotes] = useState("");

  useEffect(() => {
    if (open) {
      setCustomerId(customers[0]?.id ?? "");
      setAmount("5000");
      setDate(todayISO());
      setChannel("whatsapp");
      setOwner(owners[0] ?? "");
      setReminder("queued");
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
      accountId: cust.accountId,
      amount: amt,
      promisedDate: iso,
      channel,
      owner,
      reminder,
      notes: notes || undefined,
    });
    onOpenChange(false);
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-[25rem]">
        <SheetHeader>
          <SheetTitle>New promise-to-pay</SheetTitle>
          <SheetDescription>
            Capture a commitment and BigBound AI will handle reminders.
          </SheetDescription>
        </SheetHeader>
        <div className="mt-200 space-y-150">
          <Field label="Customer">
            <Select value={customerId} onValueChange={setCustomerId}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="max-h-[17.5rem]">
                {customers.map((c) => (
                  <SelectItem key={c.id} value={c.id}>
                    {c.name} · #{c.accountId.slice(-4)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <div className="grid grid-cols-2 gap-150">
            <Field label="Amount (₹)">
              <Input type="number" value={amount} onChange={(e) => setAmount(e.target.value)} />
            </Field>
            <Field label="Promised date">
              <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-150">
            <Field label="Channel">
              <Select value={channel} onValueChange={(v) => setChannel(v as PromiseChannel)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="voice">Voice call</SelectItem>
                  <SelectItem value="whatsapp">WhatsApp</SelectItem>
                  <SelectItem value="sms">SMS</SelectItem>
                  <SelectItem value="chat">Chat</SelectItem>
                  <SelectItem value="email">Email</SelectItem>
                </SelectContent>
              </Select>
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-150">
            <Field label="Owner">
              <Select value={owner} onValueChange={setOwner}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {owners.map((o) => (
                    <SelectItem key={o} value={o}>
                      {o}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <Field label="Reminders">
              <Select value={reminder} onValueChange={(v) => setReminder(v as ReminderStatus)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="off">Off</SelectItem>
                  <SelectItem value="queued">Queue a reminder</SelectItem>
                </SelectContent>
              </Select>
            </Field>
          </div>
          <Field label="Notes (optional)">
            <Textarea
              rows={3}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Context, promised source of funds, etc."
            />
          </Field>
        </div>
        <div className="mt-300 flex justify-end gap-100">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={submit}>Capture promise</Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  const id = useId();
  return (
    <div className="space-y-050">
      <Label htmlFor={id} className="text-body-small font-semibold text-text-subtlest">
        {label}
      </Label>
      {bindControlId(children, id, label)}
    </div>
  );
}

// --- Detail drawer ---
interface DetailProps {
  promise: Promise | null;
  onOpenChange: (v: boolean) => void;
  onMark: (p: Promise, status: PromiseStatus, opts?: { paidAmount?: number }) => void;
  onRevise: (p: Promise, input: ReviseInput) => void;
  onCancelPromise: (p: Promise, input: { reason: PromiseRevisionReason; note?: string }) => void;
  onResend?: (p: Promise) => void;
}

const REASON_OPTIONS = PROMISE_REVISION_REASONS.map((r) => ({
  value: r,
  label: REVISION_REASON_LABELS[r],
}));

export function PromiseDetailSheet({
  promise,
  onOpenChange,
  onMark,
  onRevise,
  onCancelPromise,
  onResend,
}: DetailProps) {
  const uid = useId();
  const [partialAmt, setPartialAmt] = useState("");
  const [reviseDate, setReviseDate] = useState("");
  const [reviseAmount, setReviseAmount] = useState("");
  const [reviseReason, setReviseReason] = useState<PromiseRevisionReason>(
    "customer_requested_delay",
  );
  const [reviseNote, setReviseNote] = useState("");

  useEffect(() => {
    if (promise) {
      setPartialAmt(String(Math.round(promise.amount / 2)));
      setReviseDate(promise.promisedDate.slice(0, 10));
      setReviseAmount(String(promise.amount));
      setReviseReason("customer_requested_delay");
      setReviseNote("");
    }
  }, [promise]);

  const reviseChanged =
    !!promise &&
    ((!!reviseDate && reviseDate !== promise.promisedDate.slice(0, 10)) ||
      (!!reviseAmount && Number(reviseAmount) !== promise.amount));

  if (!promise) return null;

  return (
    <Sheet open={!!promise} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-[25rem]">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-100">
            {promise.customerName}
            <Badge variant="outline" className="text-body-small">
              {promise.id}
            </Badge>
          </SheetTitle>
          <SheetDescription>
            {fmtMoney(promise.amount)} · promised {fmtDate(promise.promisedDate)}
          </SheetDescription>
        </SheetHeader>

        <div className="mt-200 space-y-200">
          <div className="grid grid-cols-2 gap-150 rounded-large border border-border bg-surface-sunken/50 p-150 text-body-small">
            <Meta
              label="Status"
              value={
                promise.status === "cancelled" && promise.cancelReason
                  ? `cancelled · ${REVISION_REASON_LABELS[promise.cancelReason as PromiseRevisionReason] ?? promise.cancelReason}`
                  : promise.status.replace("_", " ")
              }
            />
            <Meta label="Channel" value={promise.channel} />
            <Meta label="Source" value={promise.source} />
            <Meta label="Owner" value={promise.owner} />
            <Meta label="Reminder" value={promise.reminderStatus} />
            <Meta label="Account" value={`#${promise.accountTail}`} />
            <Meta
              label="Confirm"
              value={
                promise.payLinkSent
                  ? `${promise.confirmChannel ?? "sent"}${promise.phoneLast4 ? ` ···${promise.phoneLast4}` : ""}`
                  : promise.confirmStatus === "suppressed"
                    ? "suppressed"
                    : (promise.paymentIntentStatus ?? "—")
              }
            />
            <Meta label="Intent" value={promise.paymentIntentStatus ?? "—"} />
          </div>

          {promise.notes && (
            <div className="rounded-medium border border-border bg-surface p-150 text-body-small text-text-subtle">
              {promise.notes}
            </div>
          )}

          <div>
            <div className="mb-100 text-body-small font-semibold text-text-subtlest">Timeline</div>
            <ol className="space-y-100">
              {promise.events.map((ev, i) => (
                <li key={i} className="flex items-start gap-100 text-body-small">
                  <span
                    className={`mt-050 inline-block h-100 w-100 shrink-0 rounded-full ${
                      ev.tone === "success"
                        ? "bg-background-success-bold"
                        : ev.tone === "warn"
                          ? "bg-background-warning-bold"
                          : ev.tone === "danger"
                            ? "bg-background-danger-bold"
                            : "bg-background-brand-bold"
                    }`}
                  />
                  <div className="flex-1">
                    <div className="text-text">{ev.label}</div>
                    <div className="text-body-small text-text-subtlest">
                      {new Date(ev.at).toLocaleString(undefined, {
                        month: "short",
                        day: "numeric",
                        hour: "numeric",
                        minute: "2-digit",
                      })}
                    </div>
                  </div>
                </li>
              ))}
            </ol>
          </div>

          {(promise.status === "upcoming" || promise.status === "due_today") && onResend && (
            <div className="rounded-medium border border-border p-150">
              <div className="mb-100 text-body-small font-semibold text-text-subtlest">
                Payment link
              </div>
              <p className="mb-100 text-body-small text-text-subtle">
                {promise.payLinkSent
                  ? `Written confirm queued on ${promise.confirmChannel ?? "message"}${promise.phoneLast4 ? ` ending ${promise.phoneLast4}` : ""}.`
                  : "No link has been delivered yet."}
              </p>
              <Button size="sm" variant="outline" onClick={() => onResend(promise)}>
                Resend confirm
              </Button>
            </div>
          )}

          {(promise.status === "upcoming" || promise.status === "due_today") && (
            <>
              <div className="rounded-medium border border-border p-150">
                <div className="mb-100 text-body-small font-semibold text-text-subtlest">
                  Mark outcome
                </div>
                <div className="flex flex-wrap gap-100">
                  <Button
                    size="sm"
                    onClick={() => onMark(promise, "kept")}
                    disabled={!(promise.paidAmount && promise.paidAmount > 0)}
                    title={
                      !(promise.paidAmount && promise.paidAmount > 0)
                        ? "Kept requires a recorded payment"
                        : undefined
                    }
                    className="bg-background-success-bold hover:bg-background-success-bold-pressed text-text-inverse disabled:opacity-40"
                  >
                    Mark kept · {fmtMoney(promise.amount)}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => onMark(promise, "broken")}
                    className="border-border-danger-subtle text-text-danger-bolder hover:bg-background-danger-subtler"
                  >
                    Mark broken
                  </Button>
                </div>
                <div className="mt-150 flex items-end gap-100">
                  <div className="flex-1">
                    <Label className="text-body-small text-text-subtlest">
                      Partial amount received
                    </Label>
                    <Input
                      type="number"
                      value={partialAmt}
                      onChange={(e) => setPartialAmt(e.target.value)}
                      className="mt-050"
                    />
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      onMark(promise, "partial", { paidAmount: Number(partialAmt) || 0 })
                    }
                  >
                    Mark partial
                  </Button>
                </div>
              </div>

              <div className="rounded-medium border border-border p-150">
                <div className="mb-050 text-body-small font-semibold text-text-subtlest">
                  Revise the promise
                </div>
                <p className="mb-100 text-body-small text-text-subtle">
                  The customer asked for a different date or amount. The promise keeps its id and
                  its pay link; the change is recorded with the reason
                  {promise.revisionCount > 0 && ` (moved ${promise.revisionCount}× already)`}.
                </p>
                <div className="grid grid-cols-2 gap-100">
                  <div>
                    <Label
                      htmlFor={`${uid}-revise-date`}
                      className="text-body-small text-text-subtlest"
                    >
                      New date
                    </Label>
                    <Input
                      id={`${uid}-revise-date`}
                      type="date"
                      value={reviseDate}
                      onChange={(e) => setReviseDate(e.target.value)}
                      className="mt-050"
                    />
                  </div>
                  <div>
                    <Label
                      htmlFor={`${uid}-revise-amount`}
                      className="text-body-small text-text-subtlest"
                    >
                      New amount (₹)
                    </Label>
                    <Input
                      id={`${uid}-revise-amount`}
                      type="number"
                      value={reviseAmount}
                      onChange={(e) => setReviseAmount(e.target.value)}
                      className="mt-050"
                    />
                  </div>
                </div>
                <div className="mt-100">
                  <Label
                    htmlFor={`${uid}-revise-reason`}
                    className="text-body-small text-text-subtlest"
                  >
                    Reason
                  </Label>
                  <SelectField
                    id={`${uid}-revise-reason`}
                    className="mt-050"
                    value={reviseReason}
                    onChange={(v) => setReviseReason(v as PromiseRevisionReason)}
                    options={REASON_OPTIONS}
                  />
                </div>
                <div className="mt-100">
                  <Label
                    htmlFor={`${uid}-revise-note`}
                    className="text-body-small text-text-subtlest"
                  >
                    In their words
                  </Label>
                  <Textarea
                    id={`${uid}-revise-note`}
                    rows={2}
                    value={reviseNote}
                    onChange={(e) => setReviseNote(e.target.value)}
                    className="mt-050"
                    placeholder="Salary comes on the 10th…"
                  />
                </div>
                <div className="mt-150 flex items-center justify-between gap-100">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!reviseChanged}
                    title={reviseChanged ? undefined : "Change the date or the amount"}
                    onClick={() =>
                      onRevise(promise, {
                        promisedDate:
                          reviseDate && reviseDate !== promise.promisedDate.slice(0, 10)
                            ? reviseDate
                            : undefined,
                        amount:
                          reviseAmount && Number(reviseAmount) !== promise.amount
                            ? Number(reviseAmount)
                            : undefined,
                        reason: reviseReason,
                        note: reviseNote || undefined,
                      })
                    }
                  >
                    Revise promise
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-text-danger-bolder"
                    onClick={() =>
                      onCancelPromise(promise, {
                        reason: reviseReason,
                        note: reviseNote || undefined,
                      })
                    }
                  >
                    Cancel promise
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
      <div className="text-body-small font-semibold text-text-subtlest">{label}</div>
      <div className="capitalize text-text">{value}</div>
    </div>
  );
}
