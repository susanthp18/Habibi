import { useMemo, useState, type ReactNode } from "react";
import { createLazyFileRoute } from "@tanstack/react-router";
import type { UseQueryResult } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  AlertTriangle,
  Ban,
  BrainCircuit,
  CircleSlash,
  Inbox,
  Plus,
  RefreshCw,
  ShieldOff,
  Sparkles,
} from "lucide-react";

import { AppShell } from "@/components/shell/AppShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LoadingState } from "@/components/ui/loading-state";
import { Lozenge, type LozengeTone } from "@/components/ui/lozenge";
import { SectionMessage } from "@/components/ui/section-message";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { USE_MOCK } from "@/api/config";
import {
  fmtInr,
  fmtNum,
  fmtRate,
  humanise,
  HOLD_KINDS,
  HOLD_SOURCES,
  useCreateTreatmentHold,
  useReleaseTreatmentHold,
  useTreatmentCases,
  useTreatmentHolds,
  useTreatmentInsights,
  useTreatmentMetrics,
  useTreatmentModelHealth,
  useTreatmentModels,
  useTreatmentNext,
  type HoldKind,
  type HoldSource,
  type TreatmentCase,
  type TreatmentHold,
} from "@/api/treatment";

export const Route = createLazyFileRoute("/treatment")({
  component: TreatmentPage,
});

// ---------------------------------------------------------------------------
// Shared state scaffolding
//
// Loading, empty and error are rendered by one component so no section can
// quietly skip one. The error branch renders INSTEAD of the data — a failed
// live call must never fall through to a half-populated table, because a
// plausible-looking number with no backend behind it is worse than a gap.
// ---------------------------------------------------------------------------

function ErrorPanel({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <div className="flex flex-col gap-150 py-200">
      <SectionMessage variant="error" icon={AlertTriangle} title="Couldn’t load this section">
        {error instanceof Error ? error.message : "The backend did not return a usable response."}
      </SectionMessage>
      <div>
        <Button size="sm" variant="outline" onClick={onRetry}>
          <RefreshCw className="mr-075 h-3.5 w-3.5" /> Try again
        </Button>
      </div>
    </div>
  );
}

function EmptyPanel({
  title,
  body,
  icon: Icon = Inbox,
}: {
  title: string;
  body: string;
  icon?: typeof Inbox;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-100 rounded-large border border-dashed border-border py-600 text-center">
      <Icon aria-hidden className="size-6 text-icon-subtlest" />
      <p className="heading-xsmall text-text">{title}</p>
      <p className="max-w-md text-body-small text-text-subtle">{body}</p>
    </div>
  );
}

function StateGate<T>({
  query,
  loadingLabel,
  isEmpty,
  emptyTitle = "Nothing here yet",
  emptyBody = "Once the engine logs against this window, it will show up here.",
  emptyIcon,
  children,
}: {
  query: UseQueryResult<T>;
  loadingLabel: string;
  isEmpty?: (data: T) => boolean;
  emptyTitle?: string;
  emptyBody?: string;
  emptyIcon?: typeof Inbox;
  children: (data: T) => ReactNode;
}) {
  if (query.isError) {
    return <ErrorPanel error={query.error} onRetry={() => void query.refetch()} />;
  }
  if (query.isPending || query.data === undefined) {
    return (
      <div className="grid place-items-center py-600">
        <LoadingState label={loadingLabel} />
      </div>
    );
  }
  if (isEmpty?.(query.data)) {
    return <EmptyPanel title={emptyTitle} body={emptyBody} icon={emptyIcon} />;
  }
  return <>{children(query.data)}</>;
}

// ---------------------------------------------------------------------------
// Small presentational pieces
// ---------------------------------------------------------------------------

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-025 rounded-large border border-border bg-surface p-150">
      <span className="text-body-small text-text-subtle">{label}</span>
      <span className="heading-small tabular-nums text-text">{value}</span>
      {hint ? <span className="text-body-tiny text-text-subtlest">{hint}</span> : null}
    </div>
  );
}

