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
      <div className="shrink-0 border-t border-[var(--border-token)] bg-success-bg px-5 py-3">
        <div className="flex items-center gap-3">
          <CheckCircle2 className="h-5 w-5 text-success" />
          <div className="flex-1">
            <div className="text-[13px] font-semibold text-success">
              Wrap-up saved · pushed to CRM
            </div>
            <div className="text-[11px] text-text-secondary">
              Disposition <span className="font-semibold">{disposition}</span> · PTP flagged for
              tracking · summary written to Audit Trail.
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-[11px] font-semibold text-text-secondary hover:text-text-primary"
          >
            Dismiss
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="shrink-0 border-t border-[var(--border-token)] bg-surface-card px-5 py-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-[12px] font-semibold text-brand-navy">
          <FileText className="h-3.5 w-3.5 text-brand-primary" />
          Post-call wrap-up
        </div>
        <button
          type="button"
          onClick={onClose}
          className="grid h-6 w-6 place-items-center rounded-md text-text-muted hover:bg-surface-sunken"
          aria-label="Close wrap-up"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="grid gap-3 md:grid-cols-[220px_1fr_auto]">
        <div>
          <label className="text-[11px] font-medium text-text-secondary">Disposition</label>
          <select
            value={disposition}
            onChange={(e) => setDisposition(e.target.value)}
            className="mt-1 h-8 w-full rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px] text-text-primary focus:border-brand-primary focus:outline-none"
          >
            {dispositions.map((d) => (
              <option key={d}>{d}</option>
            ))}
          </select>
          <label className="mt-2 flex items-center gap-1.5 text-[11px] text-text-secondary">
            <input
              type="checkbox"
              checked={ptp}
              onChange={(e) => setPtp(e.target.checked)}
              className="h-3.5 w-3.5 accent-[var(--brand-primary)]"
            />
            Log Promise-to-Pay
          </label>
        </div>

        <div>
          <label className="text-[11px] font-medium text-text-secondary">Notes (CRM writeback)</label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            className="mt-1 w-full resize-none rounded-md border border-[var(--border-token)] bg-surface-card px-2 py-1.5 text-[12px] text-text-primary focus:border-brand-primary focus:outline-none"
          />
        </div>

        <div className="flex items-end">
          <button
            type="button"
            onClick={() => onSave({ disposition, notes, ptp })}
            className="flex h-8 items-center gap-1.5 rounded-md bg-brand-primary px-3 text-[12px] font-semibold text-white hover:bg-brand-primary-hover"
          >
            <Save className="h-3.5 w-3.5" />
            Save & writeback
          </button>
        </div>
      </div>
    </div>
  );
}
