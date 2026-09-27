/** Cases -- GET /treatment/cases, and the current decision for the selected one. */
import { useEffect, useState } from "react";
import { Inbox, RefreshCw, ShieldOff, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Lozenge } from "@/components/ui/lozenge";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { fmtNum, humanise, useTreatmentCases, type TreatmentCase } from "@/api/treatment";
import { useCurrentDecision, useDecideNow } from "@/api/treatment-trace";

import { TraceBody } from "./DecisionTraceSheet";
import { EmptyPanel, Panel, StateGate } from "./chrome";
import { fmtDateTime } from "@/lib/format";

export function CasesTab({ customerId }: { customerId?: string }) {
  const [openOnly, setOpenOnly] = useState(true);
  const [selected, setSelected] = useState<TreatmentCase | null>(null);
  const cases = useTreatmentCases({ openOnly, customerId: customerId ?? null });

  useEffect(() => {
    if (!customerId || !cases.data) return;
    const match = cases.data.find((c) => c.customerId === customerId);
    if (match) setSelected(match);
  }, [customerId, cases.data]);

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
  const current = useCurrentDecision(selected?.customerId, selected?.accountId ?? null);
  const decide = useDecideNow();

  if (!selected) {
    return (
      <Panel
        title="Next best action"
        description="Select a case above to see the engine's current decision for that borrower."
      >
        <EmptyPanel
          title="No case selected"
          body="Pick a row to see what the engine decided, every option it weighed, and why."
          icon={Sparkles}
        />
      </Panel>
    );
  }

  return (
    <Panel
      title={`Next best action — ${selected.customerName}`}
      description="The engine's latest recorded decision for this borrower, the same one the customer card and the agent copilot show."
      actions={
        <Button
          size="sm"
          variant="outline"
          disabled={decide.isPending}
          onClick={() =>
            decide.mutate({ customerId: selected.customerId, accountId: selected.accountId })
          }
        >
          <RefreshCw className="mr-075 h-3.5 w-3.5" /> Decide now
        </Button>
      }
    >
      <StateGate query={current} loadingLabel="Loading the current decision">
        {(d) =>
          d.decision ? (
            <TraceBody t={d.decision} />
          ) : (
            <EmptyPanel
              title="No recent decision"
              body="Nothing has triggered a decision for this borrower in the last week. “Decide now” asks the engine and records its answer without carrying it out."
              icon={ShieldOff}
            />
          )
        }
      </StateGate>
    </Panel>
  );
}

