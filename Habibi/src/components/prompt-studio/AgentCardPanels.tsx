import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { Lozenge } from "@/components/ui/lozenge";
import { Button } from "@/components/ui/button";
import { useFlowTools } from "@/api/flow";
import {
  useAgentGraph,
  useAgentStudioSkills,
  useCompileCard,
  useCompilePreview,
  useEvalReports,
  useCritiqueReport,
  useEvalSuites,
  useRunEvalSuite,
  type CompileReport,
  type EvalReport,
} from "@/api/agent-studio";
import { useConnectors } from "@/api/integrations";
// The card shape is the backend's, not this file's. The local copy here
// covered 7 of the schema's 14 members and every caller reached it through
// `as never`, so nothing checked the other 7 or the spelling of these.
import {
  isAuthoredCard,
  REQUIRED_POLICY_KEYS,
  type AgentCard,
  type EvalRequire,
  type PolicyKey,
} from "@/api/agent-card";
import { EvalCockpit } from "@/components/sandbox/EvalCockpit";
import { CritiquesPanel } from "./CritiquesPanel";
import { LoadingState } from "@/components/ui/loading-state";
import { cn } from "@/lib/utils";
import { QueryState } from "@/components/ui/query-state";
import type { LozengeTone } from "@/components/ui/lozenge";

/**
 * An eval report's status, coloured for what it means.
 *
 * `status === "pass" ? success : danger` painted every other value red, and the
 * scheduler emits `skipped` for a suite it had no reason to run. This tab's own
 * copy says "Skipped is honest", two panels above a lozenge that was calling it
 * a failure. Anything outside the known vocabulary stays neutral rather than
 * being assigned a verdict nobody computed.
 */
function reportTone(status: string): LozengeTone {
  if (status === "pass") return "success";
  if (status === "fail" || status === "error") return "danger";
  if (status === "skipped") return "neutral";
  if (status === "warn" || status === "partial") return "warning";
  return "neutral";
}

