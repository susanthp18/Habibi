import { Lozenge } from "@/components/ui/lozenge";
import { gateTone } from "@/lib/gate-status";
import { Button } from "@/components/ui/button";
import { useFlowTools } from "@/api/flow";
import { catalogToolsForCard, controlKindLabel } from "@/lib/studio-contract";
import { useAgentStudioSkills, useCompilePreview } from "@/api/agent-studio";
import { isAuthoredCard, type AgentCard } from "@/api/agent-card";
import { LoadingState } from "@/components/ui/loading-state";
import { NotAuthoredNotice } from "./NotAuthoredNotice";

export function ToolsTab({
  botId,
  card,
  onChange,
}: {
  botId: string;
  card: AgentCard;
  onChange?: (next: AgentCard) => void;
}) {
  const toolsQuery = useFlowTools();
  const include = card.tools?.include ?? [];
  const includeSet = new Set(include);
  const locked = new Set(card.tools?.locked ?? []);
  // The catalog now serves every channel, so the tab shows what this card's own
  // channels can render. A voice+whatsapp card sees `identify_customer`; a
  // voice-only card never did and still does not.
  const rows = catalogToolsForCard(toolsQuery.data ?? [], card.identity?.channels);
  const editable = Boolean(onChange) && isAuthoredCard(card);

  // Ask the compiler rather than guessing. This used to count
  // union(include, locked) against max_voice_tools, which is not what G6 does:
  // skill-gated tools are not offered while idle, and load_skill/run_skill_script
  // ride along free. A freshly cloned card read "21 / 12 — over the cap, G6
  // blocks publish" in red while compiling green at "idle 12 tools (cap 12)".
  const preview = useCompilePreview(botId, { agentCard: card }, isAuthoredCard(card));
  const g6 = preview.data?.gates.find((g) => g.gate === "G6");
  // G4 as well as G6. The tab read one gate out of a report that carries
  // sixteen, so a card whose include list names something the catalog does not
  // have showed nothing but a green G6 until Publish refused it.
  const g4 = preview.data?.gates.find((g) => g.gate === "G4");
  // G9 too: a skill whose allowed tools are not on the card fails publish, and
  // this is the tab where the author would put them on it.
  const g9 = preview.data?.gates.find((g) => g.gate === "G9");
  // Which skill wants each tool, so the row can say why a tool matters here.
  const skills = useAgentStudioSkills();
  const requiredBy = new Map<string, string[]>();
  for (const ref of card.skills ?? []) {
    const skill = skills.data?.find((s) => s.slug === ref.skill_id || s.id === ref.skill_id);
    for (const tool of skill?.allowedTools ?? []) {
      requiredBy.set(tool, [...(requiredBy.get(tool) ?? []), skill?.slug ?? ref.skill_id ?? "?"]);
    }
  }
  const idle = preview.data?.idle_voice_tools;
  // `??`, not `||`. A compiler that reports a voice-tool cap of 0 — a card
  // configured to offer no idle tools at all — is making a statement, and `||`
  // discarded it in favour of the card's own number or a hardcoded 12, so the
  // panel would show "3 / 12, fine" for a card the compiler will fail.
  const cap = preview.data?.voice_tool_cap ?? card.tools?.max_voice_tools ?? 12;

  const toggle = (key: string) => {
    if (!onChange) return;
    onChange({
      ...card,
      tools: {
        ...(card.tools ?? {}),
        include: includeSet.has(key) ? include.filter((k) => k !== key) : [...include, key],
      },
    });
  };

  return (
    <div className="space-y-150">
      <p className="text-body-small text-text-subtle">
        Mouth tools are a subset of the catalog. Locked engines stay on even if the author omits
        them. Idle voice tool count over the cap, or skill descriptions over ~800 tokens, blocks
        publish (G6).
      </p>
      <div className="flex flex-wrap items-center gap-150">
        <div className="rounded-medium border border-border px-150 py-100 text-body-small">
          <span className="font-mono">{idle ?? "—"}</span> / {cap} idle voice tools
        </div>
        <div className="rounded-medium border border-border px-150 py-100 text-body-small text-text-subtle">
          {/* The compiler's grant, not a client union of include and locked: the
              union counts tools the catalog dropped and misses the floor. */}
          <span className="font-mono">
            {preview.data?.effective_tools.length ?? new Set([...include, ...locked]).size}
          </span>{" "}
          {preview.data ? "granted by the compiler" : "on the card"}
          <span className="ml-075 text-text-subtlest">(skill-gated ones load on demand)</span>
        </div>
        {!isAuthoredCard(card) ? null : preview.isError ? (
          <Lozenge
            tone="warning"
            title={
              preview.error instanceof Error ? preview.error.message : "The compile did not answer."
            }
          >
            compile failed — {preview.error instanceof Error ? preview.error.message : "no answer"}
          </Lozenge>
        ) : g6 || g4 || g9 ? (
          <>
            {[g4, g6, g9].map((g) =>
              g ? (
                <Lozenge key={g.gate} tone={gateTone(g.status)}>
                  {g.gate} {g.status}
                  {g.detail ? ` — ${g.detail}` : ""}
                </Lozenge>
              ) : null,
            )}
          </>
        ) : (
          <Lozenge tone="neutral">checking…</Lozenge>
        )}
      </div>
      {!editable && onChange ? <NotAuthoredNotice what="the tool list" /> : null}
      {toolsQuery.isPending ? <LoadingState label="Loading the tool catalog" /> : null}
      <div className="overflow-hidden rounded-medium border border-border">
        <table className="w-full text-body-small">
          <thead className="bg-surface-sunken text-text-subtle">
            <tr>
              <th className="px-150 py-100 text-left font-medium">Tool</th>
              <th className="px-150 py-100 text-left font-medium">On this card</th>
              <th className="px-150 py-100 text-left font-medium">Effective</th>
              <th className="px-150 py-100 text-left font-medium">Policy</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => {
              const isLocked = Boolean(t.locked) || locked.has(t.key);
              // On whatever the card granted. Toggling it writes a line into
              // `tools.include` that changes nothing, and the row used to read
              // "unsupported" for a tool the runtime keeps on every call.
              const isFloor = Boolean(t.alwaysOn);
              const on = includeSet.has(t.key) || isLocked || isFloor;
              const frozen = isLocked || isFloor;
              return (
                <tr key={t.key} className="border-t border-border">
                  <td className="px-150 py-100">
                    <div className="font-mono text-body-tiny">{t.key}</div>
                    <div className="text-text-subtle">{t.description}</div>
                  </td>
                  <td className="px-150 py-100">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={!editable || frozen}
                      title={
                        isLocked
                          ? "Locked by policy — the author cannot unbind it"
                          : isFloor
                            ? "On the runtime floor — granted on every call whatever the card says"
                            : undefined
                      }
                      onClick={() => toggle(t.key)}
                    >
                      {on ? "Remove" : "Add"}
                    </Button>
                  </td>
                  <td className="px-150 py-100">
                    <Lozenge tone="neutral">
                      {controlKindLabel(
                        isFloor || preview.data?.effective_tools?.includes(t.key)
                          ? "runtime"
                          : "unsupported",
                      )}
                    </Lozenge>
                  </td>
                  <td className="px-150 py-100">
                    {isLocked ? (
                      <Lozenge tone="warning">required by policy</Lozenge>
                    ) : isFloor ? (
                      <Lozenge tone="neutral">always on (runtime floor)</Lozenge>
                    ) : requiredBy.has(t.key) ? (
                      <Lozenge tone={on ? "information" : "danger"}>
                        required by skill {requiredBy.get(t.key)?.join(", ")}
                      </Lozenge>
                    ) : (
                      <span className="text-text-subtle">optional</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {toolsQuery.isError ? (
        <p className="text-body-small text-text-danger-bolder">
          Could not load the tool catalog —{" "}
          {toolsQuery.error instanceof Error ? toolsQuery.error.message : "the API did not answer"}.
          The rows above are whatever was cached, not the catalog.
        </p>
      ) : !toolsQuery.isPending && rows.length === 0 ? (
        <p className="text-body-small text-text-subtle">The tool catalog is empty.</p>
      ) : null}
    </div>
  );
}
