import { useEffect, useState } from "react";
import { FileUp } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Lozenge } from "@/components/ui/lozenge";
import { useApplyConsentImport, usePreviewConsentImport } from "@/api/consent";
import type {
  ConsentImportChange,
  ConsentImportResult,
  ConsentImportRow,
} from "@/api/types/consent";
import { MAX_CONSENT_IMPORT_ROWS, parseConsentCsv } from "@/lib/consent";

const PREVIEW_ROWS = 50;

const CHANGE_LABEL: Record<ConsentImportChange, string> = {
  none: "No change",
  opt_in: "Opt in",
  opt_out: "Opt out",
  dnd_on: "DND on",
  dnd_off: "DND off",
};

/**
 * CSV → dry run → apply. The browser only parses; the server validates every
 * row against the tenant and says what each would change before anything is
 * written, and applies the valid rows in one transaction.
 */
export function ConsentImportDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [fileName, setFileName] = useState("");
  const [rows, setRows] = useState<ConsentImportRow[] | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [preview, setPreview] = useState<ConsentImportResult | null>(null);
  const previewMutation = usePreviewConsentImport();
  const applyMutation = useApplyConsentImport();

  useEffect(() => {
    if (!open) {
      setFileName("");
      setRows(null);
      setParseError(null);
      setPreview(null);
    }
  }, [open]);

  const onFile = async (file: File | undefined) => {
    setPreview(null);
    setRows(null);
    setParseError(null);
    if (!file) return;
    setFileName(file.name);
    const parsed = parseConsentCsv(await file.text());
    if (parsed.error !== null) {
      setParseError(parsed.error);
      return;
    }
    setRows(parsed.rows);
    previewMutation.mutate(parsed.rows, { onSuccess: setPreview });
  };

  const pending = preview
    ? preview.changes.opt_in +
      preview.changes.opt_out +
      preview.changes.dnd_on +
      preview.changes.dnd_off
    : 0;
  // Errors first: they are what the operator has to act on.
  const shown = preview
    ? [...preview.results.filter((r) => !r.ok), ...preview.results.filter((r) => r.ok)].slice(
        0,
        PREVIEW_ROWS,
      )
    : [];

  const apply = () => {
    if (!rows) return;
    applyMutation.mutate(rows, { onSuccess: () => onOpenChange(false) });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Import consent CSV</DialogTitle>
          <DialogDescription>
            Columns: <code>customer_id</code>, <code>channel</code> (voice, whatsapp, sms, email),{" "}
            <code>status</code> (opted_in, opted_out), optional <code>purpose</code> (servicing,
            promotional — default servicing), <code>dnd</code> (true/false) and <code>note</code>.
            Up to {MAX_CONSENT_IMPORT_ROWS.toLocaleString()} rows. Nothing is written until you
            apply.
          </DialogDescription>
        </DialogHeader>

        <label className="flex cursor-pointer items-center gap-100 rounded-medium border border-dashed border-border bg-surface-sunken px-150 py-150 text-body-small text-text-subtle hover:bg-background-brand-subtlest">
          <FileUp className="h-4 w-4" />
          <span className="truncate">{fileName || "Choose a .csv file…"}</span>
          <input
            type="file"
            accept=".csv,text/csv"
            className="sr-only"
            onChange={(e) => {
              void onFile(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
        </label>

        {parseError ? (
          <p role="alert" className="text-body-small text-text-danger">
            {parseError}
          </p>
        ) : null}
        {previewMutation.isPending ? (
          <p className="text-body-small text-text-subtle">Validating {rows?.length ?? 0} rows…</p>
        ) : null}

        {preview ? (
          <div className="space-y-100">
            <div className="flex flex-wrap items-center gap-075 text-body-small">
              <Lozenge tone="success">{preview.valid} valid</Lozenge>
              {preview.invalid > 0 ? (
                <Lozenge tone="danger">{preview.invalid} invalid (skipped)</Lozenge>
              ) : null}
              <span className="text-text-subtle">
                {pending} change{pending === 1 ? "" : "s"}: {preview.changes.opt_in} opt-in ·{" "}
                {preview.changes.opt_out} opt-out · {preview.changes.dnd_on} DND on ·{" "}
                {preview.changes.dnd_off} DND off · {preview.changes.none} unchanged
              </span>
            </div>
            <div className="max-h-[22rem] overflow-auto rounded-medium border border-border">
              <table className="w-full text-body-small">
                <thead className="sticky top-0 bg-surface-sunken text-left text-text-subtlest">
                  <tr>
                    <th className="px-100 py-050">Row</th>
                    <th className="px-100 py-050">Customer</th>
                    <th className="px-100 py-050">Channel</th>
                    <th className="px-100 py-050">Status</th>
                    <th className="px-100 py-050">Purpose</th>
                    <th className="px-100 py-050">Result</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((r) => (
                    <tr
                      key={r.row}
                      className={
                        r.ok
                          ? "border-t border-border"
                          : "border-t border-border bg-[color:var(--danger-bg)] text-text-danger"
                      }
                    >
                      <td className="px-100 py-050 tabular">{r.row}</td>
                      <td className="px-100 py-050 font-mono">{r.customerId || "—"}</td>
                      <td className="px-100 py-050">{r.channel ?? "—"}</td>
                      <td className="px-100 py-050">{r.status ?? "—"}</td>
                      <td className="px-100 py-050">{r.purpose}</td>
                      <td className="px-100 py-050">
                        {r.ok
                          ? [
                              CHANGE_LABEL[r.change],
                              r.dndChange && r.dndChange !== r.change
                                ? CHANGE_LABEL[r.dndChange]
                                : null,
                            ]
                              .filter(Boolean)
                              .join(" + ")
                          : r.error}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {preview.total > shown.length ? (
              <p className="text-body-small text-text-subtlest">
                Showing {shown.length} of {preview.total} rows, invalid rows first.
              </p>
            ) : null}
          </div>
        ) : null}

        <DialogFooter>
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            size="sm"
            disabled={!preview || pending === 0 || applyMutation.isPending}
            onClick={apply}
          >
            {applyMutation.isPending
              ? "Applying…"
              : `Apply ${pending} change${pending === 1 ? "" : "s"}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
