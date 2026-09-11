import { useState } from "react";
import { Lozenge } from "@/components/ui/lozenge";
import { Button } from "@/components/ui/button";
import { useAgentGraph } from "@/api/agent-studio";
import { isAuthoredCard, type AgentCard } from "@/api/agent-card";
import { cn } from "@/lib/utils";
import { ROUTING } from "@/lib/agent-roster";

export function AgentGraphTab({
  botId,
  card,
  onChange,
}: {
  botId: string;
  card?: AgentCard;
  onChange?: (next: AgentCard) => void;
}) {
  const graphQuery = useAgentGraph(botId);
  const [selected, setSelected] = useState<string | null>(null);
  const [whenDraft, setWhenDraft] = useState<Record<string, string>>({});
  const graph = graphQuery.data;
  const nodes = graph?.nodes ?? [];
  const label = (id: string) => nodes.find((n) => n.id === id)?.label ?? id;
  const editable = Boolean(onChange) && Boolean(card && isAuthoredCard(card));

  // The allowlist is the card's own handoffs, not a hardcoded intent table.
  // Reading it from the card (rather than only the server graph) means an
  // unsaved handoff edit is reflected before publish, same as every other tab.
  const handoffs = (card?.handoffs ?? []).filter((h) => h.to_bot_id);

  // Handoffs decide reachability: a card nothing hands off to takes no traffic
  // unless it is the inbound entry point. This was the one card field with no
  // editor anywhere, so a cloned card could never be made reachable from the UI.
  const setHandoff = (toBotId: string, when: string | null) => {
    if (!onChange || !card) return;
    const existing = (card.handoffs ?? []).find((h) => h.to_bot_id === toBotId);
    const rest = (card.handoffs ?? []).filter((h) => h.to_bot_id !== toBotId);
    onChange({
      ...card,
      // Spread the existing row so editing `when` does not drop a payload_schema
      // the card was authored with.
      handoffs: when === null ? rest : [...rest, { ...(existing ?? {}), to_bot_id: toBotId, when }],
    });
  };
  const edges = handoffs.length
    ? handoffs.map((h) => ({ from: botId, to: String(h.to_bot_id), when: h.when ?? "" }))
    : (graph?.edges ?? []).filter((e) => e.to).map((e) => ({ from: e.from, to: e.to, when: "" }));
  const legalTargets = new Set(edges.map((e) => e.to));
  const selfNode = nodes.find((n) => n.id === botId);
  const target = selected;
  const legal = target === null || target === botId || legalTargets.has(target);

  return (
    <div className="space-y-150">
      <p className="text-body-small text-text-subtle">
        Edges are this card&apos;s handoff allowlist. Pick a card to test the walk — an illegal
        target is red, and the model cannot prose its way onto it.
      </p>
      {edges.length === 0 ? (
        <div className="rounded-medium border border-dashed border-border p-150 text-body-small text-text-subtle">
          No handoffs on this card. Every conversation stays on{" "}
          <span className="font-mono">{botId}</span> or escalates to a human.
        </div>
      ) : null}
      <div className="flex flex-wrap gap-100">
        {nodes.map((n) => {
          const isSelf = n.id === botId;
          const highlighted = n.id === target;
          const reachable = isSelf || legalTargets.has(n.id);
          return (
            <button
              key={n.id}
              type="button"
              onClick={() => setSelected(target === n.id ? null : n.id)}
              className={cn(
                "rounded-medium border px-150 py-100 text-left text-body-small",
                !highlighted && reachable && "border-border-brand",
                !highlighted && !reachable && "border-border text-text-subtle",
                highlighted && reachable && "border-border-brand bg-background-brand-subtlest",
                highlighted &&
                  !reachable &&
                  "border-border-danger bg-background-danger-subtler text-text-danger-bolder",
              )}
            >
              <div className="font-semibold">{n.label}</div>
              <div className="font-mono text-body-tiny text-text-subtle">{n.id}</div>
              {isSelf ? <div className="text-body-tiny text-text-subtle">this card</div> : null}
            </button>
          );
        })}
      </div>
      <div className="text-body-small text-text-subtle">
        {target === null
          ? "Select a card above to check whether this card may hand off to it."
          : legal
            ? `Legal walk: ${botId} → ${target === botId ? "stays here" : label(target)}.`
            : `Illegal walk: ${label(target)} is not on this card's allowlist.`}
      </div>
      {editable ? (
        <div className="space-y-100 rounded-medium border border-border p-150">
          <div className="text-body-small font-semibold">Handoff allowlist</div>
          <p className="text-body-tiny text-text-subtle">
            Nothing routes to a card that is not the inbound entry point and not on some card&apos;s
            allowlist. The condition is guidance for the model, not a rule the runtime enforces —
            the allowlist itself is the rule. G5 rejects an unknown target or a self-handoff.
          </p>
          {selfNode?.reachability === "unreachable" ? (
            // The warning that is actually load-bearing here. Adding a handoff
            // TO an unreachable card is what makes it reachable, so warning on
            // the targets would be backwards; what routes nothing is an
            // allowlist on a card nothing can reach in the first place.
            <div className="rounded-medium border border-border-warning bg-background-warning-subtler px-150 py-100 text-body-tiny text-text-warning-bolder">
              This card is unreachable — it has no deployment of its own and nothing hands off to
              it. Until that changes, every handoff below routes nothing.
            </div>
          ) : null}
          {graphQuery.isError ? (
            // Without this the list is simply empty, which on a panel headed
            // "Handoff allowlist" reads as "this card may hand off to nobody" —
            // a statement about the fleet, produced by a failed fetch.
            <p className="text-body-small text-text-danger">
              The fleet could not be read, so the targets below are missing. The card&apos;s own
              allowlist is unchanged.
            </p>
          ) : null}
          <ul className="divide-y divide-border">
            {nodes
              .filter((n) => n.id !== botId)
              .map((n) => {
                const on = (card?.handoffs ?? []).find((h) => h.to_bot_id === n.id);
                return (
                  <li key={n.id} className="flex items-center gap-100 py-100">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-100">
                        <span className="text-body-small font-medium">{n.label}</span>
                        {n.reachability ? (
                          <Lozenge
                            tone={ROUTING[n.reachability]?.tone ?? "neutral"}
                            title={ROUTING[n.reachability]?.help("the entry card") ?? n.reachability}
                          >
                            {n.reachability}
                          </Lozenge>
                        ) : null}
                      </div>
                      <div className="font-mono text-body-tiny text-text-subtle">{n.id}</div>
                    </div>
                    {on ? (
                      <input
                        className="w-64 rounded-medium border border-border bg-surface px-100 py-050 text-body-small"
                        placeholder="when — e.g. caller asks about a policy"
                        value={whenDraft[n.id] ?? on.when ?? ""}
                        onChange={(e) => setWhenDraft((d) => ({ ...d, [n.id]: e.target.value }))}
                        onBlur={(e) => setHandoff(n.id, e.target.value)}
                      />
                    ) : null}
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => setHandoff(n.id, on ? null : (whenDraft[n.id] ?? ""))}
                    >
                      {on ? "Remove" : "Allow"}
                    </Button>
                  </li>
                );
              })}
          </ul>
        </div>
      ) : (
        <ul className="space-y-050 text-body-tiny text-text-subtle">
          {edges.map((e) => (
            <li key={`${e.from}->${e.to}`}>
              <span className="font-mono">
                {e.from} → {e.to}
              </span>
              {e.when ? <span className="ml-100">when {e.when}</span> : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
