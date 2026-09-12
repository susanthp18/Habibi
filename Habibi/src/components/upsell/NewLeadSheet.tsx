import { useEffect, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { X } from "lucide-react";
import type { LeadSource, Priority, Team } from "@/api/types/upsell";
import { createLead, leadCustomerOptions, leadOwnerOptions, leadTeamOptions } from "@/api/upsell";
import { useProducts } from "@/api/products";
import { useTeams } from "@/api/teams";
import { useCustomers } from "@/api/customers";
import { useStaff } from "@/api/staff";
import { useMe } from "@/api/me";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { SelectField } from "@/components/ui/select";

const SOURCE_OPTIONS = [
  { value: "agent", label: "Agent" },
  { value: "bot_voice", label: "Bot · Voice" },
  { value: "bot_chat", label: "Bot · Chat" },
];
const PRIORITY_OPTIONS = [
  { value: "high", label: "High" },
  { value: "normal", label: "Normal" },
  { value: "low", label: "Low" },
];

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

  const customers = useMemo(() => leadCustomerOptions(liveCustomers), [liveCustomers]);

  const owners = useMemo(() => leadOwnerOptions(staff), [staff]);
  // Catalog and queues from the DB — a picker must never offer an id the
  // server has not heard of.
  const { data: catalog = [] } = useProducts();
  const { data: teams = [] } = useTeams();
  const productOptions = catalog;
  const teamOptions = useMemo(() => leadTeamOptions(teams), [teams]);

  const [customerId, setCustomerId] = useState(customers[0]?.id ?? "");
  const [productId, setProductId] = useState("");
  const [amount, setAmount] = useState("");
  useEffect(() => {
    const first = productOptions[0];
    if (!productId && first) {
      setProductId(first.id);
      setAmount(String(first.minTicket * 2));
    }
  }, [productId, productOptions]);
  const [team, setTeam] = useState<Team>("Retail Sales");
  const [owner, setOwner] = useState(me?.name ?? "");
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
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : "Lead creation failed"),
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
            <h2 className="text-body font-semibold text-text">New lead</h2>
            <p className="text-body-small text-text-subtle">
              Capture an upsell opportunity manually.
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded p-050 text-text-subtlest hover:bg-surface-sunken"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-150 overflow-y-auto p-200">
          <div>
            <div className="mb-050 text-body-small font-semibold text-text-subtlest">Customer</div>
            <SelectField
              aria-label="Customer"
              value={customerId}
              onChange={setCustomerId}
              size="compact"
              options={customers.map((c) => ({ value: c.id, label: `${c.name} · #${c.tail}` }))}
            />
          </div>

          <div className="grid grid-cols-2 gap-100">
            <div className="col-span-2">
              <div className="mb-050 text-body-small font-semibold text-text-subtlest">Product</div>
              <SelectField
                aria-label="Product"
                value={productId}
                onChange={(v) => {
                  setProductId(v);
                  const p = productOptions.find((x) => x.id === v);
                  if (p) setAmount(String(p.minTicket * 2));
                }}
                size="compact"
                options={productOptions.map((p) => ({
                  value: p.id,
                  label: `${p.name} · ${p.indicativeROI}`,
                }))}
              />
            </div>
            <div>
              <div className="mb-050 text-body-small font-semibold text-text-subtlest">
                Indicative amount (₹)
              </div>
              <Input value={amount} onChange={(e) => setAmount(e.target.value)} size="compact" />
            </div>
            <div>
              <div className="mb-050 text-body-small font-semibold text-text-subtlest">Source</div>
              <SelectField
                aria-label="Source"
                value={source}
                onChange={(v) => setSource(v as LeadSource)}
                size="compact"
                options={SOURCE_OPTIONS}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-100">
            <div>
              <div className="mb-050 text-body-small font-semibold text-text-subtlest">Team</div>
              <SelectField
                aria-label="Team"
                value={team}
                onChange={(v) => setTeam(v as Team)}
                size="compact"
                options={teamOptions.map((t) => ({ value: t, label: t }))}
              />
            </div>
            <div>
              <div className="mb-050 text-body-small font-semibold text-text-subtlest">Owner</div>
              <SelectField
                aria-label="Owner"
                value={owner}
                onChange={setOwner}
                size="compact"
                options={owners.map((o) => ({ value: o, label: o }))}
              />
            </div>
          </div>

          <div>
            <div className="mb-050 text-body-small font-semibold text-text-subtlest">Priority</div>
            <SelectField
              aria-label="Priority"
              value={priority}
              onChange={(v) => setPriority(v as Priority)}
              size="compact"
              options={PRIORITY_OPTIONS}
            />
          </div>

          <div>
            <div className="mb-050 text-body-small font-semibold text-text-subtlest">
              Capture note
            </div>
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
