import { Bell, BellOff, HandCoins, MessageCircle, PhoneCall } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Customer, Promise, PtpStatus } from "@/data/customer360-seed";
import { fmtDate, fmtMoney } from "@/data/customer360-seed";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<PtpStatus, string> = {
  upcoming: "bg-brand-tint text-brand-primary-dark border-brand-primary/20",
  kept: "bg-success-bg text-success border-success/20",
  broken: "bg-danger-bg text-danger border-danger/20",
  partial: "bg-warning-bg text-warning border-warning/20",
};

function daysUntil(iso: string) {
  const d = Math.round((new Date(iso).getTime() - Date.now()) / 86400_000);
  if (d > 0) return `in ${d}d`;
  if (d === 0) return "today";
  return `${Math.abs(d)}d ago`;
}

export function PromisesTab({ customer, onCreate }: { customer: Customer; onCreate: () => void }) {
  const total = customer.promises.length || 1;
  const kept = customer.promises.filter((p) => p.status === "kept").length;
  const active = customer.promises.filter((p) => p.status === "upcoming").reduce((s, p) => s + p.amount, 0);
  const atRisk = customer.promises.filter((p) => p.status === "broken").reduce((s, p) => s + p.amount, 0);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Metric label="PTP-kept rate" value={`${((kept / total) * 100).toFixed(0)}%`} tone="brand" />
        <Metric label="$ Active" value={fmtMoney(active)} />
        <Metric label="$ Broken" value={fmtMoney(atRisk)} tone="danger" />
        <div className="flex items-end">
          <Button onClick={onCreate} className="w-full">
            <HandCoins className="h-3.5 w-3.5" />
            Create PTP
          </Button>
        </div>
      </div>

      {customer.promises.length === 0 ? (
        <Empty onCreate={onCreate} />
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
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
    <div className="rounded-lg border border-border bg-surface-card p-4">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-xs uppercase tracking-wide text-text-secondary">Amount</div>
          <div className="text-xl font-semibold text-brand-navy tabular">{fmtMoney(p.amount)}</div>
        </div>
        <span className={cn("rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase", STATUS_TONE[p.status])}>{p.status}</span>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
        <Field label="Promised for" value={fmtDate(p.promisedDate)} sub={daysUntil(p.promisedDate)} />
        <Field label="Captured by" value={p.handler} sub={fmtDate(p.createdAt)} />
      </div>
      <div className="mt-3 flex items-center justify-between border-t border-border pt-3 text-[11px] text-text-secondary">
        <span className="inline-flex items-center gap-1">
          <ChannelIcon className="h-3 w-3" />
          via {p.channel}
        </span>
        <span className="inline-flex items-center gap-1 capitalize">
          <Reminder className="h-3 w-3" />
          Reminder {p.reminderStatus}
        </span>
      </div>
    </div>
  );
}

function Metric({ label, value, tone = "default" }: { label: string; value: string; tone?: "default" | "brand" | "danger" }) {
  const t = tone === "brand" ? "text-brand-primary" : tone === "danger" ? "text-danger" : "text-brand-navy";
  return (
    <div className="rounded-lg border border-border bg-surface-card p-3">
      <div className="text-[11px] uppercase tracking-wide text-text-secondary">{label}</div>
      <div className={cn("mt-0.5 text-lg font-semibold tabular", t)}>{value}</div>
    </div>
  );
}

function Field({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-text-muted">{label}</div>
      <div className="text-sm font-medium text-text-primary">{value}</div>
      {sub && <div className="text-[10px] text-text-muted tabular">{sub}</div>}
    </div>
  );
}

function Empty({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-border bg-surface-card p-10 text-center">
      <HandCoins className="h-8 w-8 text-brand-primary" />
      <div>
        <div className="text-sm font-semibold text-brand-navy">No promise-to-pay yet</div>
        <div className="text-xs text-text-secondary">Capture a commitment during your next call.</div>
      </div>
      <Button onClick={onCreate}>Create PTP</Button>
    </div>
  );
}
