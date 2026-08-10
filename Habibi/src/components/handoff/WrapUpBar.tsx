import { useState } from "react";
import { CheckCircle2, FileText, Save, X } from "lucide-react";

type Props = {
  open: boolean;
  dispositions: string[];
  onClose: () => void;
  onSave: (payload: { disposition: string; notes: string; ptp: boolean }) => void;
  saved: boolean;
};

export function WrapUpBar({ open, dispositions, onClose, onSave, saved }: Props) {
  const [disposition, setDisposition] = useState(dispositions[0]);
  const [notes, setNotes] = useState(
    "Payment gateway failure on 12 Jul confirmed — no debit. Dispute closed. PTP captured: ₹12,180 now + ₹36,540 by 31 Jul. Waiver ₹450 applied. Customer sentiment ended positive.",
  );
  const [ptp, setPtp] = useState(true);

  if (!open && !saved) return null;

  if (saved) {
    return (
      <div className="shrink-0 border-t border-border bg-background-success px-250 py-150">
        <div className="flex items-center gap-150">
          <CheckCircle2 className="h-250 w-250 text-text-success" />
          <div className="flex-1">
            <div className="text-body font-semibold text-text-success">
              Wrap-up saved · pushed to CRM
            </div>
            <div className="text-body-small text-text-subtle">
              Disposition <span className="font-semibold">{disposition}</span> · PTP flagged for
              tracking · summary written to Audit Trail.
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-body-small font-semibold text-text-subtle hover:text-text"
          >
            Dismiss
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="shrink-0 border-t border-border bg-surface px-250 py-150">
      <div className="mb-100 flex items-center justify-between">
        <div className="flex items-center gap-075 text-body-small font-semibold text-text">
          <FileText className="h-3.5 w-3.5 text-text-brand" />
          Post-call wrap-up
        </div>
        <button
          type="button"
          onClick={onClose}
          className="grid h-300 w-300 place-items-center rounded-medium text-text-subtlest hover:bg-surface-sunken"
          aria-label="Close wrap-up"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="grid gap-150 md:grid-cols-[220px_1fr_auto]">
        <div>
          <label className="text-body-small font-medium text-text-subtle">Disposition</label>
          <select
            value={disposition}
            onChange={(e) => setDisposition(e.target.value)}
            className="mt-050 h-400 w-full rounded-medium border border-border bg-surface px-100 text-body-small text-text focus:border-border-brand focus:outline-none"
          >
            {dispositions.map((d) => (
              <option key={d}>{d}</option>
            ))}
          </select>
          <label className="mt-100 flex items-center gap-075 text-body-small text-text-subtle">
            <input
              type="checkbox"
              checked={ptp}
              onChange={(e) => setPtp(e.target.checked)}
              className="h-3.5 w-3.5 accent-[var(--background-brand-bold)]"
            />
            Log Promise-to-Pay
          </label>
        </div>

        <div>
          <label className="text-body-small font-medium text-text-subtle">Notes (CRM writeback)</label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            className="mt-050 w-full resize-none rounded-medium border border-border bg-surface px-100 py-075 text-body-small text-text focus:border-border-brand focus:outline-none"
          />
        </div>

        <div className="flex items-end">
          <button
            type="button"
            onClick={() => onSave({ disposition, notes, ptp })}
            className="flex h-400 items-center gap-075 rounded-medium bg-background-brand-bold px-150 text-body-small font-semibold text-white hover:bg-background-brand-bold-hovered"
          >
            <Save className="h-3.5 w-3.5" />
            Save & writeback
          </button>
        </div>
      </div>
    </div>
  );
}
