/** Model health -- GET /treatment/models + GET /treatment/model-health. */
import { AlertTriangle, BrainCircuit, CircleSlash } from "lucide-react";

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
  fmtNum,
  fmtRate,
  humanise,
  useTreatmentModelHealth,
  useTreatmentModels,
} from "@/api/treatment";

// ---------------------------------------------------------------------------
// Shared state scaffolding
//
// Loading, empty and error are rendered by one component so no section can
// quietly skip one. The error branch renders INSTEAD of the data — a failed
// live call must never fall through to a half-populated table, because a
// plausible-looking number with no backend behind it is worse than a gap.
// ---------------------------------------------------------------------------
import {
  EmptyPanel,
  MODEL_STATUS_TONE,
  Panel,
  SERVING_TONE,
  Stat,
  StateGate,
  VERDICT_TONE,
} from "./chrome";
import { fmtDateTime } from "@/lib/format";

export function ModelsTab({ days }: { days: number }) {
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
                          {fmtDateTime(m.registered_at)}
                        </TableCell>
                        <TableCell className="whitespace-nowrap tabular-nums text-text-subtle">
                          {fmtDateTime(m.promoted_at)}
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
