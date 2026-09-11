import { Lozenge } from "@/components/ui/lozenge";
import { usePolicyEngines } from "@/api/agent-studio";
import { QueryState } from "@/components/ui/query-state";

export function PolicyTab() {
  // The engines' actual modes, read live. The card used to carry six
  // `Literal["required"]` fields that bound nothing; this tab rendered them
  // as six green lozenges that could not change.
  const engines = usePolicyEngines();
  return (
    <div className="space-y-150">
      <p className="text-body-small text-text-subtle">
        These engines decide. The mouth cannot unbind them — G3 fails a card that drops one from its
        locked tools. The mode each runs in is set on the stack, not on this card.
      </p>
      <QueryState query={engines} label="the policy engines">
        <ul className="divide-y divide-border rounded-medium border border-border">
          {(engines.data ?? []).map((engine) => (
            <li key={engine.key} className="flex items-center justify-between px-150 py-100">
              <div>
                <div className="text-body font-medium">{engine.label}</div>
                {engine.tool ? (
                  <div className="font-mono text-body-tiny text-text-subtle">{engine.tool}</div>
                ) : null}
              </div>
              <Lozenge
                tone={
                  engine.mode === "live" || engine.mode === "always"
                    ? "success"
                    : engine.mode === "shadow"
                      ? "warning"
                      : "danger"
                }
                title={engine.source ? `Set by ${engine.source}` : "No mode knob — always on"}
              >
                {engine.mode}
              </Lozenge>
            </li>
          ))}
        </ul>
      </QueryState>
    </div>
  );
}
