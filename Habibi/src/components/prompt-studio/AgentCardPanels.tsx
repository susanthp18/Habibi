import { useState } from "react";
import { Lozenge } from "@/components/ui/lozenge";
import { Button } from "@/components/ui/button";
import { useFlowTools } from "@/api/flow";
import {
  useAgentGraph,
  useAgentStudioSkills,
  useCompileCard,
  useCompilePreview,
  useEvalReports,
  useEvalSuites,
  useRunEvalSuite,
  type CompileReport,
  type EvalReport,
} from "@/api/agent-studio";
import { useConnectors } from "@/api/integrations";
import { EvalCockpit } from "@/components/sandbox/EvalCockpit";
import { cn } from "@/lib/utils";

const POLICY_ENGINES = [
  { key: "reco", label: "Recommend next offer", tool: "recommend_next_offer" },
  { key: "treatment", label: "Treatment", tool: "recommend_treatment" },
  { key: "authority", label: "Authority", tool: "evaluate_authority" },
  { key: "live_qa", label: "Live QA", tool: "evaluate_live_qa" },
  { key: "routing", label: "Routing", tool: null },
  { key: "dnd", label: "DND / calling hours", tool: null },
] as const;

type CardShape = {
  identity?: { bot_id?: string; display_name?: string };
  tools?: { include?: string[]; locked?: string[]; max_voice_tools?: number };
  handoffs?: { to_bot_id?: string; when?: string }[];
  policy_bindings?: Record<string, string>;
  eval?: { suite_id?: string | null; require?: string[] };
  skills?: { skill_id?: string; version?: string }[];
  connectors?: { connector_id?: string; allow_prefixes?: string[] }[];
};

/** A card that has never been authored has no `identity`, so it cannot be saved. */
function isAuthored(card: CardShape): boolean {
  return Boolean(card.identity?.bot_id);
}

function NotAuthoredNotice({ what }: { what: string }) {
  return (
    <div className="rounded-medium border border-dashed border-border p-200 text-body-small text-text-subtle">
      This version has no Agent Card, so {what} cannot be edited here. Clone a card from the fleet
      index, or publish once to stamp the first-party defaults onto this bot.
    </div>
  );
}

