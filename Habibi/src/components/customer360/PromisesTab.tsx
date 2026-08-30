import { Bell, BellOff, HandCoins, MessageCircle, PhoneCall } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Customer, Promise } from "@/data/customer360-seed";
import { fmtDate, fmtMoney } from "@/data/customer360-seed";
import { StatusChip, ptpStatusTone } from "./StatusChip";
import { cn } from "@/lib/utils";

function daysUntil(iso: string) {
  const d = Math.round((new Date(iso).getTime() - Date.now()) / 86400_000);
  if (d > 0) return `in ${d}d`;
  if (d === 0) return "today";
  return `${Math.abs(d)}d ago`;
}

export function PromisesTab({ customer, onCreate }: { customer: Customer; onCreate: () => void }) {
  const settled = customer.promises.filter((p) => p.status === "kept" || p.status === "broken");
  const kept = customer.promises.filter((p) => p.status === "kept").length;
  const keepRate = settled.length ? Math.round((kept / settled.length) * 100) : null;
  const active = customer.promises
    .filter((p) => p.status === "upcoming")
    .reduce((s, p) => s + p.amount, 0);
  const atRisk = customer.promises
    .filter((p) => p.status === "broken")
    .reduce((s, p) => s + p.amount, 0);

  return (
    <div className="space-y-200">
      <div className="grid grid-cols-2 gap-150 md:grid-cols-3">
        <Metric
          label="PTP-kept rate"
          value={keepRate !== null ? `${keepRate}%` : "—"}
          tone="brand"
        />
        <Metric label="$ Active" value={fmtMoney(active)} />
        <Metric label="$ Broken" value={fmtMoney(atRisk)} tone="danger" />
      </div>

      {customer.promises.length === 0 ? (
        <Empty onCreate={onCreate} />
      ) : (
        <div className="grid gap-150 md:grid-cols-2">
          {customer.promises.map((p) => (
            <PromiseCard key={p.id} p={p} />
          ))}
        </div>
      )}
    </div>
  );
}

function PromiseCard({ p }: { p: Promise }) {
  const ChannelIcon = p.channel === "voice" ? PhoneCall : MessageCircle;
  const Reminder = p.reminderStatus === "off" ? BellOff : Bell;
  return (
    <div className="rounded-large border border-border bg-surface p-200">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-xs text-text-subtle">Amount</div>
          <div className="text-xl font-semibold text-text tabular">{fmtMoney(p.amount)}</div>
        </div>
        <StatusChip label={p.status} tone={ptpStatusTone(p.status)} />
      </div>
      <div className="mt-150 grid grid-cols-2 gap-100 text-xs">
        <Field
          label="Promised for"
          value={fmtDate(p.promisedDate)}
          sub={daysUntil(p.promisedDate)}
        />
        <Field label="Captured by" value={p.handler} sub={fmtDate(p.createdAt)} />
      </div>
      <div className="mt-150 flex items-center justify-between border-t border-border pt-150 text-body-small text-text-subtle">
        <span className="inline-flex items-center gap-050">
          <ChannelIcon className="h-3 w-3" />
          via {p.channel}
        </span>
        <span className="inline-flex items-center gap-050 capitalize">
          <Reminder className="h-3 w-3" />
          Reminder {p.reminderStatus}
        </span>
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string;
  tone?: "default" | "brand" | "danger";
}) {
  const t =
    tone === "brand" ? "text-text-brand" : tone === "danger" ? "text-text-danger" : "text-text";
  return (
    <div className="rounded-large border border-border bg-surface p-150">
      <div className="text-body-small text-text-subtle">{label}</div>
      <div className={cn("mt-025 text-lg font-semibold tabular", t)}>{value}</div>
    </div>
  );
}

function Field({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div>
      <div className="text-body-small text-text-subtlest">{label}</div>
      <div className="text-sm font-medium text-text">{value}</div>
      {sub && <div className="text-body-small text-text-subtlest tabular">{sub}</div>}
    </div>
  );
}

function Empty({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="flex flex-col items-center gap-150 rounded-large border border-dashed border-border bg-surface p-500 text-center">
      <HandCoins className="h-400 w-400 text-text-brand" />
      <div>
        <div className="text-sm font-semibold text-text">No promise-to-pay yet</div>
        <div className="text-xs text-text-subtle">Capture a commitment during your next call.</div>
      </div>
      <Button
        size="sm"
        className="bg-background-brand-bold hover:bg-background-brand-bold-hovered"
        onClick={onCreate}
      >
        Create PTP
      </Button>
    </div>
  );
}
