/** Is it working? Lift against the comparison group, and what the engine has learned. */
import { Ban, GraduationCap } from "lucide-react";

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
import { fmtInr, fmtNum, fmtRate, useTreatmentMetrics } from "@/api/treatment";
import { useLearnedRates } from "@/api/treatment-trace";

import { Panel, Stat, StateGate } from "./chrome";

export function ResultsTab({ days }: { days: number }) {
  const metrics = useTreatmentMetrics(Math.max(days, 28));
  const learned = useLearnedRates();
  return (
    <div className="flex flex-col gap-200">
      <StateGate query={metrics} loadingLabel="Loading results">
        {(m) => (
          <>
            <Panel
              title="Does contacting people help?"
              description="Borrowers are split at random: most get the engine's decisions, a small comparison group gets only what policy requires. The difference in cure rate is what the engine adds, beyond people who would have paid anyway."
            >
              {m.causal.available ? (
                <div className="grid grid-cols-2 gap-150 md:grid-cols-4">
                  <Stat
                    label="Extra cure rate from the engine"
                    value={fmtRate(m.causal.incrementalCureRate ?? null)}
                    hint={
                      m.causal.incrementalCureRateInterval
                        ? `likely between ${fmtRate(m.causal.incrementalCureRateInterval.low)} and ${fmtRate(m.causal.incrementalCureRateInterval.high)}`
                        : undefined
                    }
                  />
                  <Stat label="Cure rate with the engine" value={fmtRate(m.causal.treatedCureRate ?? null)} />
                  <Stat label="Cure rate, comparison group" value={fmtRate(m.causal.controlCureRate ?? null)} />
                  <Stat
                    label="Recovered because of it"
                    value={fmtInr(m.causal.attributableRecoveryInr ?? null)}
                    hint={
                      m.causal.incrementalRecoveryPerRupee != null
                        ? `₹${m.causal.incrementalRecoveryPerRupee} per ₹1 spent`
                        : undefined
                    }
                  />
                </div>
              ) : (
                <SectionMessage variant="information" icon={Ban} title="Not enough evidence yet to say">
                  {m.causal.controlN != null
                    ? `So far ${fmtNum(m.causal.treatedN)} contacted and ${fmtNum(m.causal.controlN)} comparison cases have a final outcome. `
                    : ""}
                  The answer needs about 40 borrowers in each group with eight weeks of outcomes; below
                  that, any difference could be chance.
                </SectionMessage>
              )}
            </Panel>
            <div className="grid grid-cols-2 gap-150 md:grid-cols-4">
              <Stat label="Resolved cases" value={fmtNum(m.efficiency.resolutions)} hint="paid or promised" />
              <Stat label="Contacts made" value={fmtNum(m.efficiency.contacts)} />
              <Stat label="Contacts per resolution" value={fmtNum(m.efficiency.contactsPerResolution, 1)} />
              <Stat label="Recovered in window" value={fmtInr(m.efficiency.recoveredInr)} />
            </div>
          </>
        )}
      </StateGate>

      <Panel
        title="What the engine has learned"
        description="Every probability starts as a planning assumption. As outcomes come in, each is re-estimated nightly: a few outcomes nudge it, hundreds replace it."
      >
        <StateGate query={learned} loadingLabel="Loading learned rates">
          {(rows) => (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Probability</TableHead>
                  <TableHead className="text-right">Assumed</TableHead>
                  <TableHead className="text-right">Now using</TableHead>
                  <TableHead className="text-right">Evidence</TableHead>
                  <TableHead>Source</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((r) => (
                  <TableRow key={`${r.metric}-${r.key}`}>
                    <TableCell>{r.label}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmtRate(r.prior ?? r.value)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmtRate(r.value)}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {r.trials ? `${fmtNum(r.successes ?? 0)} of ${fmtNum(r.trials)}` : "—"}
                    </TableCell>
                    <TableCell>
                      {r.source === "learned" ? (
                        <Lozenge tone="success">
                          <GraduationCap aria-hidden /> Learned
                        </Lozenge>
                      ) : (
                        <Lozenge>Assumption</Lozenge>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </StateGate>
      </Panel>
    </div>
  );
}
