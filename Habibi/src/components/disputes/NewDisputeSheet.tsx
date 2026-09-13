import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Input } from "@/components/ui/input";
import { SelectField } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { DisputeType } from "@/api/types/disputes";
import { TYPE_LABELS } from "@/lib/disputes";
import { createDispute } from "@/api/disputes";
import { idempotencyKey } from "@/lib/utils";

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
  // One key for the life of the sheet: it closes on success.
  const submitKey = useRef(idempotencyKey("dispute"));

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
      const res = await createDispute(
        {
          customerId: selected.id,
          accountId: selected.accountId,
          type,
          amount: Number(amount) || 0,
          notes: notes.trim() || undefined,
        },
        submitKey.current,
      );
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
    <Sheet open onOpenChange={(next) => !next && onClose()}>
      <SheetContent
        hideClose
        aria-describedby={undefined}
        className="flex w-full flex-col gap-0 p-0 sm:max-w-[25rem]"
      >
        <SheetTitle className="sr-only">New dispute</SheetTitle>
        <div className="flex shrink-0 items-center justify-between border-b border-border px-200 py-150">
          <div>
            <h2 className="text-body font-semibold text-text">Raise dispute</h2>
            <p className="text-body-small text-text-subtlest">
              Log an exception for review on the disputes board.
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

        <div className="min-h-0 flex-1 space-y-150 overflow-y-auto p-200 text-body-small">
          <div>
            <div className="mb-050 text-body-small font-semibold text-text-subtlest">Customer</div>
            <SelectField
              aria-label="Customer"
              value={customerId}
              onChange={setCustomerId}
              disabled={pool.length === 0}
              placeholder={pool.length ? undefined : "No customers loaded"}
              size="compact"
              options={pool.map((c) => ({ value: c.id, label: `${c.name} · ${c.accountId}` }))}
            />
          </div>
          <div>
            <div className="mb-050 text-body-small font-semibold text-text-subtlest">Type</div>
            <SelectField
              aria-label="Type"
              value={type}
              onChange={(v) => setType(v as DisputeType)}
              size="compact"
              options={TYPES.map((t) => ({ value: t, label: TYPE_LABELS[t] }))}
            />
          </div>
          <div>
            <div className="mb-050 text-body-small font-semibold text-text-subtlest">
              Amount (₹)
            </div>
            <Input type="number" value={amount} onChange={(e) => setAmount(e.target.value)} />
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
      </SheetContent>
    </Sheet>
  );
}
