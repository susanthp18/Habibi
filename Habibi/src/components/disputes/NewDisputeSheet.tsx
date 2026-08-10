import { useEffect, useMemo, useState } from "react";
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

  useEffect(() => {
    setCustomerId((cur) => {
      if (pool.length === 0) return "";
      return pool.some((c) => c.id === cur) ? cur : pool[0]!.id;
    });
  }, [pool]);

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
      <aside className="flex h-full w-full max-w-[25rem] flex-col bg-surface shadow-overlay">
        <div className="flex shrink-0 items-center justify-between border-b border-border px-200 py-150">
          <div>
            <h2 className="text-[0.875rem] font-semibold text-text">Raise dispute</h2>
            <p className="text-body-small text-text-subtlest">Log an exception for review on the disputes board.</p>
          </div>
          <Button size="icon" variant="ghost" className="h-7 w-7" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="min-h-0 flex-1 space-y-150 overflow-y-auto p-200 text-body-small">
          <div>
            <div className="mb-050 text-body-small font-semibold text-text-subtlest">Customer</div>
            <select
              value={customerId}
              onChange={(e) => setCustomerId(e.target.value)}
              className="h-9 w-full rounded-medium border border-border bg-surface px-100"
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
            <div className="mb-050 text-body-small font-semibold text-text-subtlest">Type</div>
            <select
              value={type}
              onChange={(e) => setType(e.target.value as DisputeType)}
              className="h-9 w-full rounded-medium border border-border bg-surface px-100"
            >
              {TYPES.map((t) => (
                <option key={t} value={t}>
                  {TYPE_LABELS[t]}
                </option>
              ))}
            </select>
          </div>
          <div>
            <div className="mb-050 text-body-small font-semibold text-text-subtlest">Amount (₹)</div>
            <Input type="number" value={amount} onChange={(e) => setAmount(e.target.value)} className="h-9" />
          </div>
          <div>
            <div className="mb-050 text-body-small font-semibold text-text-subtlest">Notes</div>
            <Textarea
              rows={3}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="What the customer claimed…"
            />
          </div>
        </div>

        <div className="flex shrink-0 justify-end gap-100 border-t border-border px-200 py-150">
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
