import { Lozenge } from "@/components/ui/lozenge";
import { gateTone } from "@/lib/gate-status";
import { Button } from "@/components/ui/button";
import { controlKindLabel } from "@/lib/studio-contract";
import { useAgentStudioSkills, useCompilePreview } from "@/api/agent-studio";
import { isAuthoredCard, type AgentCard } from "@/api/agent-card";
import { QueryState } from "@/components/ui/query-state";
import { NotAuthoredNotice } from "./NotAuthoredNotice";

export function SkillsTab({
  botId,
  card,
  onChange,
}: {
  botId: string;
  card: AgentCard;
  onChange?: (next: AgentCard) => void;
}) {
  const skillsQuery = useAgentStudioSkills();
  const attached = new Set((card.skills ?? []).map((s) => s.skill_id).filter(Boolean) as string[]);
  const editable = Boolean(onChange) && isAuthoredCard(card);
  // Same compile preview the Tools tab runs, for the same reason: the compiler
  // is the only thing whose token count is the one the gates use.
  const preview = useCompilePreview(botId, { agentCard: card }, isAuthoredCard(card));
  // G9 is the gate this tab's choices are judged by, so it is shown here
  // rather than only in the publish dialog after the fact.
  const g9 = preview.data?.gates.find((g) => g.gate === "G9");
  const prefixFromCompiler = typeof preview.data?.skill_description_tokens === "number";
  const prefixTokens = prefixFromCompiler
    ? preview.data!.skill_description_tokens
    : (skillsQuery.data ?? [])
        .filter((s) => attached.has(s.slug) || attached.has(s.id))
        .reduce((n, s) => n + Math.ceil((s.description?.length ?? 0) / 4), 0);

  // Attach writes the slug, but older rows (and the connector endpoint's
  // sibling path) store the row id. Detaching by slug alone left those rows in
  // place: the button read "Detach", the filter matched nothing, and the skill
  // stayed attached. Match every alias on the way out.
  const toggle = (aliases: string[]) => {
    if (!onChange) return;
    const slug = aliases[0];
    const on = aliases.some((a) => attached.has(a));
    const next = on
      ? (card.skills ?? []).filter((s) => !aliases.includes(String(s.skill_id)))
      : [
          ...(card.skills ?? []),
          {
            skill_id: slug,
            // The version the catalog is actually serving, not a literal "1".
            // The schema defaults to `pin: "exact", version: "1"`, which is
            // identical to every row today and stops being identical the first
            // time any skill ships a v2 — at which point every card attached
            // through this button is pinned to a version that is no longer the
            // one anybody is editing, silently and retroactively.
            version:
              (skillsQuery.data ?? []).find((sk) => sk.slug === slug || sk.id === slug)?.version ??
              "1",
          },
        ];
    onChange({ ...card, skills: next });
  };

  return (
    <div className="space-y-150">
      <p className="text-body-small text-text-subtle">
        Descriptions always ride the system prefix (~{prefixTokens} tokens). The body loads on{" "}
        <span className="font-mono">load_skill</span> or intent. Detaching PTP removes{" "}
        <span className="font-mono">create_promise_to_pay</span> even if it stays on the card
        include list. Unsigned skills cannot attach to production (G9).
      </p>
      {isAuthoredCard(card) && g9 ? (
        <Lozenge tone={gateTone(g9.status)} title={g9.detail || undefined}>
          {g9.gate} {g9.status}
          {g9.detail ? ` — ${g9.detail}` : ""}
        </Lozenge>
      ) : null}
      {!editable && onChange ? <NotAuthoredNotice what="skill attachments" /> : null}
      <QueryState
        query={skillsQuery}
        label="the skill catalog"
        empty={
          (skillsQuery.data ?? []).length === 0 ? (
            <p className="text-body-small text-text-subtle">
              Skill catalog is empty. First-party packs sync when the API boots — they are not
              disabled.
            </p>
          ) : null
        }
      >
        <div className="grid gap-100 sm:grid-cols-3">
          <div className="rounded-medium border border-border p-100">
            <div className="text-body-tiny font-medium">Idle prefix</div>
            {/* The compiler's own figure when it has one. This tile used to be
              computed here as `description.length / 4` under a label promising
              "Names + descriptions only" — an approximation of a number the
              backend already reports exactly, sitting next to the ToolsTab that
              fetches it. Two answers to one question, and no way to tell which
              one the gate uses. */}
            <div className="font-mono text-body">{prefixTokens} tok</div>
            <div className="text-body-tiny text-text-subtle">
              {prefixFromCompiler
                ? "Names + descriptions, as the compiler counts them"
                : "Names + descriptions (estimated)"}
            </div>
          </div>
          <div className="rounded-medium border border-border p-100">
            <div className="text-body-tiny font-medium">Activated body</div>
            <div className="font-mono text-body">
              {(skillsQuery.data ?? [])
                .filter((s) => attached.has(s.slug) || attached.has(s.id))
                .reduce((n, s) => n + (s.bodyTokens ?? 0), 0)}{" "}
              tok
            </div>
            <div className="text-body-tiny text-text-subtle">
              One body at a time; previous drops
            </div>
          </div>
          <div className="rounded-medium border border-border p-100">
            <div className="text-body-tiny font-medium">References</div>
            <div className="font-mono text-body">
              {(skillsQuery.data ?? [])
                .filter((s) => attached.has(s.slug) || attached.has(s.id))
                .reduce((n, s) => n + (s.referenceFiles?.length ?? 0), 0)}{" "}
              files
            </div>
            <div className="text-body-tiny text-text-subtle">Lazy text. Zero extra tools.</div>
          </div>
        </div>
        <ul className="divide-y divide-border rounded-medium border border-border">
          {(skillsQuery.data ?? []).map((skill) => {
            const on = attached.has(skill.slug) || attached.has(skill.id);
            return (
              <li key={skill.id} className="flex items-start justify-between gap-150 px-150 py-100">
                <div>
                  <div className="flex items-center gap-100">
                    <span className="font-mono text-body-small">{skill.slug}</span>
                    <Lozenge tone={skill.signed ? "success" : "warning"}>
                      {skill.signatureStatus}
                    </Lozenge>
                    <Lozenge tone="neutral">
                      {controlKindLabel(
                        on && (skill.signed || skill.hasSignedVersion) ? "runtime" : "compile-only",
                      )}
                    </Lozenge>
                  </div>
                  <div className="mt-050 text-body-small text-text-subtle">{skill.description}</div>
                  <div className="mt-050 flex flex-wrap gap-050">
                    {skill.allowedTools.map((t) => (
                      <span key={t} className="font-mono text-body-tiny text-text-subtle">
                        {t}
                      </span>
                    ))}
                  </div>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => toggle([skill.slug, skill.id])}
                  disabled={!editable || (!(skill.signed || skill.hasSignedVersion) && !on)}
                  title={
                    !(skill.signed || skill.hasSignedVersion) && !on
                      ? "Unsigned skills cannot attach to production (G9)"
                      : undefined
                  }
                >
                  {on ? "Detach" : "Attach"}
                </Button>
              </li>
            );
          })}
        </ul>
      </QueryState>
    </div>
  );
}
