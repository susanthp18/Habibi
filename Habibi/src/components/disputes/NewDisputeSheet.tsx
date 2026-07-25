import { useMemo, useState } from "react";
import { toast } from "sonner";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { TYPE_LABELS, type DisputeType } from "@/data/disputes-seed";
import { createDispute } from "@/api/disputes";

export interface DisputeCustomerOption {
  id: string;
  name: string;
  accountId: string;
}

const TYPES = Object.keys(TYPE_LABELS) as DisputeType[];

interface Props {
  onClose: () => void;
  onCreated: () => void;
  customers: DisputeCustomerOption[];
}

export function NewDisputeSheet({ onClose, onCreated, customers }: Props) {
  const pool = customers;
  const [customerId, setCustomerId] = useState(pool[0]?.id ?? "");
  const [type, setType] = useState<DisputeType>("paid_already");
  const [amount, setAmount] = useState("0");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);

  const selected = useMemo(() => pool.find((c) => c.id === customerId), [pool, customerId]);

  const submit = async () => {
    if (!selected) {
      toast.error("Pick a customer");
      return;
    }
    if (busy) return;
    setBusy(true);
    try {
      const res = await createDispute({
        customerId: selected.id,
        customerName: selected.name,
        accountId: selected.accountId,
        type,
        amount: Number(amount) || 0,
        notes: notes.trim() || undefined,
      });
      toast.success(`Dispute raised · ${res.id}`);
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
      <button aria-label="Close overlay" type="button" onClick={onClose} className="flex-1 bg-black/30" />
      <aside className="flex h-full w-full max-w-[440px] flex-col bg-surface-card shadow-xl">
        <div className="flex shrink-0 items-center justify-between border-b border-[var(--border-token)] px-4 py-3">
          <div>
            <h2 className="text-[15px] font-semibold text-brand-navy">Raise dispute</h2>
            <p className="text-[11px] text-text-muted">Log an exception for review on the disputes board.</p>
          </div>
          <Button size="icon" variant="ghost" className="h-7 w-7" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4 text-[12.5px]">
          <div>
            <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-text-muted">Customer</div>
            <select
              value={customerId}
              onChange={(e) => setCustomerId(e.target.value)}
              className="h-9 w-full rounded-md border border-[var(--border-token)] bg-surface-app px-2"
            >
              {pool.length === 0 && <option value="">No customers loaded</option>}
              {pool.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} · {c.accountId}
                </option>
              ))}
            </select>
          </div>
          <div>
            <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-text-muted">Type</div>
            <select
              value={type}
              onChange={(e) => setType(e.target.value as DisputeType)}
              className="h-9 w-full rounded-md border border-[var(--border-token)] bg-surface-app px-2"
            >
              {TYPES.map((t) => (
                <option key={t} value={t}>
                  {TYPE_LABELS[t]}
                </option>
              ))}
            </select>
          </div>
          <div>
            <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-text-muted">Amount (₹)</div>
            <Input type="number" value={amount} onChange={(e) => setAmount(e.target.value)} className="h-9" />
          </div>
          <div>
            <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-text-muted">Notes</div>
            <Textarea
              rows={3}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="What the customer claimed…"
            />
          </div>
        </div>

        <div className="flex shrink-0 justify-end gap-2 border-t border-[var(--border-token)] px-4 py-3">
          <Button variant="outline" size="sm" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button size="sm" onClick={() => void submit()} disabled={busy || !customerId}>
            {busy ? "Saving…" : "Raise dispute"}
          </Button>
        </div>
      </aside>
    </div>
  );
}
