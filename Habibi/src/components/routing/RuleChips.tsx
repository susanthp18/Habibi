import { ACTION_LABEL, FIELDS, type Condition, type Rule } from "@/data/routing-seed";
import { cn } from "@/lib/utils";

function condChip(c: Condition, matched?: boolean) {
  const f = FIELDS.find((f) => f.key === c.field);
  return (
    <span
      key={c.id}
      className={cn(
        "inline-flex items-center gap-050 rounded-medium border border-border bg-surface-sunken px-100 py-025 font-mono text-body-small text-text",
        matched === true &&
          "border-border-success bg-background-success-subtler text-text-success-bolder",
        matched === false &&
          "border-border-danger-subtle bg-background-danger-subtler text-text-danger-bolder",
      )}
    >
      <span className="font-semibold text-text-brand">{f?.label ?? c.field}</span>
      <span className="text-text-subtlest">{c.op}</span>
      <span>{String(c.value)}</span>
    </span>
  );
}

export function RuleChips({ rule }: { rule: Rule }) {
  return (
    <div className="flex flex-wrap items-center gap-075 text-body-small">
      <span className="rounded bg-background-brand-subtlest px-075 py-025 font-semibold text-text-brand">
        IF
      </span>
      {rule.when.map((node, idx) => (
        <span key={node.id} className="flex flex-wrap items-center gap-075">
          {idx > 0 && <span className="text-body-small font-semibold text-text-subtlest">AND</span>}
          {"or" in node ? (
            <span className="flex flex-wrap items-center gap-075 rounded-medium border border-dashed border-border px-075 py-025">
              {node.or.map((c, i) => (
                <span key={c.id} className="flex items-center gap-075">
                  {i > 0 && (
                    <span className="text-body-small font-semibold text-text-warning">OR</span>
                  )}
                  {condChip(c)}
                </span>
              ))}
            </span>
          ) : (
            condChip(node)
          )}
        </span>
      ))}
      <span className="ml-050 rounded bg-background-brand-bold px-075 py-025 font-semibold text-white">
        THEN
      </span>
      <span className="rounded-medium border border-border bg-surface px-100 py-025 font-medium text-text">
        {ACTION_LABEL[rule.then.key]}
        {rule.then.params &&
          Object.entries(rule.then.params).map(([k, v]) => (
            <span key={k} className="ml-050 text-text-subtlest">
              · {k}={v}
            </span>
          ))}
      </span>
    </div>
  );
}
