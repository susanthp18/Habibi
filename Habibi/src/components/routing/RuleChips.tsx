import { ACTION_LABEL, FIELDS, type Condition, type Rule } from "@/data/routing-seed";
import { cn } from "@/lib/utils";

function condChip(c: Condition, matched?: boolean) {
  const f = FIELDS.find(f => f.key === c.field);
  return (
    <span
      key={c.id}
      className={cn(
        "inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] bg-surface-sunken px-2 py-0.5 font-mono text-[11px] text-text-primary",
        matched === true && "border-emerald-300 bg-emerald-50 text-emerald-800",
        matched === false && "border-red-200 bg-red-50 text-red-700",
      )}
    >
      <span className="font-semibold text-brand-primary-dark">{f?.label ?? c.field}</span>
      <span className="text-text-muted">{c.op}</span>
      <span>{String(c.value)}</span>
    </span>
  );
}

export function RuleChips({ rule }: { rule: Rule }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
      <span className="rounded bg-brand-tint px-1.5 py-0.5 font-semibold uppercase tracking-wider text-brand-primary-dark">IF</span>
      {rule.when.map((node, idx) => (
        <span key={node.id} className="flex flex-wrap items-center gap-1.5">
          {idx > 0 && <span className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">AND</span>}
          {"or" in node ? (
            <span className="flex flex-wrap items-center gap-1.5 rounded-md border border-dashed border-[var(--border-token)] px-1.5 py-0.5">
              {node.or.map((c, i) => (
                <span key={c.id} className="flex items-center gap-1.5">
                  {i > 0 && <span className="text-[10px] font-semibold uppercase tracking-wider text-amber-600">OR</span>}
                  {condChip(c)}
                </span>
              ))}
            </span>
          ) : (
            condChip(node)
          )}
        </span>
      ))}
      <span className="ml-1 rounded bg-brand-primary px-1.5 py-0.5 font-semibold uppercase tracking-wider text-white">THEN</span>
      <span className="rounded-md border border-[var(--border-token)] bg-white px-2 py-0.5 font-medium text-brand-navy">
        {ACTION_LABEL[rule.then.key]}
        {rule.then.params && Object.entries(rule.then.params).map(([k, v]) => (
          <span key={k} className="ml-1 text-text-muted">· {k}={v}</span>
        ))}
      </span>
    </div>
  );
}
