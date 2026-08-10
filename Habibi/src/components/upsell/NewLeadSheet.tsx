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
import { useProducts } from "@/api/products";
import { teamNames, useTeams } from "@/api/teams";
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
  // Catalog and queues from the DB — a picker must never offer an id the
  // server has not heard of.
  const { data: catalog = [] } = useProducts();
  const { data: teams = [] } = useTeams();
  const productOptions = useMemo(
    () => (catalog.length > 0 ? catalog : products),
    [catalog],
  );
  const teamOptions = useMemo(
    () => (USE_MOCK ? TEAM_OPTIONS : teamNames(teams)),
    [teams],
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
        className="flex h-full w-full max-w-[25rem] flex-col bg-surface shadow-overlay"
      >
        <div className="shrink-0 flex items-center justify-between border-b border-border p-200">
          <div>
            <h2 className="text-[0.875rem] font-semibold text-text">New lead</h2>
            <p className="text-body-small text-text-subtle">Capture an upsell opportunity manually.</p>
          </div>
          <button onClick={onClose} className="rounded p-050 text-text-subtlest hover:bg-surface-sunken">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-150 overflow-y-auto p-200">
          <div>
            <div className="mb-050 text-body-small font-semibold text-text-subtlest">Customer</div>
            <select
              value={customerId}
              onChange={(e) => setCustomerId(e.target.value)}
              className="h-400 w-full rounded-medium border border-border bg-surface px-100 text-body-small"
            >
              {customers.map((c) => (
                <option key={c.id} value={c.id}>{c.name} · #{c.tail}</option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-100">
            <div className="col-span-2">
              <div className="mb-050 text-body-small font-semibold text-text-subtlest">Product</div>
              <select
                value={productId}
                onChange={(e) => {
                  setProductId(e.target.value);
                  const p = productOptions.find((x) => x.id === e.target.value);
                  if (p) setAmount(String(p.minTicket * 2));
                }}
                className="h-400 w-full rounded-medium border border-border bg-surface px-100 text-body-small"
              >
                {productOptions.map((p) => (
                  <option key={p.id} value={p.id}>{p.name} · {p.indicativeROI}</option>
                ))}
              </select>
            </div>
            <div>
              <div className="mb-050 text-body-small font-semibold text-text-subtlest">Indicative amount (₹)</div>
              <Input value={amount} onChange={(e) => setAmount(e.target.value)} className="h-400 text-body-small" />
            </div>
            <div>
              <div className="mb-050 text-body-small font-semibold text-text-subtlest">Source</div>
              <select
                value={source}
                onChange={(e) => setSource(e.target.value as LeadSource)}
                className="h-400 w-full rounded-medium border border-border bg-surface px-100 text-body-small"
              >
                <option value="agent">Agent</option>
                <option value="bot_voice">Bot · Voice</option>
                <option value="bot_chat">Bot · Chat</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-100">
            <div>
              <div className="mb-050 text-body-small font-semibold text-text-subtlest">Team</div>
              <select
                value={team}
                onChange={(e) => setTeam(e.target.value as Team)}
                className="h-400 w-full rounded-medium border border-border bg-surface px-100 text-body-small"
              >
                {TEAM_OPTIONS.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
            <div>
              <div className="mb-050 text-body-small font-semibold text-text-subtlest">Owner</div>
              <select
                value={owner}
                onChange={(e) => setOwner(e.target.value)}
                className="h-400 w-full rounded-medium border border-border bg-surface px-100 text-body-small"
              >
                {owners.map((o) => (
                  <option key={o} value={o}>{o}</option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <div className="mb-050 text-body-small font-semibold text-text-subtlest">Priority</div>
            <select
              value={priority}
              onChange={(e) => setPriority(e.target.value as Priority)}
              className="h-400 w-full rounded-medium border border-border bg-surface px-100 text-body-small"
            >
              <option value="high">High</option>
              <option value="normal">Normal</option>
              <option value="low">Low</option>
            </select>
          </div>

          <div>
            <div className="mb-050 text-body-small font-semibold text-text-subtlest">Capture note</div>
            <Textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={3}
              placeholder="Why is this customer interested? Any key details."
              className="text-body-small"
            />
          </div>
        </div>

        <div className="shrink-0 flex items-center justify-end gap-100 border-t border-border bg-surface-sunken/40 p-150">
          <Button size="sm" variant="ghost" className="h-400" onClick={onClose}>
            Cancel
          </Button>
          <Button size="sm" className="h-400" onClick={submit}>
            Create lead
          </Button>
        </div>
      </div>
    </div>
  );
}
