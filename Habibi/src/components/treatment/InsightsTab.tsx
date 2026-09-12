/** Insights -- GET /treatment/insights + GET /treatment/metrics. */
import { Ban, CircleSlash, Sparkles } from "lucide-react";

import { Lozenge } from "@/components/ui/lozenge";
import { SectionMessage } from "@/components/ui/section-message";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  fmtInr,
  fmtNum,
  fmtRate,
  humanise,
  useTreatmentInsights,
  useTreatmentMetrics,
} from "@/api/treatment";

// ---------------------------------------------------------------------------
// Shared state scaffolding
//
// Loading, empty and error are rendered by one component so no section can
// quietly skip one. The error branch renders INSTEAD of the data — a failed
// live call must never fall through to a half-populated table, because a
// plausible-looking number with no backend behind it is worse than a gap.
// ---------------------------------------------------------------------------
import { BarList, EmptyPanel, Panel, Stat, StateGate } from "./chrome";

export function InsightsTab({ days }: { days: number }) {
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
