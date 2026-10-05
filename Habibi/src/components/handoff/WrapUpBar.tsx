import { useState, type FormEvent } from "react";
import { FileText, Save, X } from "lucide-react";
import type { WrapUpOutcome, WrapUpPayload } from "@/api/handoff";
import type { DisputeType } from "@/api/types/disputes";
import type { CbReason } from "@/api/types/callbacks";
import { SelectField } from "@/components/ui/select";
import { TYPE_LABELS } from "@/lib/disputes";
import { REASON_LABELS } from "@/lib/callbacks";
import { wrapDraft, type DraftOwner } from "@/lib/wrap-draft";

type Props = {
  open: boolean;
  /** The case: its unsaved notes are kept under it until the wrap-up saves. */
  handoffId: string;
  outcomes: WrapUpOutcome[];
  onClose: () => void;
  onSave: (payload: WrapUpPayload) => void;
  saving?: boolean;
  defaultPtpAmount?: number;
  /** The operator wrapping up: their draft, and a callback booked here is theirs. */
  owner: DraftOwner;
  /** perm-collections-write: filing a promise, a dispute or a callback. */
  canFile: boolean;
  error?: string | null;
};

const FILES_RECORD = new Set(["promise", "callback", "dispute"]);
/** Rupees to the paisa: what the amount field's step allows. */
const RUPEES = /^\d+(\.\d{1,2})?$/;

const fieldClass =
  "mt-050 h-400 w-full rounded-medium border border-border bg-surface px-100 text-body-small text-text";
const labelClass = "text-body-small font-medium text-text-subtle";

/** Today plus `days`, as the calendar date in India. */
function istDatePlus(days: number) {
  return new Date(Date.now() + days * 86_400_000).toLocaleDateString("en-CA", {
    timeZone: "Asia/Kolkata",
  });
}

/** Now, as a datetime-local value on India's clock. */
function istNowLocal() {
  return new Date()
    .toLocaleString("sv-SE", { timeZone: "Asia/Kolkata", hour12: false })
    .slice(0, 16)
    .replace(" ", "T");
}

/** A datetime-local value read as India's time -- the zone the field says --
 * whatever the browser's own zone is. */
function istInstant(local: string) {
  return new Date(`${local}:00+05:30`);
}

/**
 * Closing the case. The outcome is the agent's choice -- there is no default
 * -- and each one asks for what it claims happened: a promise, a callback or a
 * dispute is filed with the wrap-up, the rest need a note. Closing the panel
 * hides it; what was typed stays until it is saved.
 */
