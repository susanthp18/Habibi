import { Download, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { Env, Period } from "@/data/billing-seed";
import { TENANTS } from "@/data/billing-seed";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

export function BillingHeader({
  period,
  onPeriod,
  tenantId,
  onTenant,
  env,
  onEnv,
}: {
  period: Period;
  onPeriod: (p: Period) => void;
  tenantId: string;
  onTenant: (id: string) => void;
  env: Env;
  onEnv: (e: Env) => void;
}) {
  return (
    <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-[var(--border-token)] bg-surface-card px-6 py-3">
      <div>
        <h1 className="text-[15px] font-semibold text-brand-navy">Billing & Usage Analytics</h1>
        <p className="text-[12px] text-text-secondary">
          Cloud spend across LLM, voice, messaging and infrastructure — with per-tenant unit economics.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-md border border-[var(--border-token)] bg-white p-0.5 text-[12px]">
          {(["production", "sandbox"] as Env[]).map((e) => (
            <button
              key={e}
              onClick={() => onEnv(e)}
              className={cn(
                "rounded px-3 py-1 font-medium capitalize transition-colors",
                env === e ? "bg-brand-primary text-white" : "text-text-secondary hover:text-brand-primary-dark",
              )}
            >
              {e === "production" ? "Prod" : "Sandbox"}
            </button>
          ))}
        </div>
        <Select value={period} onValueChange={(v) => onPeriod(v as Period)}>
          <SelectTrigger className="h-9 w-[140px] text-[12px]"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="mtd">Month to date</SelectItem>
            <SelectItem value="7d">Last 7 days</SelectItem>
            <SelectItem value="30d">Last 30 days</SelectItem>
            <SelectItem value="quarter">Last quarter</SelectItem>
          </SelectContent>
        </Select>
        <Select value={tenantId} onValueChange={onTenant}>
          <SelectTrigger className="h-9 w-[200px] text-[12px]"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All tenants</SelectItem>
            {TENANTS.map((t) => (
              <SelectItem key={t.id} value={t.id}>{t.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          variant="outline"
          size="sm"
          onClick={() => toast.success("CSV export queued", { description: "You'll be notified when the file is ready." })}
        >
          <Download className="mr-1.5 h-3.5 w-3.5" /> Export CSV
        </Button>
        <Button
          size="sm"
          onClick={() => toast.success("PDF summary generated", { description: "Invoice-style summary sent to finance-ops@." })}
        >
          <FileText className="mr-1.5 h-3.5 w-3.5" /> Export PDF
        </Button>
      </div>
    </div>
  );
}
