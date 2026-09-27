/** Decisions: every decision the engine made, searchable, each one explainable. */
import { useState } from "react";
import { Download, Inbox } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
import { fmtInr, humanise } from "@/api/treatment";
import {
  downloadDecisionLog,
  triggerLabel,
  useDecisionLog,
  type DecisionLogRow,
} from "@/api/treatment-trace";
import { fmtDateTime } from "@/lib/format";

import { DecisionTraceSheet } from "./DecisionTraceSheet";
import { Panel, StateGate } from "./chrome";

const PAGE = 50;

export function DecisionsTab({ customerId }: { customerId?: string }) {
  const [customer, setCustomer] = useState(customerId ?? "");
  const [heldOnly, setHeldOnly] = useState(false);
  const [page, setPage] = useState(0);
  const [open, setOpen] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const query = {
    customerId: customer.trim() || null,
    held: heldOnly ? true : null,
    limit: PAGE,
    offset: page * PAGE,
  };
  const log = useDecisionLog(query);

  return (
    <>
      <Panel
        title="Decisions"
        description="Every decision the engine recorded, newest first. Open one to see what it knew, every option it weighed, why it chose, and what happened."
        actions={
          <div className="flex shrink-0 flex-wrap items-center gap-150">
            <Input
              aria-label="Customer id"
              placeholder="Customer id"
              className="w-44"
              value={customer}
              onChange={(e) => {
                setCustomer(e.target.value);
                setPage(0);
              }}
            />
            <div className="flex items-center gap-075">
              <Label
                id="decisions-held-label"
                htmlFor="decisions-held"
                className="text-body-small text-text-subtle"
              >
                Held only
              </Label>
              <Switch
                id="decisions-held"
                aria-labelledby="decisions-held-label"
                checked={heldOnly}
                onCheckedChange={(v) => {
                  setHeldOnly(v);
                  setPage(0);
                }}
              />
            </div>
            <Button
              size="sm"
              variant="outline"
              disabled={exporting}
              onClick={() => {
                setExporting(true);
                void downloadDecisionLog(query).finally(() => setExporting(false));
              }}
            >
              <Download className="mr-075 h-3.5 w-3.5" /> Export CSV
            </Button>
          </div>
        }
      >
        <StateGate
          query={log}
          loadingLabel="Loading decisions"
          isEmpty={(rows) => rows.length === 0}
          emptyTitle="No decisions"
          emptyBody="No decision matches these filters yet."
          emptyIcon={Inbox}
        >
          {(rows) => (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>When</TableHead>
                    <TableHead>Borrower</TableHead>
                    <TableHead>Because</TableHead>
                    <TableHead>Decision</TableHead>
                    <TableHead className="text-right">Expected value</TableHead>
                    <TableHead>Result</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((r) => (
                    <TableRow key={r.id} className="cursor-pointer" onClick={() => setOpen(r.id)}>
                      <TableCell className="whitespace-nowrap tabular-nums text-text-subtle">
                        {fmtDateTime(r.created_at)}
                      </TableCell>
                      <TableCell>
                        <span className="text-body text-text">{r.customer_name}</span>
                        <span className="block text-body-tiny tabular-nums text-text-subtlest">
                          {r.account_id ?? r.customer_id}
                        </span>
                      </TableCell>
                      <TableCell>{triggerLabel(r.trigger_kind)}</TableCell>
                      <TableCell>
                        <DecisionCell r={r} />
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{fmtInr(r.expected_value)}</TableCell>
                      <TableCell>
                        {r.outcome ? (
                          <Lozenge tone={r.outcome === "paid" ? "success" : "information"}>
                            {humanise(r.outcome)}
                          </Lozenge>
                        ) : r.enacted ? (
                          <Lozenge tone="success">Carried out</Lozenge>
                        ) : (
                          <span className="text-body-small text-text-subtlest">—</span>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <div className="flex items-center justify-end gap-100">
                <Button size="sm" variant="outline" disabled={page === 0} onClick={() => setPage(page - 1)}>
                  Newer
                </Button>
                <Button size="sm" variant="outline" disabled={rows.length < PAGE} onClick={() => setPage(page + 1)}>
                  Older
                </Button>
              </div>
            </>
          )}
        </StateGate>
      </Panel>
      <DecisionTraceSheet decisionId={open} onClose={() => setOpen(null)} />
    </>
  );
}

function DecisionCell({ r }: { r: DecisionLogRow }) {
  const shadow = r.suppression_reason === "shadow_mode";
  const held = r.suppression_reason && !shadow;
  return (
    <div className="flex flex-col gap-025">
      <span className="flex flex-wrap items-center gap-050">
        <span className="text-body text-text">{held ? "Hold" : humanise(r.chosen_action)}</span>
        {shadow ? <Lozenge tone="information">Not carried out (shadow)</Lozenge> : null}
        {r.explore_kind === "ranked" ? <Lozenge tone="discovery">Exploring</Lozenge> : null}
        {r.explore_kind === "control_arm" ? <Lozenge>Comparison group</Lozenge> : null}
      </span>
      {held ? <span className="text-body-tiny text-text-subtle">{r.holdReasonText}</span> : null}
    </div>
  );
}