export function WrapUpBar({
  open,
  handoffId,
  outcomes,
  onClose,
  onSave,
  saving,
  defaultPtpAmount,
  owner,
  canFile,
  error,
}: Props) {
  const [label, setLabel] = useState("");
  const [notes, setNotesState] = useState(() => wrapDraft.read(owner, handoffId));
  const setNotes = (value: string) => {
    setNotesState(value);
    wrapDraft.write(owner, handoffId, value);
  };
  const [ptpAmount, setPtpAmount] = useState(defaultPtpAmount ? String(defaultPtpAmount) : "");
  const [ptpDate, setPtpDate] = useState(() => istDatePlus(7));
  const [callbackAt, setCallbackAt] = useState(() => `${istDatePlus(1)}T11:00`);
  const [callbackReason, setCallbackReason] = useState<CbReason>("payment_discussion");
  const [disputeType, setDisputeType] = useState<DisputeType | "">("");

  const needs = outcomes.find((o) => o.label === label)?.needs;
  // The rights can go while the form is open (the session refreshes): an
  // outcome chosen before then no longer saves.
  const blocked = Boolean(needs && FILES_RECORD.has(needs) && !canFile);
  const amount = Number(ptpAmount);
  const today = istDatePlus(0);
  const callbackTime = callbackAt ? istInstant(callbackAt).getTime() : Number.NaN;
  // The server refuses the same (promise_date_in_past, callback_in_past); the
  // form says so before the round trip.
  const valid = blocked
    ? false
    : needs === "promise"
      ? RUPEES.test(ptpAmount) && amount > 0 && Boolean(ptpDate) && ptpDate >= today
      : needs === "callback"
        ? !Number.isNaN(callbackTime) && callbackTime > Date.now()
        : needs === "dispute"
          ? Boolean(disputeType)
          : needs === "notes"
            ? notes.trim().length > 0
            : false;

  const save = (e: FormEvent) => {
    e.preventDefault();
    if (!valid || !needs) return;
    const payload: WrapUpPayload = { disposition: label, notes };
    if (needs === "promise") payload.promise = { amount, promisedDate: ptpDate };
    if (needs === "callback") {
      payload.callback = {
        scheduledAt: istInstant(callbackAt).toISOString(),
        reason: callbackReason,
        assigneeUserId: owner?.id,
      };
    }
    if (needs === "dispute" && disputeType) payload.dispute = { type: disputeType };
    onSave(payload);
  };

  return (
    <section
      hidden={!open}
      aria-label="Wrap up this case"
      className="shrink-0 border-t border-border bg-surface px-250 py-150"
    >
      <div className="mb-100 flex items-center justify-between">
        <h2 className="flex items-center gap-075 text-body-small font-semibold text-text">
          <FileText className="h-3.5 w-3.5 text-text-brand" />
          Wrap up
        </h2>
        <button
          type="button"
          onClick={onClose}
          className="grid h-300 w-300 place-items-center rounded-medium text-text-subtlest hover:bg-surface-sunken"
          aria-label="Close wrap-up"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <form onSubmit={save} className="grid gap-150 md:grid-cols-[240px_1fr_auto]">
        <div>
          <label htmlFor="wrapup-outcome" className={labelClass}>
            Outcome
          </label>
          <SelectField
            id="wrapup-outcome"
            aria-label="Outcome"
            value={label}
            onChange={setLabel}
            size="compact"
            className="mt-050"
            placeholder="Choose what happened"
            // The records an outcome files need the rights their own pages need.
            options={outcomes.map((o) => {
              const blocked = !canFile && FILES_RECORD.has(o.needs);
              return {
                value: o.label,
                label: blocked ? `${o.label} (your role can't file it)` : o.label,
                disabled: blocked,
              };
            })}
          />

          {blocked ? (
            <p role="alert" className="mt-100 text-body-small text-text-danger">
              Your role can no longer file this outcome&apos;s record. Choose an outcome that needs
              only a note.
            </p>
          ) : null}

          {needs === "promise" && !blocked && (
            <div className="mt-100 grid grid-cols-2 gap-075">
              <div>
                <label htmlFor="wrapup-ptp-amount" className={labelClass}>
                  Amount (₹)
                </label>
                <input
                  id="wrapup-ptp-amount"
                  type="number"
                  inputMode="decimal"
                  required
                  min={0.01}
                  step={0.01}
                  value={ptpAmount}
                  onChange={(e) => setPtpAmount(e.target.value)}
                  className={fieldClass}
                />
              </div>
              <div>
                <label htmlFor="wrapup-ptp-date" className={labelClass}>
                  Promised for
                </label>
                <input
                  id="wrapup-ptp-date"
                  type="date"
                  required
                  min={today}
                  value={ptpDate}
                  onChange={(e) => setPtpDate(e.target.value)}
                  className={fieldClass}
                />
              </div>
            </div>
          )}

          {needs === "callback" && !blocked && (
            <div className="mt-100 grid gap-075">
              <div>
                <label htmlFor="wrapup-callback-at" className={labelClass}>
                  Call back at (IST)
                </label>
                <input
                  id="wrapup-callback-at"
                  type="datetime-local"
                  required
                  min={istNowLocal()}
                  value={callbackAt}
                  onChange={(e) => setCallbackAt(e.target.value)}
                  className={fieldClass}
                />
              </div>
              <div>
                <label htmlFor="wrapup-callback-reason" className={labelClass}>
                  About
                </label>
                <SelectField
                  id="wrapup-callback-reason"
                  aria-label="Callback reason"
                  value={callbackReason}
                  onChange={(v) => setCallbackReason(v as CbReason)}
                  size="compact"
                  className="mt-050"
                  options={(Object.keys(REASON_LABELS) as CbReason[]).map((r) => ({
                    value: r,
                    label: REASON_LABELS[r],
                  }))}
                />
              </div>
            </div>
          )}

          {needs === "dispute" && !blocked && (
            <div className="mt-100">
              <label htmlFor="wrapup-dispute-type" className={labelClass}>
                Dispute type
              </label>
              <SelectField
                id="wrapup-dispute-type"
                aria-label="Dispute type"
                value={disputeType}
                onChange={(v) => setDisputeType(v as DisputeType)}
                size="compact"
                className="mt-050"
                placeholder="Choose a type"
                options={(Object.keys(TYPE_LABELS) as DisputeType[]).map((t) => ({
                  value: t,
                  label: TYPE_LABELS[t],
                }))}
              />
            </div>
          )}
        </div>

        <div>
          <label htmlFor="wrapup-notes" className={labelClass}>
            Notes{needs === "notes" ? " (required)" : ""}
          </label>
          <textarea
            id="wrapup-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            placeholder={
              label === "Customer says they paid"
                ? "The payment reference the customer gave (UTR, date, amount)"
                : undefined
            }
            className="mt-050 w-full resize-none rounded-medium border border-border bg-surface px-100 py-075 text-body-small text-text focus:border-border-brand focus:outline-none"
          />
          {error ? (
            <p role="alert" className="mt-050 text-body-small text-text-danger">
              {error}
            </p>
          ) : null}
        </div>

        <div className="flex items-end">
          <button
            type="submit"
            disabled={saving || !valid}
            className="flex h-400 items-center gap-075 rounded-medium bg-background-brand-bold px-150 text-body-small font-semibold text-text-inverse hover:bg-background-brand-bold-hovered disabled:opacity-60"
          >
            <Save className="h-3.5 w-3.5" />
            {saving ? "Saving…" : "Save wrap-up"}
          </button>
        </div>
      </form>
    </section>
  );
}
