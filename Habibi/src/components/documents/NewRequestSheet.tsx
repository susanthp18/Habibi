import { useMemo, useState } from "react";
import { toast } from "sonner";
import { X, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import {
  CHANNEL_LABELS,
  DOC_TYPE_LABELS,
  templatesFor,
  type DocChannel,
  type DocType,
} from "@/data/documents-seed";
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
      <aside className="flex h-full w-full max-w-[440px] flex-col bg-surface-card shadow-xl">
        <div className="shrink-0 flex items-center justify-between border-b border-[var(--border-token)] px-4 py-3">
          <div>
            <h2 className="text-[15px] font-semibold text-brand-navy">New document request</h2>
            <p className="text-[11px] text-text-muted">Raise a fulfilment task for a customer.</p>
          </div>
          <Button size="icon" variant="ghost" className="h-7 w-7" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3 space-y-3">
          <Field label="Customer">
            <select
              value={customerId}
              onChange={(e) => setCustomerId(e.target.value)}
              disabled={!pool.length || busy}
              className="h-9 w-full rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[13px]"
            >
              {!pool.length && <option value="">Loading customers…</option>}
              {pool.map((c) => (
                <option key={c.id} value={c.id}>{c.name} · {c.accountId}</option>
              ))}
            </select>
          </Field>

          <Field label="Document type">
            <select
              value={docType}
              disabled={busy}
              onChange={(e) => {
                const t = e.target.value as DocType;
                setDocType(t);
                setTemplateId(templatesFor(t)[0]?.id ?? "");
              }}
              className="h-9 w-full rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[13px]"
            >
              {(Object.keys(DOC_TYPE_LABELS) as DocType[]).map((t) => (
                <option key={t} value={t}>{DOC_TYPE_LABELS[t]}</option>
              ))}
            </select>
          </Field>

          <Field label="Template">
            <select
              value={templateId}
              disabled={busy}
              onChange={(e) => setTemplateId(e.target.value)}
              className="h-9 w-full rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[13px]"
            >
              {templates.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </Field>

          <Field label="Period (optional)">
            <Input
              value={period}
              disabled={busy}
              onChange={(e) => setPeriod(e.target.value)}
              placeholder="e.g. May–Oct 2026"
              className="h-9 text-[13px]"
            />
          </Field>

          <Field label="Delivery channel">
            <div className="flex gap-1.5">
              {(Object.keys(CHANNEL_LABELS) as DocChannel[]).map((c) => (
                <button
                  key={c}
                  disabled={busy}
                  onClick={() => setChannel(c)}
                  className={cn(
                    "flex-1 rounded-md border px-2 py-1.5 text-[12px]",
                    channel === c
                      ? "border-brand-primary bg-brand-tint text-brand-primary-dark font-semibold"
                      : "border-[var(--border-token)] bg-surface-card text-text-secondary hover:bg-surface-sunken",
                  )}
                >
                  {CHANNEL_LABELS[c]}
                </button>
              ))}
            </div>
          </Field>
        </div>

        <div className="shrink-0 flex justify-end gap-2 border-t border-[var(--border-token)] px-4 py-2.5">
          <Button size="sm" variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button size="sm" onClick={() => void submit()} disabled={busy || !pool.length}>
            <Send className="mr-1 h-3.5 w-3.5" /> Create request
          </Button>
        </div>
      </aside>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10.5px] font-semibold uppercase tracking-wide text-text-muted">{label}</div>
      <div className="mt-1">{children}</div>
    </div>
  );
}