export function ToolsTab({
  botId,
  card,
  onChange,
}: {
  botId: string;
  card: CardShape;
  onChange?: (next: CardShape) => void;
}) {
  const toolsQuery = useFlowTools();
  const include = card.tools?.include ?? [];
  const includeSet = new Set(include);
  const locked = new Set(card.tools?.locked ?? []);
  const rows = toolsQuery.data ?? [];
  const editable = Boolean(onChange) && isAuthored(card);

  // Ask the compiler rather than guessing. This used to count
  // union(include, locked) against max_voice_tools, which is not what G6 does:
  // skill-gated tools are not offered while idle, and load_skill/run_skill_script
  // ride along free. A freshly cloned card read "21 / 12 — over the cap, G6
  // blocks publish" in red while compiling green at "idle 12 tools (cap 12)".
  const preview = useCompilePreview(botId, { agentCard: card }, isAuthored(card));
  const g6 = preview.data?.gates.find((g) => g.gate === "G6");
  const idle = preview.data?.idle_voice_tools;
  const cap = preview.data?.voice_tool_cap || (card.tools?.max_voice_tools ?? 12);

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
        Mouth tools are a subset of the catalog. Locked engines stay on even if the author omits them.
        Idle voice tool count over the cap, or skill descriptions over ~800 tokens, blocks publish (G6).
      </p>
      <div className="flex flex-wrap items-center gap-150">
        <div className="rounded-medium border border-border px-150 py-100 text-body-small">
          <span className="font-mono">{idle ?? "—"}</span> / {cap} idle voice tools
        </div>
        <div className="rounded-medium border border-border px-150 py-100 text-body-small text-text-subtle">
          <span className="font-mono">{new Set([...include, ...locked]).size}</span> on the card
          <span className="ml-075 text-text-subtlest">(skill-gated ones load on demand)</span>
        </div>
        {!isAuthored(card) ? null : preview.isError ? (
          <Lozenge tone="neutral">compiler unreachable</Lozenge>
        ) : g6 ? (
          <Lozenge tone={g6.status === "fail" ? "danger" : g6.status === "warn" ? "warning" : "success"}>
            G6 {g6.status}
            {g6.detail ? ` — ${g6.detail}` : ""}
          </Lozenge>
        ) : (
          <Lozenge tone="neutral">checking…</Lozenge>
        )}
      </div>
      {!editable && onChange ? <NotAuthoredNotice what="the tool list" /> : null}
      <div className="overflow-hidden rounded-medium border border-border">
        <table className="w-full text-body-small">
          <thead className="bg-surface-sunken text-text-subtle">
            <tr>
              <th className="px-150 py-100 text-left font-medium">Tool</th>
              <th className="px-150 py-100 text-left font-medium">On this card</th>
              <th className="px-150 py-100 text-left font-medium">Policy</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => {
              const isLocked = Boolean(t.locked) || locked.has(t.key);
              const on = includeSet.has(t.key) || isLocked;
              return (
                <tr key={t.key} className="border-t border-border">
                  <td className="px-150 py-100">
                    <div className="font-mono text-caption">{t.key}</div>
                    <div className="text-text-subtle">{t.description}</div>
                  </td>
                  <td className="px-150 py-100">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={!editable || isLocked}
                      title={isLocked ? "Locked by policy — the author cannot unbind it" : undefined}
                      onClick={() => toggle(t.key)}
                    >
                      {on ? "Remove" : "Add"}
                    </Button>
                  </td>
                  <td className="px-150 py-100">
                    {isLocked ? (
                      <Lozenge tone="warning">required by policy</Lozenge>
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
      {rows.length === 0 ? (
        <p className="text-body-small text-text-subtle">Tool catalog unavailable — check the API.</p>
      ) : null}
    </div>
  );
}

export function PolicyTab({ card }: { card: CardShape }) {
  const bindings = card.policy_bindings ?? {};
  return (
    <div className="space-y-150">
      <p className="text-body-small text-text-subtle">
        These engines decide. The mouth cannot unbind them. Reco / treatment / authority / live QA / DND stay
        code with a log. This card cannot disable DND.
      </p>
      <ul className="divide-y divide-border rounded-medium border border-border">
        {POLICY_ENGINES.map((engine) => (
          <li key={engine.key} className="flex items-center justify-between px-150 py-100">
            <div>
              <div className="text-body font-medium">{engine.label}</div>
              {engine.tool ? <div className="font-mono text-caption text-text-subtle">{engine.tool}</div> : null}
            </div>
            <Lozenge tone="success">{bindings[engine.key] || "required"}</Lozenge>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function EvalsTab({ botId, card }: { botId: string; card: CardShape }) {
  const suitesQuery = useEvalSuites();
  // Scoped to this card. The tab used to accept botId and drop it, so a card
  // with no runs of its own showed another card's green badge.
  const reportsQuery = useEvalReports(undefined, botId);
  // Same botId the reports are filtered by, or the run vanishes from the tab
  // that started it.
  const run = useRunEvalSuite(botId);
  const required = card.eval?.require ?? ["regression", "redteam"];
  const latestByKind = new Map<string, EvalReport>();
  for (const r of reportsQuery.data ?? []) {
    const kind = r.kind ?? "unknown";
    if (!latestByKind.has(kind)) latestByKind.set(kind, r);
  }
  return (
    <div className="space-y-150">
      <p className="text-body-small text-text-subtle">
        Code graders hit CRM-shaped fixtures. When the eval/red-team flags are on, a failed suite blocks
        publish. Skipped is honest — not a fake green badge.
      </p>
      <div className="text-body-small">
        This card requires: {required.join(", ")}
        {card.eval?.suite_id ? (
          <span className="ml-100 font-mono text-caption text-text-subtle">({card.eval.suite_id})</span>
        ) : null}
      </div>
      <ul className="space-y-050 rounded-medium border border-border p-150">
        {required.map((kind) => {
          const latest = latestByKind.get(kind);
          return (
            <li key={kind} className="flex items-center justify-between gap-100 text-body-small">
              <span className="font-mono">{kind}</span>
              {latest ? (
                <span className="flex items-center gap-100">
                  <span className="text-caption text-text-subtle">
                    {latest.summary?.total != null
                      ? `${(latest.summary.total ?? 0) - (latest.summary.failed ?? 0)}/${latest.summary.total}`
                      : ""}
                  </span>
                  <Lozenge tone={latest.status === "pass" ? "success" : "danger"}>{latest.status}</Lozenge>
                </span>
              ) : (
                <Lozenge tone="neutral">never run on {botId}</Lozenge>
              )}
            </li>
          );
        })}
      </ul>
      <ul className="space-y-100">
        {(suitesQuery.data ?? []).map((suite) => (
          <li
            key={suite.id}
            className="flex items-center justify-between rounded-medium border border-border px-150 py-100"
          >
            <div>
              <div className="text-body font-medium">{suite.name}</div>
              <div className="text-caption text-text-subtle">
                {suite.kind} · {suite.id}
              </div>
            </div>
            <Button
              type="button"
              variant="outline"
              disabled={run.isPending}
              onClick={() => void run.mutateAsync(suite.id)}
            >
              {run.isPending ? "Running…" : "Run"}
            </Button>
          </li>
        ))}
      </ul>
      {run.data ? (
        <div className="rounded-medium border border-border bg-surface-sunken px-150 py-100 text-body-small">
          Last run: {run.data.status} · {run.data.total - run.data.failed}/{run.data.total} passed
          {run.data.reportId ? <span className="ml-100 font-mono">{run.data.reportId}</span> : null}
        </div>
      ) : null}
      <EvalCockpit />
    </div>
  );
}

export function AgentGraphTab({
  botId,
  card,
  onChange,
}: {
  botId: string;
  card?: CardShape;
  onChange?: (next: CardShape) => void;
}) {
  const graphQuery = useAgentGraph(botId);
  const [selected, setSelected] = useState<string | null>(null);
  const [whenDraft, setWhenDraft] = useState<Record<string, string>>({});
  const graph = graphQuery.data;
  const nodes = graph?.nodes ?? [];
  const label = (id: string) => nodes.find((n) => n.id === id)?.label ?? id;
  const editable = Boolean(onChange) && Boolean(card && isAuthored(card));

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
    : (graph?.edges ?? [])
        .filter((e) => e.to)
        .map((e) => ({ from: e.from, to: e.to, when: "" }));
  const legalTargets = new Set(edges.map((e) => e.to));
  const target = selected;
  const legal = target === null || target === botId || legalTargets.has(target);

  return (
    <div className="space-y-150">
      <p className="text-body-small text-text-subtle">
        Edges are this card&apos;s handoff allowlist. Pick a card to test the walk — an illegal target is
        red, and the model cannot prose its way onto it.
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
              <div className="font-mono text-caption text-text-subtle">{n.id}</div>
              {isSelf ? <div className="text-caption text-text-subtle">this card</div> : null}
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
          <p className="text-caption text-text-subtle">
            Nothing routes to a card that is not the inbound entry point and not on some card&apos;s
            allowlist. The condition is guidance for the model, not a rule the runtime enforces —
            the allowlist itself is the rule. G5 rejects an unknown target or a self-handoff.
          </p>
          <ul className="divide-y divide-border">
            {nodes
              .filter((n) => n.id !== botId)
              .map((n) => {
                const on = (card?.handoffs ?? []).find((h) => h.to_bot_id === n.id);
                return (
                  <li key={n.id} className="flex items-center gap-100 py-100">
                    <div className="min-w-0 flex-1">
                      <div className="text-body-small font-medium">{n.label}</div>
                      <div className="font-mono text-caption text-text-subtle">{n.id}</div>
                    </div>
                    {on ? (
                      <input
                        className="w-64 rounded-medium border border-border bg-surface px-100 py-050 text-body-small"
                        placeholder="when — e.g. caller asks about a policy"
                        value={whenDraft[n.id] ?? on.when ?? ""}
                        onChange={(e) =>
                          setWhenDraft((d) => ({ ...d, [n.id]: e.target.value }))
                        }
                        onBlur={(e) => setHandoff(n.id, e.target.value)}
                      />
                    ) : null}
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        setHandoff(n.id, on ? null : (whenDraft[n.id] ?? ""))
                      }
                    >
                      {on ? "Remove" : "Allow"}
                    </Button>
                  </li>
                );
              })}
          </ul>
        </div>
      ) : (
        <ul className="space-y-050 text-caption text-text-subtle">
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

export function SkillsTab({
  card,
  onChange,
}: {
  card: CardShape;
  onChange?: (next: CardShape) => void;
}) {
  const skillsQuery = useAgentStudioSkills();
  const attached = new Set((card.skills ?? []).map((s) => s.skill_id).filter(Boolean) as string[]);
  const prefixChars = (skillsQuery.data ?? [])
    .filter((s) => attached.has(s.slug) || attached.has(s.id))
    .reduce((n, s) => n + Math.ceil((s.description?.length ?? 0) / 4), 0);
  const editable = Boolean(onChange) && isAuthored(card);

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
      : [...(card.skills ?? []), { skill_id: slug, version: "1" }];
    onChange({ ...card, skills: next });
  };

  return (
    <div className="space-y-150">
      <p className="text-body-small text-text-subtle">
        Descriptions always ride the system prefix (~{prefixChars} tokens). The body loads on{" "}
        <span className="font-mono">load_skill</span> or intent. Detaching PTP removes{" "}
        <span className="font-mono">create_promise_to_pay</span> even if it stays on the card include list.
        Unsigned skills cannot attach to production (G9).
      </p>
      {!editable && onChange ? <NotAuthoredNotice what="skill attachments" /> : null}
      <div className="grid gap-100 sm:grid-cols-3">
        <div className="rounded-medium border border-border p-100">
          <div className="text-caption font-medium">Idle prefix</div>
          <div className="font-mono text-body">{prefixChars} tok</div>
          <div className="text-caption text-text-subtle">Names + descriptions only</div>
        </div>
        <div className="rounded-medium border border-border p-100">
          <div className="text-caption font-medium">Activated body</div>
          <div className="font-mono text-body">
            {(skillsQuery.data ?? [])
              .filter((s) => attached.has(s.slug) || attached.has(s.id))
              .reduce((n, s) => n + (s.bodyTokens ?? 0), 0)}{" "}
            tok
          </div>
          <div className="text-caption text-text-subtle">One body at a time; previous drops</div>
        </div>
        <div className="rounded-medium border border-border p-100">
          <div className="text-caption font-medium">References</div>
          <div className="font-mono text-body">
            {(skillsQuery.data ?? [])
              .filter((s) => attached.has(s.slug) || attached.has(s.id))
              .reduce((n, s) => n + (s.referenceFiles?.length ?? 0), 0)}{" "}
            files
          </div>
          <div className="text-caption text-text-subtle">Lazy text. Zero extra tools.</div>
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
                  <Lozenge tone={skill.signed ? "success" : "warning"}>{skill.signatureStatus}</Lozenge>
                </div>
                <div className="mt-050 text-body-small text-text-subtle">{skill.description}</div>
                <div className="mt-050 flex flex-wrap gap-050">
                  {skill.allowedTools.map((t) => (
                    <span key={t} className="font-mono text-caption text-text-subtle">
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
      {(skillsQuery.data ?? []).length === 0 ? (
        <p className="text-body-small text-text-subtle">
          Skill catalog is empty. First-party packs sync when the API boots — they are not disabled.
        </p>
      ) : null}
    </div>
  );
}

export function ConnectorsTab({
  card,
  onChange,
}: {
  card: CardShape;
  onChange?: (next: CardShape) => void;
}) {
  const connectorsQuery = useConnectors();
  const bound = new Set((card.connectors ?? []).map((c) => c.connector_id).filter(Boolean) as string[]);
  const approved = (connectorsQuery.data ?? []).filter((c) => c.status === "approved");
  const prefixes = (card.connectors ?? []).flatMap((c) => c.allow_prefixes ?? []);
  const editable = Boolean(onChange) && isAuthored(card);
  // Same alias trap as skills: the POST /connectors endpoint stamps the row id
  // while this tab wrote the slug, so Unbind matched nothing on any card bound
  // through the API. get_connector resolves either, so binding by slug is fine
  // — only the removal had to widen.
  const toggle = (aliases: string[], prefixesFor: string[]) => {
    if (!onChange) return;
    const on = aliases.some((a) => bound.has(a));
    const next = on
      ? (card.connectors ?? []).filter((c) => !aliases.includes(String(c.connector_id)))
      : [...(card.connectors ?? []), { connector_id: aliases[0], allow_prefixes: prefixesFor }];
    onChange({ ...card, connectors: next });
  };

  return (
    <div className="space-y-150">
      <p className="text-body-small text-text-subtle">
        Bind <span className="font-semibold">approved</span> connectors only. Compiler G10 checks HTTPS, data-class,
        and health. <span className="font-mono">ext.*</span> tools stay off the idle mouth so G6 does not count them
        against the 12-tool SLO.
      </p>
      {!editable && onChange ? <NotAuthoredNotice what="connector bindings" /> : null}
      {prefixes.length > 0 ? (
        <div className="rounded-medium border border-border-warning bg-background-warning-subtler px-150 py-100 text-body-small text-text-warning-bolder">
          Bound prefixes: {prefixes.join(", ")}. Activated connector tools still count toward the voice cap.
        </div>
      ) : null}
      <ul className="divide-y divide-border rounded-medium border border-border">
        {approved.map((conn) => {
          const on = bound.has(conn.id) || bound.has(conn.slug);
          return (
            <li key={conn.id} className="flex items-start justify-between gap-150 px-150 py-100">
              <div>
                <div className="font-medium">{conn.displayName}</div>
                <div className="font-mono text-caption text-text-subtle">
                  {conn.slug} · {(conn.allowPrefixes ?? []).join(" ")}
                </div>
                <div className="mt-050 text-caption text-text-subtle">
                  {(conn.dataClass ?? []).join(", ")} · {conn.health}
                </div>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={!editable}
                onClick={() => toggle([conn.slug, conn.id], conn.allowPrefixes ?? [])}
              >
                {on ? "Unbind" : "Bind"}
              </Button>
            </li>
          );
        })}
      </ul>
      {approved.length === 0 ? (
        <p className="text-body-small text-text-subtle">No approved connectors. Approve them on Integrations.</p>
      ) : null}
    </div>
  );
}

export function CompileReportList({ report }: { report: CompileReport | null }) {
  if (!report) return null;
  return (
    <ul className="space-y-050 text-body-small">
      {report.gates.map((g) => (
        <li key={g.gate} className="flex items-start justify-between gap-100">
          <span>
            <span className="font-mono">{g.gate}</span> {g.name}
            {g.detail ? <span className="ml-075 text-text-subtle">{g.detail}</span> : null}
          </span>
          <Lozenge
            tone={
              g.status === "pass" ? "success" : g.status === "fail" ? "danger" : g.status === "warn" ? "warning" : "neutral"
            }
          >
            {g.status}
          </Lozenge>
        </li>
      ))}
    </ul>
  );
}

export function useStudioCompile(botId: string) {
  return useCompileCard(botId);
}
