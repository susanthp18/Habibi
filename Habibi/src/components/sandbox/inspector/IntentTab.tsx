import { INTENT_LABEL, type SandboxTurn, type IntentKey } from "@/data/sandbox-seed";
import { cn } from "@/lib/utils";

export function IntentTab({ turns }: { turns: SandboxTurn[] }) {
  const lastCustomer = [...turns].reverse().find((t) => t.role === "customer" && t.intentScores);
  if (!lastCustomer?.intentScores) {
    return (
      <div className="rounded-md border border-dashed border-[var(--border-token)] p-6 text-center text-[12px] text-text-muted">
        Send a customer message to classify intent.
      </div>
    );
  }
  const entries = (Object.keys(lastCustomer.intentScores) as IntentKey[])
    .map((k) => ({ k, v: lastCustomer.intentScores![k] }))
    .sort((a, b) => b.v - a.v);
  const top = entries[0].k;
  return (
    <div className="space-y-2">
      <div className="text-[11px] text-text-muted">Classifier output for last customer turn</div>
      {entries.map((e) => (
        <div key={e.k}>
          <div className="mb-0.5 flex items-center justify-between text-[11.5px]">
            <span className={cn(e.k === top ? "font-semibold text-brand-primary-dark" : "text-text-secondary")}>
              {INTENT_LABEL[e.k]}
            </span>
            <span className="font-mono text-[10.5px] text-text-muted">{(e.v * 100).toFixed(0)}%</span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded bg-surface-sunken">
            <div className={cn("h-full", e.k === top ? "bg-brand-primary" : "bg-brand-primary/40")} style={{ width: `${e.v * 100}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}