const POLICY_ENGINES = [
  { key: "reco", label: "Recommend next offer", tool: "recommend_next_offer" },
  { key: "treatment", label: "Treatment", tool: "recommend_treatment" },
  { key: "authority", label: "Authority", tool: "evaluate_authority" },
  { key: "live_qa", label: "Live QA", tool: "evaluate_live_qa" },
  { key: "routing", label: "Routing", tool: null },
  { key: "dnd", label: "DND / calling hours", tool: null },
] as const;

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
  card: AgentCard;
  onChange?: (next: AgentCard) => void;
}) {
  const toolsQuery = useFlowTools();
  const include = card.tools?.include ?? [];
  const includeSet = new Set(include);
  const locked = new Set(card.tools?.locked ?? []);
  const rows = toolsQuery.data ?? [];
  const editable = Boolean(onChange) && isAuthoredCard(card);

  // Ask the compiler rather than guessing. This used to count
  // union(include, locked) against max_voice_tools, which is not what G6 does:
  // skill-gated tools are not offered while idle, and load_skill/run_skill_script
  // ride along free. A freshly cloned card read "21 / 12 — over the cap, G6
  // blocks publish" in red while compiling green at "idle 12 tools (cap 12)".
  const preview = useCompilePreview(botId, { agentCard: card }, isAuthoredCard(card));
  const g6 = preview.data?.gates.find((g) => g.gate === "G6");
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
          <span className="font-mono">{new Set([...include, ...locked]).size}</span> on the card
          <span className="ml-075 text-text-subtlest">(skill-gated ones load on demand)</span>
        </div>
        {!isAuthoredCard(card) ? null : preview.isError ? (
          <Lozenge tone="neutral">compiler unreachable</Lozenge>
        ) : g6 ? (
          <Lozenge
            tone={g6.status === "fail" ? "danger" : g6.status === "warn" ? "warning" : "success"}
          >
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
                    <div className="font-mono text-body-tiny">{t.key}</div>
                    <div className="text-text-subtle">{t.description}</div>
                  </td>
                  <td className="px-150 py-100">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={!editable || isLocked}
                      title={
                        isLocked ? "Locked by policy — the author cannot unbind it" : undefined
                      }
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

export function PolicyTab({ card }: { card: AgentCard }) {
  const bindings = card.policy_bindings ?? {};
  return (
    <div className="space-y-150">
      <p className="text-body-small text-text-subtle">
        These engines decide. The mouth cannot unbind them. Reco / treatment / authority / live QA /
        DND stay code with a log. This card cannot disable DND.
      </p>
      <ul className="divide-y divide-border rounded-medium border border-border">
        {POLICY_ENGINES.map((engine) => (
          <li key={engine.key} className="flex items-center justify-between px-150 py-100">
            <div>
              <div className="text-body font-medium">{engine.label}</div>
              {engine.tool ? (
                <div className="font-mono text-body-tiny text-text-subtle">{engine.tool}</div>
              ) : null}
            </div>
            {/* Green meant nothing here. The tone was hardcoded `success` and
                the label fell back to the literal "required" whenever the key
                was ABSENT — so a card missing a binding rendered exactly like a
                card that has one, in the reassuring colour, while G3 fails a
                card for that precise omission ("engines cannot be unbound").
                The one screen that shows policy bindings was incapable of
                showing a policy binding problem. */}
            {bindings[engine.key] === "required" ? (
              <Lozenge tone="success">required</Lozenge>
            ) : bindings[engine.key] ? (
              <Lozenge tone="danger" title="G3 accepts only 'required'.">
                {bindings[engine.key]}
              </Lozenge>
            ) : (
              <Lozenge tone="danger" title="G3 fails a card that does not bind every engine.">
                not bound — G3 blocks publish
              </Lozenge>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * What a card may demand before it ships. Mirrors `schema.py::EvalRequire`.
 *
 * The first three predate outbound. `twin` replays a real call against the
 * candidate; `outbound` is separate because an outbound bug fails differently —
 * an inbound one annoys the caller who rang us, an outbound one has already
 * rung ten thousand phones by the time anyone notices.
 */
const EVAL_REQUIRE: Array<{ key: EvalRequire; label: string; hint: string }> = [
  { key: "regression", label: "Regression", hint: "the behaviours that already worked" },
  { key: "redteam", label: "Red team", hint: "adversarial callers and prompt injection" },
  { key: "capability", label: "Capability", hint: "the things this card claims it can do" },
  { key: "twin", label: "Twin", hint: "replays of real calls against the candidate" },
  { key: "outbound", label: "Outbound", hint: "gated by G-OB9, on the same terms as G7/G8" },
];

export function EvalsTab({
  botId,
  card,
  onChange,
}: {
  botId: string;
  card: AgentCard;
  onChange?: (next: AgentCard) => void;
}) {
  const suitesQuery = useEvalSuites();
  // Scoped to this card. The tab used to accept botId and drop it, so a card
  // with no runs of its own showed another card's green badge.
  const reportsQuery = useEvalReports(undefined, botId);
  // Same botId the reports are filtered by, or the run vanishes from the tab
  // that started it.
  const run = useRunEvalSuite(botId);
  const editable = Boolean(onChange) && isAuthoredCard(card);
  // What the card actually requires, and nothing else.
  //
  // This used to fall back to `["regression","redteam"]`, rendered identically
  // to a stored value and with the same checkboxes ticked — so a card whose
  // `eval.require` was never set displayed two requirements it does not have,
  // and the tab's own "Nothing is required…" warning could never fire on the
  // card it was written for. The absence is the thing worth showing.
  const required: EvalRequire[] = card.eval?.require ?? [];
  const requirementsUnset = card.eval?.require === undefined;
  /**
   * Reports the scheduler filed against no card at all.
   *
   * A suite is not owned by one card — nine cards in this tenant name
   * `eval-regression-collections` — so `run_named_suite` files scheduled runs
   * with `bot_id = NULL` rather than guessing an owner, and that is the correct
   * thing for it to do. What was wrong is reading NULL here as "never run on
   * this card": insurance-v1's lapse suites pass nightly and this tab said
   * "never run on insurance-v1" the entire time, because the scoped query
   * cannot see a row with no scope.
   *
   * They are shown, and shown as what they are — tenant-wide — rather than
   * being folded in as if the card had run them itself.
   */
  const tenantReportsQuery = useEvalReports();
  const latestByKind = new Map<string, EvalReport>();
  for (const r of reportsQuery.data ?? []) {
    const kind = r.kind ?? "unknown";
    if (!latestByKind.has(kind)) latestByKind.set(kind, r);
  }
  const tenantWideByKind = new Map<string, EvalReport>();
  for (const r of tenantReportsQuery.data ?? []) {
    if (r.botId) continue;
    const kind = r.kind ?? "unknown";
    if (!latestByKind.has(kind) && !tenantWideByKind.has(kind)) tenantWideByKind.set(kind, r);
  }
  return (
    <div className="space-y-150">
      <p className="text-body-small text-text-subtle">
        Code graders hit CRM-shaped fixtures. When the eval/red-team flags are on, a failed suite
        blocks publish. Skipped is honest — not a fake green badge.
      </p>
      {/* Both of these were displayed read-only with no control anywhere, so a
          card's eval requirements — the thing that decides whether a failing
          suite blocks its publish — could only be changed by editing JSON in
          the database. */}
      <div className="space-y-100 rounded-medium border border-border p-150">
        <div className="text-body-small font-semibold">What this card requires before it ships</div>
        {!editable && onChange ? <NotAuthoredNotice what="the eval requirements" /> : null}
        <div className="grid gap-075 sm:grid-cols-2 lg:grid-cols-3">
          {EVAL_REQUIRE.map((r) => (
            <label key={r.key} className="flex items-start gap-075 text-body-small">
              <input
                type="checkbox"
                className="mt-050"
                disabled={!editable}
                checked={required.includes(r.key)}
                onChange={() => {
                  if (!onChange) return;
                  onChange({
                    ...card,
                    eval: {
                      ...(card.eval ?? {}),
                      require: required.includes(r.key)
                        ? required.filter((k) => k !== r.key)
                        : [...required, r.key],
                    },
                  });
                }}
              />
              <span>
                {r.label}
                <span className="block text-body-tiny text-text-subtlest">{r.hint}</span>
              </span>
            </label>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-100">
          <label className="text-body-small" htmlFor="eval-suite">
            Pinned suite
          </label>
          <select
            id="eval-suite"
            className="h-200 rounded-small border border-border bg-surface px-100 text-body-small"
            disabled={!editable}
            value={card.eval?.suite_id ?? ""}
            onChange={(e) => {
              if (!onChange) return;
              onChange({
                ...card,
                eval: { ...(card.eval ?? {}), suite_id: e.target.value || null },
              });
            }}
          >
            <option value="">— latest report of each required kind —</option>
            {(suitesQuery.data ?? []).map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.kind})
              </option>
            ))}
          </select>
          {card.eval?.suite_id &&
          !(suitesQuery.data ?? []).some((s) => s.id === card.eval?.suite_id) ? (
            <Lozenge tone="warning">{card.eval.suite_id} is not a suite that exists</Lozenge>
          ) : null}
        </div>
        {required.length === 0 ? (
          <p className="text-body-small text-text-warning-bolder">
            {requirementsUnset
              ? "This card sets no eval requirements, so no suite result can block a publish of it. Tick the kinds that must pass."
              : "Nothing is required, so no suite result can block a publish of this card."}
          </p>
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
                  <span className="text-body-tiny text-text-subtle">
                    {latest.summary?.total != null
                      ? `${(latest.summary.total ?? 0) - (latest.summary.failed ?? 0)}/${latest.summary.total}`
                      : ""}
                  </span>
                  <Lozenge tone={reportTone(latest.status)}>{latest.status}</Lozenge>
                </span>
              ) : tenantWideByKind.get(kind) ? (
                <span className="flex items-center gap-100">
                  <span className="text-body-tiny text-text-subtle">tenant-wide</span>
                  <Lozenge
                    tone={reportTone(tenantWideByKind.get(kind)!.status)}
                    title="A scheduled run filed against no particular card. It exercised this suite, but it is not a result for this card specifically."
                  >
                    {tenantWideByKind.get(kind)!.status}
                  </Lozenge>
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
              <div className="text-body-tiny text-text-subtle">
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
      <EvalReportsList botId={botId} reportsQuery={reportsQuery} />
      <CritiquesPanel />
      <EvalCockpit />
    </div>
  );
}

/**
 * The individual eval reports for this card, each with a Critique action.
 *
 * The reports were already fetched here to compute the latest-per-kind summary
 * and then thrown away, so a failed run could be seen as a red badge but never
 * opened. POST /eval/reports/{id}/critique reads that report's FAILED trials,
 * so critiquing a passing report is a no-op — the button says so rather than
 * returning an empty list and looking broken.
 */
function EvalReportsList({
  botId,
  reportsQuery,
}: {
  botId: string;
  reportsQuery: ReturnType<typeof useEvalReports>;
}) {
  const critique = useCritiqueReport();
  const [critiqued, setCritiqued] = useState<Record<string, string>>({});

  if (reportsQuery.isPending) return <LoadingState label="Loading eval reports" />;
  if (reportsQuery.isError) {
    return (
      <div className="rounded-medium border border-border px-150 py-100 text-body-small text-text-danger">
        Could not load eval reports for {botId} — this card&apos;s run history cannot be shown.
      </div>
    );
  }
  const reports = reportsQuery.data ?? [];
  if (reports.length === 0) {
    return (
      <div className="rounded-medium border border-dashed border-border bg-surface-sunken/40 px-200 py-150 text-center text-body-small">
        <div className="font-medium text-text">No eval reports for this card</div>
        <p className="mt-050 text-text-subtle">Run a suite above to produce one.</p>
      </div>
    );
  }

  const run = (reportId: string) => {
    critique.mutate(reportId, {
      onSuccess: (rows) => {
        const n = Array.isArray(rows) ? rows.length : 0;
        setCritiqued((prev) => ({
          ...prev,
          [reportId]: n === 0 ? "No failed trial the judge has a line for" : `${n} suggested`,
        }));
        if (n === 0) toast.message("Nothing to critique in that report");
        else toast.success(`${n} critique${n === 1 ? "" : "s"} drafted`);
      },
      onError: (e) => {
        const msg = e instanceof Error ? e.message : "Critique failed";
        // A missing table is a provisioning state, not a failure of this run.
        const missing = msg.includes("skill_critiques_missing");
        setCritiqued((prev) => ({
          ...prev,
          [reportId]: missing ? "Critique storage not provisioned" : "Failed",
        }));
        toast.error(missing ? "Critique storage is not provisioned" : msg);
      },
    });
  };

  return (
    <div className="overflow-hidden rounded-medium border border-border bg-surface">
      <div className="border-b border-border px-150 py-100 text-body-small font-semibold">
        Eval reports for this card
      </div>
      <table className="w-full text-body-small">
        <thead>
          <tr className="border-b border-border text-text-subtlest">
            <th className="px-150 py-100 text-left font-semibold">Suite</th>
            <th className="px-150 py-100 text-left font-semibold">Kind</th>
            <th className="px-150 py-100 text-right font-semibold">Passed</th>
            <th className="px-150 py-100 text-left font-semibold">Status</th>
            <th className="px-150 py-100 text-right font-semibold">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {reports.map((r) => {
            const total = r.summary?.total ?? 0;
            const failed = r.summary?.failed ?? 0;
            return (
              <tr key={r.id}>
                <td className="px-150 py-100">
                  <div className="text-text">{r.suiteName ?? r.suiteId}</div>
                  <div className="font-mono text-body-tiny text-text-subtlest">{r.id}</div>
                </td>
                <td className="px-150 py-100 font-mono text-text-subtle">{r.kind ?? "—"}</td>
                <td className="px-150 py-100 text-right font-mono tabular-nums text-text-subtle">
                  {total ? `${total - failed}/${total}` : "—"}
                </td>
                <td className="px-150 py-100">
                  <Lozenge tone={reportTone(r.status)}>{r.status}</Lozenge>
                </td>
                <td className="px-150 py-100 text-right">
                  <div className="flex items-center justify-end gap-075">
                    {critiqued[r.id] && (
                      <span className="text-body-tiny text-text-subtlest">{critiqued[r.id]}</span>
                    )}
                    <Button
                      type="button"
                      variant="outline"
                      disabled={critique.isPending}
                      onClick={() => run(r.id)}
                      title="Read this report's failed trials and propose a SKILL.md line. Writes nothing."
                    >
                      {critique.isPending ? "Critiquing…" : "Critique"}
                    </Button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

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
                            tone={ROUTE_TONE[n.reachability] ?? "neutral"}
                            title={ROUTE_HELP[n.reachability] ?? n.reachability}
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

/** Same vocabulary the fleet index uses, so one word does not mean two things. */
const ROUTE_TONE: Record<string, "success" | "information" | "warning" | "neutral"> = {
  entry: "success",
  handoff: "information",
  direct: "information",
  unreachable: "warning",
  archived: "neutral",
};

const ROUTE_HELP: Record<string, string> = {
  entry: "Takes inbound traffic directly.",
  handoff: "Reached mid-conversation from a live card's allowlist.",
  direct: "Has its own live deployment, but nothing hands off to it.",
  unreachable: "No deployment of its own and no inbound handoff — routes nothing today.",
  archived: "Retired. Takes no traffic.",
};

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

export function ConnectorsTab({
  card,
  onChange,
}: {
  card: AgentCard;
  onChange?: (next: AgentCard) => void;
}) {
  const connectorsQuery = useConnectors();
  const bound = new Set(
    (card.connectors ?? []).map((c) => c.connector_id).filter(Boolean) as string[],
  );
  const approved = (connectorsQuery.data ?? []).filter((c) => c.status === "approved");
  const prefixes = (card.connectors ?? []).flatMap((c) => c.allow_prefixes ?? []);
  const editable = Boolean(onChange) && isAuthoredCard(card);
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
        Bind <span className="font-semibold">approved</span> connectors only. Compiler G10 checks
        HTTPS, data-class, and health. <span className="font-mono">ext.*</span> tools stay off the
        idle mouth so G6 does not count them against the 12-tool SLO.
      </p>
      {!editable && onChange ? <NotAuthoredNotice what="connector bindings" /> : null}
      {prefixes.length > 0 ? (
        <div className="rounded-medium border border-border-warning bg-background-warning-subtler px-150 py-100 text-body-small text-text-warning-bolder">
          Bound prefixes: {prefixes.join(", ")}. Activated connector tools still count toward the
          voice cap.
        </div>
      ) : null}
      <QueryState
        query={connectorsQuery}
        label="connectors"
        empty={
          approved.length === 0 ? (
            // Naming the screen without offering it left the tab a dead end: the
            // only way forward was to know where Integrations lives and go there
            // by hand. Same Link treatment the Guardrails tab gives the
            // Redaction Hub.
            //
            // Reachable ONLY on a successful, empty response now. It used to be
            // the fallback for a failed one too, so an unreachable API produced
            // a confident instruction to go and approve connectors that were
            // already approved.
            <div className="space-y-100 rounded-medium border border-border p-150 text-body-small text-text-subtle">
              <p>
                No approved connectors. A connector has to be registered and approved before a card
                can bind it — G10 rejects a binding to anything else.
              </p>
              <Link
                to="/integrations"
                className="inline-flex items-center gap-050 text-text-brand hover:underline"
              >
                Approve connectors on Integrations <ExternalLink className="h-3 w-3" />
              </Link>
            </div>
          ) : null
        }
      >
        <ul className="divide-y divide-border rounded-medium border border-border">
          {approved.map((conn) => {
            const on = bound.has(conn.id) || bound.has(conn.slug);
            return (
              <li key={conn.id} className="flex items-start justify-between gap-150 px-150 py-100">
                <div>
                  <div className="font-medium">{conn.displayName}</div>
                  <div className="font-mono text-body-tiny text-text-subtle">
                    {conn.slug} · {(conn.allowPrefixes ?? []).join(" ")}
                  </div>
                  <div className="mt-050 text-body-tiny text-text-subtle">
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
      </QueryState>
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
              g.status === "pass"
                ? "success"
                : g.status === "fail"
                  ? "danger"
                  : g.status === "warn"
                    ? "warning"
                    : "neutral"
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
