/** Cases -- GET /treatment/cases, and the next-treatment panel for the selected one. */
import { useState } from "react";
import { Inbox, ShieldOff, Sparkles } from "lucide-react";

import { Label } from "@/components/ui/label";
import { Lozenge } from "@/components/ui/lozenge";
import { Switch } from "@/components/ui/switch";
import { Select } from "@/components/ui/select";
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
  useTreatmentCases,
  useTreatmentNext,
  type TreatmentCase,
} from "@/api/treatment";

// ---------------------------------------------------------------------------
// Shared state scaffolding
//
// Loading, empty and error are rendered by one component so no section can
// quietly skip one. The error branch renders INSTEAD of the data — a failed
// live call must never fall through to a half-populated table, because a
// plausible-looking number with no backend behind it is worse than a gap.
// ---------------------------------------------------------------------------
import { EmptyPanel, Panel, Stat, StateGate } from "./chrome";
import { fmtDateTime } from "@/lib/format";

export function CasesTab() {
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
                      {fmtDateTime(c.lastDecidedAt)}
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

export function NextTreatmentPanel({ selected }: { selected: TreatmentCase | null }) {
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
              <Stat label="Scheduled for" value={fmtDateTime(d.at)} />
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
