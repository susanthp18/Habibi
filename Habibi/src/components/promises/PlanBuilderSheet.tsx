import { useEffect, useMemo, useState } from "react";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  buildSchedule,
  fmtDate,
  fmtMoney,
  listCustomerSlim,
  type PlanCadence,
} from "@/data/promises-seed";
import type { CustomerOption } from "./PromiseSheet";

export interface PlanInput {
  customerId: string;
  customerName: string;
  accountTail: string;
  total: number;
  installments: number;
  startDate: string;
  cadence: PlanCadence;
  owner: string;
}

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onSubmit: (input: PlanInput) => void;
  owners: string[];
  /** Real customers to pick from (live mode). Falls back to seed roster when omitted. */
  customers?: CustomerOption[];
}

const startDefault = () => {
  const d = new Date();
  d.setDate(d.getDate() + 7);
  return d.toISOString().slice(0, 10);
};

export function PlanBuilderSheet({ open, onOpenChange, onSubmit, owners, customers: customersProp }: Props) {
  const customers = useMemo<CustomerOption[]>(
    () => (customersProp && customersProp.length ? customersProp : listCustomerSlim()),
    [customersProp],
  );
  const [customerId, setCustomerId] = useState(customers[0]?.id ?? "");
  const [total, setTotal] = useState("30000");
  const [installments, setInstallments] = useState(4);
  const [cadence, setCadence] = useState<PlanCadence>("monthly");
  const [startDate, setStartDate] = useState(startDefault());
  const [owner, setOwner] = useState(owners[0] ?? "AI Bot");

  useEffect(() => {
    if (open) {
      const c = customers[0];
      if (c) {
        setCustomerId(c.id);
        setTotal(String(Math.max(20000, Math.round((c.outstanding || 30000) / 100) * 100)));
      }
      setInstallments(4);
      setCadence("monthly");
      setStartDate(startDefault());
      setOwner(owners[0] ?? "AI Bot");
    }
  }, [open, customers, owners]);

  const cust = customers.find((c) => c.id === customerId);
  useEffect(() => {
    if (cust) setTotal(String(Math.max(15000, Math.round((cust.outstanding || 30000) / 100) * 100)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerId]);

  const totalN = Number(total) || 0;
  const schedule = useMemo(
    () => (totalN > 0 ? buildSchedule({ total: totalN, installments, startDate: new Date(`${startDate}T10:00:00`).toISOString(), cadence }) : []),
    [totalN, installments, startDate, cadence],
  );

  const submit = () => {
    if (!cust || totalN <= 0) return;
    onSubmit({
      customerId: cust.id,
      customerName: cust.name,
      accountTail: cust.accountId.slice(-4),
      total: totalN,
      installments,
      startDate: new Date(`${startDate}T10:00:00`).toISOString(),
      cadence,
      owner,
    });
    onOpenChange(false);
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-[37.5rem]">
        <SheetHeader>
          <SheetTitle>Build payment plan</SheetTitle>
          <SheetDescription>Split the outstanding into installments. First installment auto-becomes a promise.</SheetDescription>
        </SheetHeader>

        <div className="mt-200 space-y-150">
          <Field label="Customer">
            <Select value={customerId} onValueChange={setCustomerId}>
              <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
              <SelectContent className="max-h-[17.5rem]">
                {customers.map((c) => (
                  <SelectItem key={c.id} value={c.id}>{c.name} · #{c.accountId.slice(-4)}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            {cust && (
              <div className="mt-050 text-body-small text-text-subtlest">
                Outstanding on file: <span className="font-medium text-text">{fmtMoney(cust.outstanding)}</span>
              </div>
            )}
          </Field>

          <div className="grid grid-cols-2 gap-150">
            <Field label="Plan total (₹)">
              <Input type="number" value={total} onChange={(e) => setTotal(e.target.value)} className="h-9" />
            </Field>
            <Field label="Owner">
              <Select value={owner} onValueChange={setOwner}>
                <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {owners.map((o) => (<SelectItem key={o} value={o}>{o}</SelectItem>))}
                </SelectContent>
              </Select>
            </Field>
          </div>

          <Field label={`Installments · ${installments}`}>
            <Slider
              value={[installments]}
              min={2}
              max={12}
              step={1}
              onValueChange={([v]) => setInstallments(v)}
            />
          </Field>

          <div className="grid grid-cols-2 gap-150">
            <Field label="Start date">
              <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="h-9" />
            </Field>
            <Field label="Cadence">
              <Select value={cadence} onValueChange={(v) => setCadence(v as PlanCadence)}>
                <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="weekly">Weekly</SelectItem>
                  <SelectItem value="biweekly">Bi-weekly</SelectItem>
                  <SelectItem value="monthly">Monthly</SelectItem>
                </SelectContent>
              </Select>
            </Field>
          </div>

          <div className="rounded-large border border-border bg-surface-sunken/60 p-150">
            <div className="mb-100 flex items-center justify-between">
              <div className="text-body-small font-semibold text-text-subtlest">Preview schedule</div>
              <div className="text-body-small text-text-subtlest tabular-nums">
                {installments} × ≈{fmtMoney(Math.round(totalN / installments))}
              </div>
            </div>
            <ol className="max-h-[15rem] space-y-050 overflow-y-auto">
              {schedule.map((r) => (
                <li key={r.index} className="flex items-center justify-between rounded bg-surface px-100 py-075 text-body-small">
                  <span className="tabular-nums text-text-subtle">#{r.index}</span>
                  <span className="text-text">{fmtDate(r.dueDate)}</span>
                  <span className="tabular-nums font-medium text-text">{fmtMoney(r.amount)}</span>
                </li>
              ))}
            </ol>
          </div>
        </div>

        <div className="mt-300 flex justify-end gap-100">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={submit}>Create plan</Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-050">
      <Label className="text-body-small font-semibold text-text-subtlest">{label}</Label>
      {children}
    </div>
  );
}
