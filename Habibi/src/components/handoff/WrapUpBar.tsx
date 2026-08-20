import { useState } from "react";
import { CheckCircle2, FileText, Save, X } from "lucide-react";
import type { WrapUpPayload } from "@/api/handoff";

type Props = {
  open: boolean;
  dispositions: string[];
  onClose: () => void;
  onSave: (payload: WrapUpPayload) => void;
  saved: boolean;
  saving?: boolean;
  defaultNotes?: string;
  defaultPtpAmount?: number;
  error?: string | null;
};

export function WrapUpBar({
  open,
  dispositions,
  onClose,
  onSave,
  saved,
  saving,
  defaultNotes = "",
  defaultPtpAmount,
  error,
}: Props) {
  const [disposition, setDisposition] = useState(dispositions[0] ?? "");
  const [notes, setNotes] = useState(defaultNotes);
  const [ptp, setPtp] = useState(false);
  const [ptpAmount, setPtpAmount] = useState(
    defaultPtpAmount ? String(defaultPtpAmount) : "",
  );
  const [ptpDate, setPtpDate] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() + 7);
    return d.toISOString().slice(0, 10);
  });

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
              Disposition <span className="font-semibold">{disposition}</span>
              {ptp ? " · PTP flagged for tracking" : ""} · summary written to Audit Trail.
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
          {ptp && (
            <div className="mt-075 grid grid-cols-2 gap-075">
              <input
                type="number"
                min={1}
                value={ptpAmount}
                onChange={(e) => setPtpAmount(e.target.value)}
                placeholder="Amount"
                className="h-400 rounded-medium border border-border bg-surface px-100 text-body-small text-text"
              />
              <input
                type="date"
                value={ptpDate}
                onChange={(e) => setPtpDate(e.target.value)}
                className="h-400 rounded-medium border border-border bg-surface px-100 text-body-small text-text"
              />
            </div>
          )}
        </div>

        <div>
          <label className="text-body-small font-medium text-text-subtle">Notes (CRM writeback)</label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            className="mt-050 w-full resize-none rounded-medium border border-border bg-surface px-100 py-075 text-body-small text-text focus:border-border-brand focus:outline-none"
          />
          {error ? <p className="mt-050 text-body-small text-text-danger">{error}</p> : null}
        </div>

        <div className="flex items-end">
          <button
            type="button"
            disabled={saving || (ptp && (!ptpAmount || !ptpDate))}
            onClick={() =>
              onSave({
                disposition,
                notes,
                ptp,
                ptpAmount: ptp ? Number(ptpAmount) : undefined,
                ptpDate: ptp ? ptpDate : undefined,
              })
            }
            className="flex h-400 items-center gap-075 rounded-medium bg-background-brand-bold px-150 text-body-small font-semibold text-white hover:bg-background-brand-bold-hovered disabled:opacity-60"
          >
            <Save className="h-3.5 w-3.5" />
            {saving ? "Saving…" : "Save & writeback"}
          </button>
        </div>
      </div>
    </div>
  );
}
