import { useId, useMemo, useState } from "react";
import { bindControlId } from "@/components/ui/bind-control-id";
import { toast } from "sonner";
import { X, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SelectField } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import type { DocChannel, DocType } from "@/api/types/documents";
import { CHANNEL_LABELS, DOC_TYPE_LABELS, templatesFor } from "@/lib/documents";
import { createRequest } from "@/api/documents";

export interface DocumentCustomerOption {
  id: string;
  name: string;
  accountId: string;
}

interface Props {
  onClose: () => void;
  onCreated: () => void;
  /** Real customers from GET /customers — never the seed's synthetic EXTRA pool. */
  customers: DocumentCustomerOption[];
}

export function NewRequestSheet({ onClose, onCreated, customers }: Props) {
  const pool = customers;
  const [customerId, setCustomerId] = useState(pool[0]?.id ?? "");
  const [docType, setDocType] = useState<DocType>("account_statement");
  const [period, setPeriod] = useState("");
  const [channel, setChannel] = useState<DocChannel>("email");
  const templates = useMemo(() => templatesFor(docType), [docType]);
  const [templateId, setTemplateId] = useState(templates[0]?.id ?? "");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    const tpl = templateId || templates[0]?.id;
    if (!customerId) {
      toast.error("Pick a customer");
      return;
    }
    if (!tpl) {
      toast.error("Pick a template");
      return;
    }
    setBusy(true);
    try {
      await createRequest({
        customerId,
        docType,
        period: period.trim() || undefined,
        channel,
        templateId: tpl,
      });
      toast.success("Request created");
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
      <aside className="flex h-full w-full max-w-[25rem] flex-col bg-surface shadow-overlay">
        <div className="shrink-0 flex items-center justify-between border-b border-border px-200 py-150">
          <div>
            <h2 className="text-body font-semibold text-text">New document request</h2>
            <p className="text-body-small text-text-subtlest">
              Raise a fulfilment task for a customer.
            </p>
          </div>
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7"
            onClick={onClose}
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-200 py-150 space-y-150">
          <Field label="Customer">
            <SelectField
              value={customerId}
              onChange={setCustomerId}
              disabled={!pool.length || busy}
              placeholder={pool.length ? undefined : "Loading customers…"}
              options={pool.map((c) => ({ value: c.id, label: `${c.name} · ${c.accountId}` }))}
            />
          </Field>

          <Field label="Document type">
            <SelectField
              value={docType}
              disabled={busy}
              onChange={(v) => {
                const t = v as DocType;
                setDocType(t);
                setTemplateId(templatesFor(t)[0]?.id ?? "");
              }}
              options={(Object.keys(DOC_TYPE_LABELS) as DocType[]).map((t) => ({
                value: t,
                label: DOC_TYPE_LABELS[t],
              }))}
            />
          </Field>

          <Field label="Template">
            <SelectField
              value={templateId}
              disabled={busy}
              onChange={setTemplateId}
              options={templates.map((t) => ({ value: t.id, label: t.name }))}
            />
          </Field>

          <Field label="Period (optional)">
            <Input
              value={period}
              disabled={busy}
              onChange={(e) => setPeriod(e.target.value)}
              placeholder="e.g. May–Oct 2026"
            />
          </Field>

          <Field label="Delivery channel">
            <div className="flex gap-075">
              {(Object.keys(CHANNEL_LABELS) as DocChannel[]).map((c) => (
                <button
                  key={c}
                  disabled={busy}
                  onClick={() => setChannel(c)}
                  className={cn(
                    "flex-1 rounded-medium border px-100 py-075 text-body-small",
                    channel === c
                      ? "border-border-brand bg-background-brand-subtlest text-text-brand font-semibold"
                      : "border-border bg-surface text-text-subtle hover:bg-surface-sunken",
                  )}
                >
                  {CHANNEL_LABELS[c]}
                </button>
              ))}
            </div>
          </Field>
        </div>

        <div className="shrink-0 flex justify-end gap-100 border-t border-border px-200 py-150">
          <Button size="sm" variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button size="sm" onClick={() => void submit()} disabled={busy || !pool.length}>
            <Send className="mr-050 h-3.5 w-3.5" /> Create request
          </Button>
        </div>
      </aside>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  const id = useId();
  return (
    <div>
      <Label htmlFor={id} className="text-body-small font-semibold text-text-subtlest">
        {label}
      </Label>
      <div className="mt-050">{bindControlId(children, id, label)}</div>
    </div>
  );
}
