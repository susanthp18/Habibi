import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { X } from "lucide-react";
import {
  CURRENT_AGENT,
  TEAM_OPTIONS,
  listCustomers,
  listOwners,
  products,
  type LeadSource,
  type Priority,
  type Team,
} from "@/data/upsell-seed";
import { createLead } from "@/api/upsell";
import { useCustomers } from "@/api/customers";
import { humanNames, useStaff } from "@/api/staff";
import { useMe } from "@/api/me";
import { USE_MOCK } from "@/api/config";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

interface Props {
  onClose: () => void;
  onCreated: () => void;
}

export function NewLeadSheet({ onClose, onCreated }: Props) {
  // Live: real customers/staff from the DB so the picker can't offer an id that
  // doesn't exist. Mock: the seed rosters, unchanged.
  const { data: liveCustomers = [] } = useCustomers();
  const { data: staff = [] } = useStaff();
  const { data: me } = useMe();

  const customers = useMemo(() => {
    if (USE_MOCK) return listCustomers();
    return liveCustomers.map((c) => ({
      id: c.id,
      name: c.name,
      accountId: c.accountId,
      tail: c.accountId.slice(-4),
    }));
  }, [liveCustomers]);

  const owners = useMemo(
    () => (USE_MOCK ? listOwners() : [...humanNames(staff), "Unassigned"]),
    [staff],
  );

  const [customerId, setCustomerId] = useState(customers[0]?.id ?? "");
  const [productId, setProductId] = useState(products[0].id);
  const [amount, setAmount] = useState(String(products[0].minTicket * 2));
  const [team, setTeam] = useState<Team>("Retail Sales");
  const [owner, setOwner] = useState(me?.name ?? CURRENT_AGENT);
  const [source, setSource] = useState<LeadSource>("agent");
  const [priority, setPriority] = useState<Priority>("normal");
  const [note, setNote] = useState("");
  const createMutation = useMutation({
    mutationFn: createLead,
    onSuccess: () => {
      toast.success("Lead created in Interested");
      onCreated();
      onClose();
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Lead creation failed"),
  });

  const submit = () => {
    const n = Number(amount);
    if (!n || n <= 0) {
      toast.error("Enter a valid amount");
      return;
    }
    if (!note.trim()) {
      toast.error("Add a short capture note");
      return;
    }
    createMutation.mutate({
      customerId,
      productId,
      indicativeAmount: n,
      team,
      owner,
      source,
      priority,
      note: note.trim(),
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex h-full w-full max-w-[480px] flex-col bg-surface-card shadow-2xl"
      >
        <div className="shrink-0 flex items-center justify-between border-b border-[var(--border-token)] p-4">
          <div>
            <h2 className="text-[15px] font-semibold text-brand-navy">New lead</h2>
            <p className="text-[11.5px] text-text-secondary">Capture an upsell opportunity manually.</p>
          </div>
          <button onClick={onClose} className="rounded p-1 text-text-muted hover:bg-surface-sunken">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
          <div>
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">Customer</div>
            <select
              value={customerId}
              onChange={(e) => setCustomerId(e.target.value)}
              className="h-8 w-full rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
            >
              {customers.map((c) => (
                <option key={c.id} value={c.id}>{c.name} · #{c.tail}</option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div className="col-span-2">
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">Product</div>
              <select
                value={productId}
                onChange={(e) => {
                  setProductId(e.target.value);
                  const p = products.find((x) => x.id === e.target.value);
                  if (p) setAmount(String(p.minTicket * 2));
                }}
                className="h-8 w-full rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
              >
                {products.map((p) => (
                  <option key={p.id} value={p.id}>{p.name} · {p.indicativeROI}</option>
                ))}
              </select>
            </div>
            <div>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">Indicative amount (₹)</div>
              <Input value={amount} onChange={(e) => setAmount(e.target.value)} className="h-8 text-[12px]" />
            </div>
            <div>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">Source</div>
              <select
                value={source}
                onChange={(e) => setSource(e.target.value as LeadSource)}
                className="h-8 w-full rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
              >
                <option value="agent">Agent</option>
                <option value="bot_voice">Bot · Voice</option>
                <option value="bot_chat">Bot · Chat</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">Team</div>
              <select
                value={team}
                onChange={(e) => setTeam(e.target.value as Team)}
                className="h-8 w-full rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
              >
                {TEAM_OPTIONS.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
            <div>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">Owner</div>
              <select
                value={owner}
                onChange={(e) => setOwner(e.target.value)}
                className="h-8 w-full rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
              >
                {owners.map((o) => (
                  <option key={o} value={o}>{o}</option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">Priority</div>
            <select
              value={priority}
              onChange={(e) => setPriority(e.target.value as Priority)}
              className="h-8 w-full rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
            >
              <option value="high">High</option>
              <option value="normal">Normal</option>
              <option value="low">Low</option>
            </select>
          </div>

          <div>
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">Capture note</div>
            <Textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={3}
              placeholder="Why is this customer interested? Any key details."
              className="text-[12px]"
            />
          </div>
        </div>

        <div className="shrink-0 flex items-center justify-end gap-2 border-t border-[var(--border-token)] bg-surface-sunken/40 p-3">
          <Button size="sm" variant="ghost" className="h-8" onClick={onClose}>
            Cancel
          </Button>
          <Button size="sm" className="h-8" onClick={submit}>
            Create lead
          </Button>
        </div>
      </div>
    </div>
  );
}
