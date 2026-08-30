import { CircleSlash, HelpCircle, ShieldAlert, ShieldCheck } from "lucide-react";
import { ChartCard } from "@/components/charts";
import { Lozenge, type LozengeTone } from "@/components/ui/lozenge";
import { useRuleCoverage, type RuleState } from "@/api/compliance";
import { cn } from "@/lib/utils";

/**
 * Which rules are actually being checked.
 *
 * "Top rule hits" can only list rules that have already produced a violation,
 * so a rule nobody is checking looked identical to a rule with a spotless
 * record: absent from the list. That is the reading a compliance officer most
 * needs to be able to make, and it was the one the page could not support.
 *
 * The distinction that matters is `clean` vs `unverified`, and they are styled
 * to be told apart at a glance rather than read.
 */

const STATE: Record<RuleState, { tone: LozengeTone; label: string; Icon: typeof ShieldCheck }> = {
  breached: { tone: "danger", label: "breached", Icon: ShieldAlert },
  clean: { tone: "success", label: "clean", Icon: ShieldCheck },
  unverified: { tone: "warning", label: "no detector", Icon: HelpCircle },
  disabled: { tone: "neutral", label: "disabled", Icon: CircleSlash },
};

const ORDER: RuleState[] = ["unverified", "breached", "clean", "disabled"];

export function RuleCoverageCard({
  selectedRuleId,
  onSelect,
}: {
  selectedRuleId: "all" | string;
  onSelect: (id: "all" | string) => void;
}) {
  const { data, isLoading } = useRuleCoverage();

  if (isLoading || !data || data.rules.length === 0) return null;

  const rows = [...data.rules].sort(
    (a, b) => ORDER.indexOf(a.state) - ORDER.indexOf(b.state) || a.code.localeCompare(b.code),
  );
  const unverified = rows.filter((r) => r.state === "unverified").length;

  return (
    <ChartCard
      title="Rule coverage"
      subtitle={`${data.rules.length} rules · ${data.interactionsEvaluated} interactions evaluated`}
      action={
        unverified > 0 ? (
          <Lozenge tone="warning">{unverified} unchecked</Lozenge>
        ) : (
          <Lozenge tone="success">all checked</Lozenge>
        )
      }
    >
      <ul className="space-y-050 overflow-y-auto">
        {rows.map((rule) => {
          const meta = STATE[rule.state];
          const active = selectedRuleId === rule.ruleId;
          // A rule with nothing to show cannot be filtered to anything useful.
          const filterable = rule.total > 0;
          const Icon = meta.Icon;
          return (
            <li key={rule.ruleId}>
              <button
                type="button"
                disabled={!filterable}
                onClick={() => onSelect(active ? "all" : rule.ruleId)}
                className={cn(
                  "flex w-full items-center gap-100 rounded-medium px-100 py-075 text-left transition-colors",
                  active
                    ? "bg-background-brand-subtlest"
                    : filterable
                      ? "hover:bg-surface-sunken"
                      : "",
                  !filterable && "cursor-default",
                )}
              >
                <Icon
                  className={cn(
                    "h-3.5 w-3.5 shrink-0",
                    rule.state === "breached" && "text-text-danger",
                    rule.state === "clean" && "text-text-success",
                    rule.state === "unverified" && "text-text-warning",
                    rule.state === "disabled" && "text-text-subtlest",
                  )}
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-body-small font-medium text-text">
                    {rule.label}
                  </span>
                  <span className="block font-mono text-body-small text-text-subtlest">
                    {rule.code}
                  </span>
                </span>
                {rule.total > 0 ? (
                  <span className="shrink-0 tabular-nums text-body-small text-text-subtle">
                    {rule.open}/{rule.total}
                  </span>
                ) : (
                  <Lozenge tone={meta.tone}>{meta.label}</Lozenge>
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </ChartCard>
  );
}
