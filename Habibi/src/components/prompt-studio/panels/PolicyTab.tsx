import { Link } from "@tanstack/react-router";
import { ExternalLink } from "lucide-react";
import { usePolicyEngines } from "@/api/agent-studio";
import { isAuthoredCard, type AgentCard } from "@/api/agent-card";
import { Button } from "@/components/ui/button";
import { Lozenge } from "@/components/ui/lozenge";
import { QueryState } from "@/components/ui/query-state";

/**
 * Where each engine's own screen is. The tab listed six engines and linked to
 * none of the places an operator would go to see what they decide; the mode
 * is env-driven, but the rules, holds and windows each engine reads are
 * authored on these screens.
 */
const ENGINE_SCREENS: Record<string, { to: string; label: string }> = {
  reco: { to: "/upsell", label: "Offer policy on Upsell & leads" },
  treatment: { to: "/treatment", label: "Decision intelligence" },
  authority: { to: "/customers", label: "Authority profile on a customer's 360" },
  live_qa: { to: "/qa", label: "QA scorecards" },
  routing: { to: "/routing", label: "Routing rules" },
  dnd: { to: "/consent", label: "Consent / DND and calling hours" },
};

export function PolicyTab({
  card,
  onChange,
}: {
  card: AgentCard;
  onChange?: (next: AgentCard) => void;
}) {
  // The engines' actual modes, read live. The card used to carry six
  // booleans that nothing read; the runtime consults the stack's flags.
  const engines = usePolicyEngines();
  const locked = new Set(card.tools?.locked ?? []);
  const editable = Boolean(onChange) && isAuthoredCard(card);
  // G3 fails a card whose locked list dropped an engine's tool, and this tab
  // used to show the engines without noticing. Restore puts the tool back.
  const restore = (tool: string) =>
    onChange?.({ ...card, tools: { ...(card.tools ?? {}), locked: [...locked, tool] } });
  return (
    <div className="space-y-150">
      <p className="text-body-small text-text-subtle">
        These engines decide. The mouth cannot unbind them — G3 fails a card that drops one from its
        locked tools. The mode each runs in is set on the stack, not on this card.
      </p>
      <QueryState query={engines} label="the policy engines">
        <ul className="divide-y divide-border rounded-medium border border-border">
          {(engines.data ?? []).map((engine) => {
            const missing = Boolean(engine.tool) && !locked.has(engine.tool as string);
            return (
              <li
                key={engine.key}
                className="flex items-center justify-between gap-100 px-150 py-100"
              >
                <div className="min-w-0">
                  <div className="text-body font-medium">{engine.label}</div>
                  {engine.tool ? (
                    <div className="font-mono text-body-tiny text-text-subtle">{engine.tool}</div>
                  ) : null}
                  {ENGINE_SCREENS[engine.key] ? (
                    <Link
                      to={ENGINE_SCREENS[engine.key]!.to}
                      className="inline-flex items-center gap-050 text-body-tiny text-text-brand hover:underline"
                    >
                      {ENGINE_SCREENS[engine.key]!.label} <ExternalLink className="h-3 w-3" />
                    </Link>
                  ) : null}
                </div>
                <div className="flex items-center gap-075">
                  {missing ? (
                    <>
                      <Lozenge
                        tone="danger"
                        title="G3 fails publish while this engine's tool is off the card's locked list"
                      >
                        not locked on this card
                      </Lozenge>
                      {editable ? (
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => restore(engine.tool as string)}
                        >
                          Restore
                        </Button>
                      ) : null}
                    </>
                  ) : null}
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
                </div>
              </li>
            );
          })}
        </ul>
      </QueryState>
    </div>
  );
}
