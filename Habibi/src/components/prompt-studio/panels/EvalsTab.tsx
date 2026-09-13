import { useState } from "react";
import { toast } from "sonner";
import { Lozenge } from "@/components/ui/lozenge";
import { gateTone } from "@/lib/gate-status";
import { Button } from "@/components/ui/button";
import {
  useEvalReports,
  useCritiqueReport,
  useEvalSuites,
  useRunEvalSuite,
  TENANT_WIDE_REPORTS,
  type EvalReport,
} from "@/api/agent-studio";
// The card shape is the backend's, not this file's. The local copy here
// covered 7 of the schema's 14 members and every caller reached it through
// `as never`, so nothing checked the other 7 or the spelling of these.
import { isAuthoredCard, type AgentCard, type EvalRequire } from "@/api/agent-card";
import { CritiquesPanel } from "../CritiquesPanel";
import { useEvalReportDetail } from "@/api/agent-studio";
import { LoadingState } from "@/components/ui/loading-state";
import { QueryErrorBanner, QueryState } from "@/components/ui/query-state";
import { NotAuthoredNotice } from "./NotAuthoredNotice";

/**
 * An eval report's status, coloured for what it means.
 *
 * `status === "pass" ? success : danger` painted every other value red, and the
 * scheduler emits `skipped` for a suite it had no reason to run. This tab's own
 * copy says "Skipped is honest", two panels above a lozenge that was calling it
 * a failure. Anything outside the known vocabulary stays neutral rather than
 * being assigned a verdict nobody computed.
 */

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
  {
    key: "twin",
    label: "Twin",
    // Where to run it, because it is not here. The Twin has its own runner in
    // the Sandbox inspector; the Evals tab's suites write `eval_reports` and
    // G11 reads `twin_runs`, so nothing on this screen can satisfy this box.
    hint: "replays of real calls — run it from the Sandbox inspector's Twin tab",
  },
  { key: "outbound", label: "Outbound", hint: "gated by G-OB9, on the same terms as G7/G8" },
];

export function EvalsTab({
  botId,
  card,
  onChange,
  promptVersionId,
}: {
  botId: string;
  card: AgentCard;
  onChange?: (next: AgentCard) => void;
  promptVersionId?: string;
}) {
  const suitesQuery = useEvalSuites();
  // Scoped to this card. The tab used to accept botId and drop it, so a card
  // with no runs of its own showed another card's green badge.
  const reportsQuery = useEvalReports(undefined, botId);
  // Same botId the reports are filtered by, or the run vanishes from the tab
  // that started it.
  const run = useRunEvalSuite(botId, promptVersionId);
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
  const tenantReportsQuery = useEvalReports(undefined, TENANT_WIDE_REPORTS);
  const [openReport, setOpenReport] = useState<string | null>(null);
  const latestByKind = new Map<string, EvalReport>();
  for (const r of reportsQuery.data ?? []) {
    const kind = r.kind ?? "unknown";
    if (!latestByKind.has(kind)) latestByKind.set(kind, r);
  }
  const tenantWideByKind = new Map<string, EvalReport>();
  for (const r of tenantReportsQuery.data ?? []) {
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
                  <Lozenge tone={gateTone(latest.status)}>{latest.status}</Lozenge>
                  <button
                    type="button"
                    className="text-body-tiny text-text-brand underline-offset-2 hover:underline"
                    aria-expanded={openReport === latest.id}
                    onClick={() => setOpenReport((cur) => (cur === latest.id ? null : latest.id))}
                  >
                    {openReport === latest.id ? "hide trials" : "trials"}
                  </button>
                </span>
              ) : tenantWideByKind.get(kind) ? (
                <span className="flex items-center gap-100">
                  <span className="text-body-tiny text-text-subtle">tenant-wide</span>
                  <Lozenge
                    tone={gateTone(tenantWideByKind.get(kind)!.status)}
                    title="A scheduled run filed against no particular card. It exercised this suite, but it is not a result for this card specifically."
                  >
                    {tenantWideByKind.get(kind)!.status}
                  </Lozenge>
                </span>
              ) : reportsQuery.isError || tenantReportsQuery.isError ? (
                <Lozenge
                  tone="warning"
                  title="The reports could not be loaded. This is a failed read, not a card with no runs."
                >
                  reports unavailable
                </Lozenge>
              ) : reportsQuery.isPending ? (
                <Lozenge tone="neutral">loading…</Lozenge>
              ) : (
                <Lozenge tone="neutral">never run on {botId}</Lozenge>
              )}
            </li>
          );
        })}
      </ul>
      {openReport ? <EvalTrials reportId={openReport} /> : null}
      <QueryState
        query={suitesQuery}
        label="the suite catalog"
        empty={
          suitesQuery.data?.length === 0 ? (
            <p className="text-body-small text-text-subtle">No eval suites are configured.</p>
          ) : null
        }
      >
        <ul className="space-y-100">
          {(suitesQuery.data ?? []).map((suite) => {
            // Pending per suite: one `isPending` disabled every Run button.
            const running = run.isPending && run.variables === suite.id;
            return (
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
                  onClick={() => run.mutate(suite.id)}
                >
                  {running ? "Running…" : "Run"}
                </Button>
              </li>
            );
          })}
        </ul>
      </QueryState>
      {run.isError ? (
        <QueryErrorBanner label={`the run of ${run.variables ?? "the suite"}`} error={run.error} />
      ) : run.data ? (
        <div className="rounded-medium border border-border bg-surface-sunken px-150 py-100 text-body-small">
          Last run: {run.data.status} · {run.data.total - run.data.failed}/{run.data.total} passed
          {run.data.reportId ? <span className="ml-100 font-mono">{run.data.reportId}</span> : null}
        </div>
      ) : null}
      <EvalReportsList botId={botId} reportsQuery={reportsQuery} />
      <CritiquesPanel />
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
                  <Lozenge tone={gateTone(r.status)}>{r.status}</Lozenge>
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

/**
 * The graded fixtures behind a verdict, failed first. The trials were written
 * on every run and read by nothing; a lozenge that says "fail" with no way to
 * see which fixture failed is a verdict the author cannot act on.
 */
function EvalTrials({ reportId }: { reportId: string }) {
  const query = useEvalReportDetail(reportId);
  return (
    <QueryState query={query} label="the report's trials">
      {query.data ? (
        query.data.trials.length === 0 ? (
          <p className="text-body-tiny text-text-subtle">
            This report recorded no trials — it predates per-fixture storage.
          </p>
        ) : (
          <ul className="max-h-[16rem] space-y-050 overflow-y-auto rounded-medium border border-border p-100">
            {query.data.trials.map((t, i) => (
              <li
                key={`${t.taskId ?? "trial"}-${i}`}
                className="flex items-start gap-100 text-body-tiny"
              >
                <Lozenge tone={t.passed ? "success" : "danger"}>
                  {t.passed ? "pass" : "fail"}
                </Lozenge>
                <span className="min-w-0 flex-1">
                  <span className="font-medium text-text">{t.name ?? t.taskId ?? "trial"}</span>
                  {(t.verdict.graders ?? [])
                    .filter((g) => g.passed === false && g.detail)
                    .map((g, j) => (
                      <span key={j} className="block text-text-subtle">
                        {g.grader}: {g.detail}
                      </span>
                    ))}
                </span>
              </li>
            ))}
          </ul>
        )
      ) : null}
    </QueryState>
  );
}