function Panel({
  title,
  description,
  children,
  actions,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <section className="flex min-w-0 flex-col gap-150 rounded-large border border-border bg-surface p-200">
      <div className="flex items-start justify-between gap-150">
        <div className="min-w-0">
          <h2 className="heading-xsmall text-text">{title}</h2>
          {description ? <p className="text-body-small text-text-subtle">{description}</p> : null}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

/** Share-of-total bar list. Widths are relative to the largest row, not to the
 *  sum, so a long tail stays readable instead of collapsing to slivers. */
function BarList({ rows }: { rows: Array<{ key: string; label: string; count: number }> }) {
  const max = Math.max(...rows.map((r) => r.count), 1);
  const total = rows.reduce((sum, r) => sum + r.count, 0);
  return (
    <ul className="flex flex-col gap-100">
      {rows.map((row) => (
        <li key={row.key} className="flex flex-col gap-025">
          <div className="flex items-baseline justify-between gap-100 text-body-small">
            <span className="min-w-0 truncate text-text">{row.label}</span>
            <span className="shrink-0 tabular-nums text-text-subtle">
              {fmtNum(row.count)} · {fmtRate(total ? row.count / total : null)}
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-small bg-background-neutral">
            <div
              className="h-full rounded-small bg-background-brand-bold"
              style={{ width: `${Math.max((row.count / max) * 100, 2)}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

const HOLD_TONE: Record<string, LozengeTone> = {
  hardship: "warning",
  dispute: "information",
  complaint: "warning",
  bereavement: "discovery",
  legal: "danger",
};

const SERVING_TONE: Record<string, LozengeTone> = {
  ok: "success",
  unregistered: "warning",
  stale: "warning",
  missing: "danger",
};

const MODEL_STATUS_TONE: Record<string, LozengeTone> = {
  champion: "success",
  challenger: "information",
  retired: "neutral",
};

const VERDICT_TONE: Record<string, LozengeTone> = {
  promoted: "success",
  rejected: "danger",
  skipped: "neutral",
};

function fmtWhen(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

const WINDOWS = [7, 14, 28, 90] as const;

function TreatmentPage() {
  const [days, setDays] = useState<number>(14);
  const [tab, setTab] = useState("insights");

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col">
        <div className="shrink-0 border-b border-border bg-background-brand-subtlest/40 px-300 py-075 text-body-small text-text-brand">
          {USE_MOCK
            ? "Mock data · no backend call is being made. Set VITE_USE_MOCK=false to read the live decision log."
            : "Live decision log · the engine logs every decision. Outside live mode it enacts nothing."}
        </div>

        <div className="flex shrink-0 items-center justify-between gap-200 border-b border-border bg-surface px-300 py-150">
          <div className="min-w-0">
            <h1 className="text-body font-semibold text-text">Decision intelligence</h1>
            <p className="text-body-small text-text-subtle">
              What the treatment engine decided, why it was suppressed, and whether the models
              behind it are still calibrated.
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-100">
            <Label htmlFor="treatment-window" className="text-body-small text-text-subtle">
              Window
            </Label>
            <Select value={String(days)} onValueChange={(v) => setDays(Number(v))}>
              <SelectTrigger id="treatment-window" className="w-36">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {WINDOWS.map((w) => (
                  <SelectItem key={w} value={String(w)}>
                    Last {w} days
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <Tabs
          value={tab}
          onValueChange={setTab}
          className="flex min-h-0 flex-1 flex-col overflow-hidden"
        >
          <TabsList className="h-10 w-full shrink-0 justify-start px-300">
            <TabsTrigger value="insights">Insights</TabsTrigger>
            <TabsTrigger value="models">Model health</TabsTrigger>
            <TabsTrigger value="cases">Cases</TabsTrigger>
            <TabsTrigger value="holds">Holds</TabsTrigger>
          </TabsList>

          <TabsContent
            value="insights"
            className="mt-0 min-h-0 flex-1 overflow-y-auto px-300 py-200"
          >
            <InsightsTab days={days} />
          </TabsContent>
          <TabsContent value="models" className="mt-0 min-h-0 flex-1 overflow-y-auto px-300 py-200">
            <ModelsTab days={days} />
          </TabsContent>
          <TabsContent value="cases" className="mt-0 min-h-0 flex-1 overflow-y-auto px-300 py-200">
            <CasesTab />
          </TabsContent>
          <TabsContent value="holds" className="mt-0 min-h-0 flex-1 overflow-y-auto px-300 py-200">
            <HoldsTab />
          </TabsContent>
        </Tabs>
      </div>
    </AppShell>
  );
}

// ---------------------------------------------------------------------------
// Insights — GET /treatment/insights + GET /treatment/metrics
// ---------------------------------------------------------------------------

function InsightsTab({ days }: { days: number }) {
  const insights = useTreatmentInsights(days);
  const metrics = useTreatmentMetrics(days);

  return (
    <div className="flex flex-col gap-200">
      <StateGate
        query={insights}
        loadingLabel="Loading shadow-mode report"
        isEmpty={(d) => d.decisions === 0}
        emptyTitle="No decisions in this window"
        emptyBody="The engine has not logged a decision over the selected window. Widen the window, or trigger one from a borrower’s record."
        emptyIcon={Sparkles}
      >
        {(data) => (
          <>
            <div className="grid grid-cols-2 gap-150 md:grid-cols-4 xl:grid-cols-7">
              <Stat label="Decisions" value={fmtNum(data.decisions)} />
              <Stat label="Actionable" value={fmtNum(data.actionable)} hint="survived the veto" />
              <Stat label="Coverage" value={fmtRate(data.coverage)} hint="actionable ÷ decisions" />
              <Stat label="Enacted" value={fmtNum(data.enacted)} hint="actually carried out" />
              <Stat label="Borrowers" value={fmtNum(data.customers)} />
              <Stat label="Expected value" value={fmtInr(data.expectedValueInr)} />
              <Stat label="Avg latency" value={`${fmtNum(data.avgLatencyMs)} ms`} />
            </div>

            <div className="grid gap-200 lg:grid-cols-2">
              <Panel
                title="Suppression mix"
                description="Why an actionable decision still did nothing. The exit criterion is written against this breakdown."
              >
                {data.suppression.length === 0 ? (
                  <EmptyPanel
                    title="Nothing was suppressed"
                    body="Every decision in this window was free to act."
                    icon={CircleSlash}
                  />
                ) : (
                  <BarList
                    rows={data.suppression.map((s) => ({
                      key: s.reason,
                      label: humanise(s.reason),
                      count: s.count,
                    }))}
                  />
                )}
              </Panel>

              <Panel
                title="Action mix"
                description="What the engine chose, and what it thought each choice was worth."
              >
                {data.byAction.length === 0 ? (
                  <EmptyPanel
                    title="No action was chosen"
                    body="Every decision in this window resolved to a hold."
                    icon={CircleSlash}
                  />
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Action</TableHead>
                        <TableHead className="text-right">Decisions</TableHead>
                        <TableHead className="text-right">Avg expected value</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.byAction.map((a) => (
                        <TableRow key={a.action}>
                          <TableCell>{humanise(a.action)}</TableCell>
                          <TableCell className="text-right tabular-nums">
                            {fmtNum(a.count)}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {fmtInr(a.avgExpectedValue)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </Panel>

              <Panel title="Mode split" description="Shadow decides and logs; live also acts.">
                {data.byMode.length === 0 ? (
                  <EmptyPanel title="No decisions" body="Nothing logged in this window." />
                ) : (
                  <BarList
                    rows={data.byMode.map((m) => ({
                      key: m.mode,
                      label: humanise(m.mode),
                      count: m.count,
                    }))}
                  />
                )}
              </Panel>

              <Panel
                title="Outcomes"
                description="Labelled results, once a case has moved. Empty is normal in shadow mode."
              >
                {data.outcomes.length === 0 ? (
                  <EmptyPanel
                    title="No labelled outcomes yet"
                    body="Nothing has been enacted, so no decision in this window has an outcome to attribute."
                    icon={CircleSlash}
                  />
                ) : (
                  <BarList
                    rows={data.outcomes.map((o) => ({
                      key: o.outcome,
                      label: humanise(o.outcome),
                      count: o.count,
                    }))}
                  />
                )}
              </Panel>
            </div>
          </>
        )}
      </StateGate>

      <StateGate query={metrics} loadingLabel="Loading scoreboard">
        {(m) => (
          <div className="flex flex-col gap-200">
            <Panel
              title="Causal read"
              description="Incremental recovery against the randomised control arm — never a collections rate."
            >
              {m.causal.available ? (
                <div className="grid grid-cols-2 gap-150 md:grid-cols-4">
                  <Stat label="Treatment effect" value={fmtRate(m.causal.ate ?? null)} />
                  <Stat label="Standard error" value={fmtRate(m.causal.stderr ?? null, 2)} />
                  <Stat label="Treated arm" value={fmtNum(m.causal.treatedN)} />
                  <Stat label="Control arm" value={fmtNum(m.causal.controlN)} />
                </div>
              ) : (
                <SectionMessage
                  variant="warning"
                  icon={Ban}
                  title="No causal number can be reported yet"
                >
                  {m.causal.reason ??
                    "The arms are too thin to support a causal estimate over this window."}
                </SectionMessage>
              )}
            </Panel>

            <div className="grid gap-200 lg:grid-cols-2">
              <Panel title="Efficiency" description="What the recovery cost to produce.">
                <div className="grid grid-cols-2 gap-150">
                  <Stat label="Resolutions" value={fmtNum(m.efficiency.resolutions)} />
                  <Stat label="Contacts" value={fmtNum(m.efficiency.contacts)} />
                  <Stat
                    label="Contacts per resolution"
                    value={fmtNum(m.efficiency.contactsPerResolution, 2)}
                  />
                  <Stat
                    label="Voice minutes"
                    value={fmtNum(m.efficiency.voiceMinutes, 1)}
                    hint={`${fmtNum(m.efficiency.voiceCalls)} calls`}
                  />
                  <Stat
                    label="Voice minutes per ₹1L"
                    value={fmtNum(m.efficiency.voiceMinutesPerLakhRecovered, 1)}
                  />
                  <Stat label="Recovered" value={fmtInr(m.efficiency.recoveredInr)} />
                </div>
              </Panel>

              <Panel
                title="Conduct"
                description="Contact attempts against the window and the daily cap."
              >
                <div className="grid grid-cols-2 gap-150">
                  <Stat label="Attempts" value={fmtNum(m.compliance.attempts)} />
                  <Stat label="Allowed" value={fmtNum(m.compliance.allowed)} />
                  <Stat
                    label="Denied"
                    value={fmtNum(m.compliance.denied)}
                    hint={fmtRate(m.compliance.denialRate)}
                  />
                  <Stat
                    label="Worst day touches"
                    value={`${fmtNum(m.compliance.worstDayTouches)} / ${fmtNum(m.compliance.dailyCap)}`}
                  />
                  <Stat label="Opt-outs" value={fmtNum(m.compliance.optOuts)} />
                  <Stat label="Breaches" value={fmtNum(m.compliance.breaches)} />
                </div>
                <p className="text-body-small text-text-subtle">{m.compliance.breachNote}</p>
                {m.compliance.complaints.available ? null : (
                  <SectionMessage
                    variant="information"
                    icon={CircleSlash}
                    title="Complaints are not measured"
                  >
                    {m.compliance.complaints.reason ?? "No complaint intake is wired up."}
                  </SectionMessage>
                )}
              </Panel>

              <Panel
                title="Borrower experience"
                description="How heavily the book is being contacted."
              >
                <div className="grid grid-cols-2 gap-150">
                  <Stat label="Cases" value={fmtNum(m.borrowerExperience.cases)} />
                  <Stat
                    label="Contacts per case"
                    value={fmtNum(m.borrowerExperience.contactsPerCase, 2)}
                  />
                  <Stat
                    label="Worst case"
                    value={`${fmtNum(m.borrowerExperience.worstCaseContacts)} contacts`}
                  />
                  <Stat
                    label="Over five contacts"
                    value={fmtNum(m.borrowerExperience.casesOverFiveContacts)}
                    hint={fmtRate(m.borrowerExperience.heavyCaseShare)}
                  />
                </div>
              </Panel>

              <Panel
                title="Capacity"
                description="Shadow prices per constrained resource. An unpriced resource never bound."
              >
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Resource</TableHead>
                      <TableHead className="text-right">Dual price</TableHead>
                      <TableHead className="text-right">Utilisation</TableHead>
                      <TableHead>Stability</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {m.capacity.resources.map((r) => (
                      <TableRow key={r.resource}>
                        <TableCell>{humanise(r.resource)}</TableCell>
                        <TableCell className="text-right tabular-nums">
                          {fmtInr(r.avgDualPriceInr)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {fmtRate(r.utilisation)}
                        </TableCell>
                        <TableCell>
                          <Lozenge tone={r.stability === "volatile" ? "warning" : "neutral"}>
                            {humanise(r.stability)}
                          </Lozenge>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Panel>
            </div>
          </div>
        )}
      </StateGate>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Model health — GET /treatment/model-health + GET /treatment/models
// ---------------------------------------------------------------------------

function ModelsTab({ days }: { days: number }) {
  const health = useTreatmentModelHealth(days);
  const models = useTreatmentModels();

  return (
    <div className="flex flex-col gap-200">
      <StateGate query={health} loadingLabel="Loading model health">
        {(h) => (
          <div className="flex flex-col gap-200">
            {h.alerts.length > 0 && (
              <div className="flex flex-col gap-100">
                {h.alerts.map((alert, i) => {
                  const isObject = typeof alert === "object" && alert !== null;
                  return (
                    <SectionMessage
                      key={isObject ? alert.metric : `${alert}-${i}`}
                      variant="warning"
                      icon={AlertTriangle}
                      title={isObject ? humanise(alert.metric) : "Model alert"}
                    >
                      {isObject ? alert.message : alert}
                    </SectionMessage>
                  );
                })}
              </div>
            )}

            <div className="grid grid-cols-2 gap-150 md:grid-cols-3 xl:grid-cols-6">
              <Stat label="Decisions sampled" value={fmtNum(h.decisions)} />
              <Stat
                label="Drift sample"
                value={fmtNum(h.driftSampled)}
                hint={`cap ${fmtNum(h.driftSampleLimit)}`}
              />
              <Stat
                label="Reach ECE"
                value={fmtRate(h.reachCalibration.ece, 2)}
                hint={`n = ${fmtNum(h.reachCalibration.n)}`}
              />
              <Stat label="Reach model" value={h.models.reach ?? "—"} />
              <Stat label="Uplift model" value={h.models.uplift ?? "—"} />
              <Stat label="Uplift segments" value={fmtNum(h.models.upliftSegments)} />
            </div>

            <div className="grid gap-200 lg:grid-cols-2">
              <Panel title="Feature drift" description="PSI against the training distribution.">
                {h.featureDrift.available && h.featureDrift.features.length > 0 ? (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Feature</TableHead>
                        <TableHead className="text-right">PSI</TableHead>
                        <TableHead>Verdict</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {h.featureDrift.features.map((f) => (
                        <TableRow key={f.feature}>
                          <TableCell>{humanise(f.feature)}</TableCell>
                          <TableCell className="text-right tabular-nums">
                            {fmtNum(f.psi, 3)}
                          </TableCell>
                          <TableCell>
                            <Lozenge tone={f.drifted ? "warning" : "success"}>
                              {f.drifted ? "Drifted" : "Stable"}
                            </Lozenge>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : (
                  <EmptyPanel
                    title="Drift is not measurable"
                    body={
                      h.featureDrift.reason ??
                      "No reference distribution is loaded, so there is nothing to drift from."
                    }
                    icon={CircleSlash}
                  />
                )}
              </Panel>

              <Panel title="Reach calibration" description={h.reachCalibration.quantity}>
                {h.reachCalibration.bins.length > 0 ? (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="text-right">Bin</TableHead>
                        <TableHead className="text-right">n</TableHead>
                        <TableHead className="text-right">Predicted</TableHead>
                        <TableHead className="text-right">Observed</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {h.reachCalibration.bins.map((b) => (
                        <TableRow key={b.bin}>
                          <TableCell className="text-right tabular-nums">
                            {fmtRate(b.bin, 0)}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">{fmtNum(b.n)}</TableCell>
                          <TableCell className="text-right tabular-nums">
                            {fmtRate(b.predicted)}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {fmtRate(b.observed)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : (
                  <EmptyPanel
                    title="No calibration sample"
                    body="No attempt in this window has a reach label, so predicted probabilities cannot be scored."
                    icon={CircleSlash}
                  />
                )}
              </Panel>
            </div>

            {h.upliftCalibration.available ? null : (
              <SectionMessage
                variant="information"
                icon={CircleSlash}
                title="Uplift calibration is unavailable"
              >
                {h.upliftCalibration.reason ??
                  "Predicted tau cannot be scored against a measured effect yet."}{" "}
                Treated {fmtNum(h.upliftCalibration.treatedN)}, control{" "}
                {fmtNum(h.upliftCalibration.controlN)}.
              </SectionMessage>
            )}
          </div>
        )}
      </StateGate>

      <StateGate
        query={models}
        loadingLabel="Loading model ledger"
        isEmpty={(d) => d.history.length === 0 && d.serving.length === 0}
        emptyTitle="No models registered"
        emptyBody="Nothing has been trained or promoted for this tenant yet, so the engine is running on priors."
        emptyIcon={BrainCircuit}
      >
        {(d) => (
          <div className="flex flex-col gap-200">
            <Panel
              title="What is actually serving"
              description="Whether the file on disk is the one a promotion produced. A registry that only records promotions cannot tell you an artifact was swapped afterwards."
            >
              {d.serving.length === 0 ? (
                <EmptyPanel
                  title="No serving check"
                  body="No target reported a serving state."
                  icon={CircleSlash}
                />
              ) : (
                <ul className="flex flex-col gap-100">
                  {d.serving.map((s) => (
                    <li
                      key={s.target}
                      className="flex items-center justify-between gap-150 rounded-medium border border-border p-100"
                    >
                      <span className="text-body font-medium text-text">{humanise(s.target)}</span>
                      <div className="flex min-w-0 items-center gap-100">
                        <span className="truncate text-body-small text-text-subtle">
                          {s.detail}
                        </span>
                        <Lozenge tone={SERVING_TONE[s.state] ?? "neutral"}>
                          {humanise(s.state)}
                        </Lozenge>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>

            <Panel
              title="Champion / challenger ledger"
              description="Every registered version, and the segment ladder the promoted one won on."
            >
              {d.history.length === 0 ? (
                <EmptyPanel
                  title="Nothing registered"
                  body="No training run has registered a version for this tenant."
                  icon={BrainCircuit}
                />
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Target</TableHead>
                      <TableHead>Version</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Corpus</TableHead>
                      <TableHead className="text-right">Samples</TableHead>
                      <TableHead className="text-right">Holdout AUC</TableHead>
                      <TableHead className="text-right">Segments</TableHead>
                      <TableHead>Registered</TableHead>
                      <TableHead>Promoted</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {d.history.map((m) => (
                      <TableRow key={m.id}>
                        <TableCell>{humanise(m.target)}</TableCell>
                        <TableCell className="tabular-nums">{m.version}</TableCell>
                        <TableCell>
                          <Lozenge tone={MODEL_STATUS_TONE[m.status] ?? "neutral"}>
                            {humanise(m.status)}
                          </Lozenge>
                        </TableCell>
                        <TableCell>
                          <Lozenge tone={m.corpus === "simulated" ? "warning" : "neutral"}>
                            {humanise(m.corpus)}
                          </Lozenge>
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {fmtNum(m.n_samples)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {fmtNum(m.metrics?.holdoutAuc ?? null, 4)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {fmtNum(m.segments_promoted)}
                        </TableCell>
                        <TableCell className="whitespace-nowrap tabular-nums text-text-subtle">
                          {fmtWhen(m.registered_at)}
                        </TableCell>
                        <TableCell className="whitespace-nowrap tabular-nums text-text-subtle">
                          {fmtWhen(m.promoted_at)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </Panel>

            {d.history
              .filter((m) => (m.metrics?.segmentLadder?.length ?? 0) > 0)
              .map((m) => (
                <Panel
                  key={`${m.id}-ladder`}
                  title={`Segment ladder — ${humanise(m.target)} ${m.version}`}
                  description="Which segments cleared the significance bar and held their lift out of sample."
                >
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Segment</TableHead>
                        <TableHead>Verdict</TableHead>
                        <TableHead className="text-right">ATE</TableHead>
                        <TableHead className="text-right">z / required</TableHead>
                        <TableHead className="text-right">Treated</TableHead>
                        <TableHead className="text-right">Control</TableHead>
                        <TableHead>Reason</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(m.metrics?.segmentLadder ?? []).map((rung) => (
                        <TableRow key={rung.segment}>
                          <TableCell>
                            <span className="text-body text-text">
                              {rung.label ?? rung.segment}
                            </span>
                            {rung.label ? (
                              <span className="block text-body-tiny text-text-subtlest">
                                {rung.segment}
                              </span>
                            ) : null}
                          </TableCell>
                          <TableCell>
                            <Lozenge tone={VERDICT_TONE[rung.verdict] ?? "neutral"}>
                              {humanise(rung.verdict)}
                            </Lozenge>
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {fmtRate(rung.ate ?? null, 2)}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {fmtNum(rung.z ?? null, 2)} / {fmtNum(rung.zRequired ?? null, 2)}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {fmtNum(rung.treatedN ?? null)}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {fmtNum(rung.controlN ?? null)}
                          </TableCell>
                          <TableCell className="text-body-small text-text-subtle">
                            {rung.reason ? humanise(rung.reason) : "—"}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </Panel>
              ))}
          </div>
        )}
      </StateGate>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Cases — GET /treatment/cases + GET /treatment/next
// ---------------------------------------------------------------------------

function CasesTab() {
  const [openOnly, setOpenOnly] = useState(true);
  const [selected, setSelected] = useState<TreatmentCase | null>(null);
  const cases = useTreatmentCases({ openOnly });

  return (
    <div className="flex flex-col gap-200">
      <Panel
        title="Cases"
        description="One row per (borrower, trigger) — the ladder already walked, and what is left."
        actions={
          <div className="flex shrink-0 items-center gap-100">
            <Label
              id="cases-open-only-label"
              htmlFor="cases-open-only"
              className="text-body-small text-text-subtle"
            >
              Open only
            </Label>
            <Switch
              id="cases-open-only"
              aria-labelledby="cases-open-only-label"
              checked={openOnly}
              onCheckedChange={setOpenOnly}
            />
          </div>
        }
      >
        <StateGate
          query={cases}
          loadingLabel="Loading cases"
          isEmpty={(d) => d.length === 0}
          emptyTitle={openOnly ? "No open cases" : "No cases"}
          emptyBody={
            openOnly
              ? "Every case the engine has decided on has since been paid or promised. Turn off “open only” to see the closed ones."
              : "The engine has not decided against any triggered case yet."
          }
          emptyIcon={Inbox}
        >
          {(rows) => (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Borrower</TableHead>
                  <TableHead>Trigger</TableHead>
                  <TableHead className="text-right">Decisions</TableHead>
                  <TableHead className="text-right">Attempts</TableHead>
                  <TableHead>Ladder</TableHead>
                  <TableHead>Last action</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Last decided</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((c) => (
                  <TableRow
                    key={`${c.customerId}-${c.id}`}
                    className="cursor-pointer"
                    data-state={selected?.customerId === c.customerId ? "selected" : undefined}
                    onClick={() => setSelected(c)}
                  >
                    <TableCell>
                      <span className="text-body text-text">{c.customerName}</span>
                      <span className="block text-body-tiny tabular-nums text-text-subtlest">
                        {c.accountId ?? c.customerId}
                      </span>
                    </TableCell>
                    <TableCell>
                      <span className="text-body text-text">{humanise(c.trigger)}</span>
                      <span className="block text-body-tiny tabular-nums text-text-subtlest">
                        {c.triggerRef}
                      </span>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{fmtNum(c.decisions)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmtNum(c.attempts)}</TableCell>
                    <TableCell>
                      {c.ladder.length === 0 ? (
                        <span className="text-body-small text-text-subtlest">nothing tried</span>
                      ) : (
                        <span className="flex flex-wrap gap-050">
                          {c.ladder.map((step, i) => (
                            <Lozenge key={`${step}-${i}`}>{humanise(step)}</Lozenge>
                          ))}
                        </span>
                      )}
                    </TableCell>
                    <TableCell>{humanise(c.lastAction)}</TableCell>
                    <TableCell>
                      {c.lastOutcome ? (
                        <Lozenge tone={c.lastOutcome === "paid" ? "success" : "information"}>
                          {humanise(c.lastOutcome)}
                        </Lozenge>
                      ) : c.lastSuppression ? (
                        <Lozenge tone="warning">{humanise(c.lastSuppression)}</Lozenge>
                      ) : (
                        <span className="text-body-small text-text-subtlest">—</span>
                      )}
                    </TableCell>
                    <TableCell className="whitespace-nowrap tabular-nums text-text-subtle">
                      {fmtWhen(c.lastDecidedAt)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </StateGate>
      </Panel>

      <NextTreatmentPanel selected={selected} />
    </div>
  );
}

function NextTreatmentPanel({ selected }: { selected: TreatmentCase | null }) {
  const next = useTreatmentNext(selected?.customerId, selected?.accountId ?? null, "manual");

  if (!selected) {
    return (
      <Panel
        title="Next best treatment"
        description="Select a case above to ask the engine what it would do right now."
      >
        <EmptyPanel
          title="No case selected"
          body="Pick a row to see the chosen action, the alternatives it beat, and everything vetoed before scoring."
          icon={Sparkles}
        />
      </Panel>
    );
  }

  return (
    <Panel
      title={`Next best treatment — ${selected.customerName}`}
      description="Read-only for the caller. The engine writes a decision row; outside live mode it enacts nothing."
    >
      <StateGate query={next} loadingLabel="Asking the engine">
        {(d) => (
          <div className="flex flex-col gap-150">
            <div className="flex flex-wrap items-center gap-100">
              <Lozenge tone={d.suppressed ? "warning" : "success"} size="spacious">
                {humanise(d.actionLabel || d.action)}
              </Lozenge>
              <Lozenge tone={d.mode === "live" ? "success" : "information"}>
                {humanise(d.mode)} mode
              </Lozenge>
              {d.variant ? <Lozenge>{humanise(d.variant)}</Lozenge> : null}
              {d.suppressed && d.reason ? (
                <Lozenge tone="warning">
                  <ShieldOff aria-hidden /> {humanise(d.reason)}
                </Lozenge>
              ) : null}
            </div>

            <p className="text-body text-text">{d.rationale}</p>

            <div className="grid grid-cols-2 gap-150 md:grid-cols-4">
              <Stat label="Expected value" value={fmtInr(d.expectedValueInr)} />
              <Stat label="Scheduled for" value={fmtWhen(d.at)} />
              <Stat label="Propensity" value={fmtRate(d.propensity)} />
              <Stat label="Latency" value={`${fmtNum(d.latencyMs)} ms`} />
            </div>

            {d.alternatives.length > 0 && (
              <div>
                <h3 className="mb-100 text-body-small font-semibold text-text-subtle">
                  Alternatives considered
                </h3>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Action</TableHead>
                      <TableHead className="text-right">Expected value</TableHead>
                      <TableHead className="text-right">Reach</TableHead>
                      <TableHead className="text-right">Resolve</TableHead>
                      <TableHead className="text-right">Cost</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {d.alternatives.map((alt) => (
                      <TableRow key={alt.action}>
                        <TableCell>{humanise(alt.action)}</TableCell>
                        <TableCell className="text-right tabular-nums">
                          {fmtInr(alt.expectedValue)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {fmtRate(alt.pReach)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {fmtRate(alt.pResolve)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {fmtInr(alt.cost)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}

            {Object.keys(d.excluded).length > 0 && (
              <div>
                <h3 className="mb-100 text-body-small font-semibold text-text-subtle">
                  Vetoed before scoring
                </h3>
                <ul className="flex flex-wrap gap-100">
                  {Object.entries(d.excluded).map(([action, why]) => (
                    <li key={action} className="flex items-center gap-050">
                      <Lozenge tone="neutral">
                        {humanise(action)} · {humanise(why)}
                      </Lozenge>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </StateGate>
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Holds — GET/POST /treatment/holds + POST /treatment/holds/{id}/release
// ---------------------------------------------------------------------------

function HoldsTab() {
  const [activeOnly, setActiveOnly] = useState(true);
  const [placeOpen, setPlaceOpen] = useState(false);
  const [releasing, setReleasing] = useState<TreatmentHold | null>(null);
  const holds = useTreatmentHolds({ activeOnly });

  return (
    <div className="flex flex-col gap-200">
      <Panel
        title="Collections holds"
        description="The veto the treatment engine reads. A hold stops outreach before any action is scored."
        actions={
          <div className="flex shrink-0 items-center gap-150">
            <div className="flex items-center gap-100">
              <Label
                id="holds-active-only-label"
                htmlFor="holds-active-only"
                className="text-body-small text-text-subtle"
              >
                Active only
              </Label>
              <Switch
                id="holds-active-only"
                aria-labelledby="holds-active-only-label"
                checked={activeOnly}
                onCheckedChange={setActiveOnly}
              />
            </div>
            <Button size="sm" variant="primary" onClick={() => setPlaceOpen(true)}>
              <Plus className="mr-075 h-3.5 w-3.5" /> Place a hold
            </Button>
          </div>
        }
      >
        <StateGate
          query={holds}
          loadingLabel="Loading holds"
          isEmpty={(d) => d.length === 0}
          emptyTitle={activeOnly ? "No active holds" : "No holds on record"}
          emptyBody={
            activeOnly
              ? "Nothing is vetoing outreach right now. Turn off “active only” to see released holds."
              : "No hold has ever been placed for this tenant."
          }
          emptyIcon={ShieldOff}
        >
          {(rows) => (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Borrower</TableHead>
                  <TableHead>Kind</TableHead>
                  <TableHead>Reason</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead>Placed</TableHead>
                  <TableHead>SLA due</TableHead>
                  <TableHead>Expires</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((h) => (
                  <TableRow key={h.id}>
                    <TableCell>
                      <span className="text-body text-text">{h.customerName ?? h.customerId}</span>
                      <span className="block text-body-tiny tabular-nums text-text-subtlest">
                        {h.accountId ?? h.customerId}
                      </span>
                    </TableCell>
                    <TableCell>
                      <Lozenge tone={HOLD_TONE[h.kind] ?? "neutral"}>{humanise(h.kind)}</Lozenge>
                    </TableCell>
                    <TableCell className="max-w-xs">
                      <span className="block truncate text-body-small text-text-subtle">
                        {h.reason ?? "—"}
                      </span>
                    </TableCell>
                    <TableCell className="text-body-small text-text-subtle">
                      {humanise(h.source)}
                      {h.placedBy ? (
                        <span className="block text-body-tiny text-text-subtlest">
                          {h.placedBy}
                        </span>
                      ) : null}
                    </TableCell>
                    <TableCell className="whitespace-nowrap tabular-nums text-text-subtle">
                      {fmtWhen(h.startsAt)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap tabular-nums text-text-subtle">
                      {fmtWhen(h.slaDueAt)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap tabular-nums text-text-subtle">
                      {h.expiresAt ? fmtWhen(h.expiresAt) : "no expiry"}
                    </TableCell>
                    <TableCell>
                      {h.active ? (
                        <Lozenge tone="success">Active</Lozenge>
                      ) : (
                        <Lozenge tone="neutral">Released</Lozenge>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      {h.active ? (
                        <Button size="sm" variant="outline" onClick={() => setReleasing(h)}>
                          Release
                        </Button>
                      ) : (
                        <span className="text-body-small text-text-subtlest">
                          {fmtWhen(h.releasedAt)}
                        </span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </StateGate>
      </Panel>

      <PlaceHoldDialog open={placeOpen} onOpenChange={setPlaceOpen} />
      <ReleaseHoldDialog hold={releasing} onOpenChange={(v) => !v && setReleasing(null)} />
    </div>
  );
}

function PlaceHoldDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const create = useCreateTreatmentHold();
  const [customerId, setCustomerId] = useState("");
  const [accountId, setAccountId] = useState("");
  const [kind, setKind] = useState<HoldKind>("hardship");
  const [source, setSource] = useState<HoldSource>("manual");
  const [reason, setReason] = useState("");
  const [expiresAt, setExpiresAt] = useState("");

  const reset = () => {
    setCustomerId("");
    setAccountId("");
    setKind("hardship");
    setSource("manual");
    setReason("");
    setExpiresAt("");
  };

  const canSubmit = customerId.trim().length > 0 && !create.isPending;

  const submit = () => {
    if (!canSubmit) return;
    create.mutate(
      {
        customerId: customerId.trim(),
        accountId: accountId.trim() || null,
        kind,
        source,
        reason: reason.trim() || null,
        // <input type="date"> gives a bare date; the column is a timestamptz.
        expiresAt: expiresAt ? new Date(`${expiresAt}T00:00:00`).toISOString() : null,
      },
      {
        onSuccess: (hold) => {
          toast.success(`${humanise(hold.kind)} hold in place`, {
            description: `${hold.customerName ?? hold.customerId} — outreach is vetoed until it is released.`,
          });
          reset();
          onOpenChange(false);
        },
        onError: (e) => toast.error(e instanceof Error ? e.message : "Could not place the hold"),
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Place a hold</DialogTitle>
          <DialogDescription>
            Stops collections outreach for this borrower. Re-placing an active hold of the same kind
            returns the existing one rather than creating a second.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-150">
          <div className="flex flex-col gap-050">
            <Label htmlFor="hold-customer">Borrower id</Label>
            <Input
              id="hold-customer"
              value={customerId}
              placeholder="priya-sharma"
              onChange={(e) => setCustomerId(e.target.value)}
            />
          </div>

          <div className="flex flex-col gap-050">
            <Label htmlFor="hold-account">Account id (optional)</Label>
            <Input
              id="hold-account"
              value={accountId}
              placeholder="AC-90881 — leave blank to hold every account"
              onChange={(e) => setAccountId(e.target.value)}
            />
          </div>

          <div className="grid grid-cols-2 gap-150">
            <div className="flex flex-col gap-050">
              <Label htmlFor="hold-kind">Kind</Label>
              <Select value={kind} onValueChange={(v) => setKind(v as HoldKind)}>
                <SelectTrigger id="hold-kind">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {HOLD_KINDS.map((k) => (
                    <SelectItem key={k} value={k}>
                      {humanise(k)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-050">
              <Label htmlFor="hold-source">Source</Label>
              <Select value={source} onValueChange={(v) => setSource(v as HoldSource)}>
                <SelectTrigger id="hold-source">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {HOLD_SOURCES.map((s) => (
                    <SelectItem key={s} value={s}>
                      {humanise(s)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="flex flex-col gap-050">
            <Label htmlFor="hold-expires">Expires (optional)</Label>
            <Input
              id="hold-expires"
              type="date"
              value={expiresAt}
              onChange={(e) => setExpiresAt(e.target.value)}
            />
          </div>

          <div className="flex flex-col gap-050">
            <Label htmlFor="hold-reason">Reason</Label>
            <Textarea
              id="hold-reason"
              value={reason}
              rows={3}
              placeholder="What the borrower said, or which desk asked for this."
              onChange={(e) => setReason(e.target.value)}
            />
          </div>

          {kind === "legal" || kind === "dispute" ? (
            <SectionMessage
              variant="information"
              icon={ShieldOff}
              title={
                kind === "legal"
                  ? "A legal hold still permits a statutory notice"
                  : "A dispute hold still permits a specialist call about the dispute"
              }
            >
              Every other kind stops outreach entirely.
            </SectionMessage>
          ) : null}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!canSubmit} onClick={submit}>
            {create.isPending ? "Placing…" : "Place hold"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ReleaseHoldDialog({
  hold,
  onOpenChange,
}: {
  hold: TreatmentHold | null;
  onOpenChange: (v: boolean) => void;
}) {
  const release = useReleaseTreatmentHold();
  const [reason, setReason] = useState("");
  const label = useMemo(
    () => (hold ? `${humanise(hold.kind)} hold on ${hold.customerName ?? hold.customerId}` : ""),
    [hold],
  );

  const submit = () => {
    if (!hold) return;
    release.mutate(
      { holdId: hold.id, reason: reason.trim() || null },
      {
        onSuccess: () => {
          toast.success("Hold released", {
            description: `${label} — the engine may schedule outreach again.`,
          });
          setReason("");
          onOpenChange(false);
        },
        onError: (e) => toast.error(e instanceof Error ? e.message : "Could not release the hold"),
      },
    );
  };

  return (
    <Dialog open={hold !== null} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Release this hold</DialogTitle>
          <DialogDescription>
            {label ? `${label}. ` : ""}Outreach becomes possible again as soon as this is lifted.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-050">
          <Label htmlFor="release-reason">Reason (optional)</Label>
          <Textarea
            id="release-reason"
            value={reason}
            rows={3}
            placeholder="Why the hold no longer applies."
            onChange={(e) => setReason(e.target.value)}
          />
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="danger" disabled={release.isPending} onClick={submit}>
            {release.isPending ? "Releasing…" : "Release hold"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
