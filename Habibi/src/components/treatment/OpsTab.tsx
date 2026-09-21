import { toast } from "sonner";
import { Inbox, Landmark, MapPin, Scale } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useConfirm } from "@/components/ui/use-confirm";
import { fmtInr, humanise, useEnactTreatmentDecision, useTreatmentOps } from "@/api/treatment";
import { Panel, StateGate } from "./chrome";
import { fmtDateTime } from "@/lib/format";
import { mutationErrorMessage } from "@/lib/mutation-errors";
import { ApiError } from "@/api/config";
import { idempotencyKey } from "@/lib/utils";
import { useState } from "react";

type Kind = "mandates" | "field" | "legal";

const COPY: Record<Kind, { title: string; description: string; icon: typeof Landmark }> = {
  mandates: {
    title: "Mandates",
    description: "Presentments the engine asked for. Confirming re-presents once.",
    icon: Landmark,
  },
  field: {
    title: "Field visits",
    description: "Dispatch queue. Confirming enqueues the visit; it is not a legal hold.",
    icon: MapPin,
  },
  legal: {
    title: "Legal notices",
    description: "Statutory notices (registered post / SARFAESI). Distinct from the Holds tab.",
    icon: Scale,
  },
};

export function OpsTab({ kind, customerId }: { kind: Kind; customerId?: string }) {
  const query = useTreatmentOps(kind, customerId);
  const enact = useEnactTreatmentDecision();
  const { confirm, confirmDialog } = useConfirm();
  const [agency, setAgency] = useState("");
  const [scheduledDate, setScheduledDate] = useState("");
  const [servedAt, setServedAt] = useState("");
  const [method, setMethod] = useState("registered_post");
  const copy = COPY[kind];

  return (
    <div className="flex flex-col gap-200">
      <Panel title={copy.title} description={copy.description}>
        {kind === "field" ? (
          <div className="mb-150 grid gap-150 sm:grid-cols-2">
            <div className="space-y-050">
              <Label htmlFor="field-agency">Agency</Label>
              <Input id="field-agency" value={agency} onChange={(e) => setAgency(e.target.value)} />
            </div>
            <div className="space-y-050">
              <Label htmlFor="field-date">Visit date</Label>
              <Input
                id="field-date"
                type="date"
                value={scheduledDate}
                onChange={(e) => setScheduledDate(e.target.value)}
              />
            </div>
          </div>
        ) : null}
        {kind === "legal" ? (
          <div className="mb-150 grid gap-150 sm:grid-cols-2">
            <div className="space-y-050">
              <Label htmlFor="legal-served">Served at</Label>
              <Input
                id="legal-served"
                type="datetime-local"
                value={servedAt}
                onChange={(e) => setServedAt(e.target.value)}
              />
            </div>
            <div className="space-y-050">
              <Label htmlFor="legal-method">Method</Label>
              <Input id="legal-method" value={method} onChange={(e) => setMethod(e.target.value)} />
            </div>
          </div>
        ) : null}
        <StateGate
          query={query}
          loadingLabel={`Loading ${copy.title.toLowerCase()}`}
          isEmpty={(d) => d.length === 0}
          emptyTitle={`No ${copy.title.toLowerCase()}`}
          emptyBody="Nothing waiting for an operator on this filter."
          emptyIcon={Inbox}
        >
          {(rows) => (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Borrower</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead className="text-right">Expected</TableHead>
                  <TableHead>Mode</TableHead>
                  <TableHead>Scheduled</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => {
                  const shadow = row.mode !== "live" || row.enacted;
                  return (
                    <TableRow
                      key={row.decisionId}
                      data-state={row.customerId === customerId ? "selected" : undefined}
                    >
                      <TableCell>
                        <span className="text-body text-text">{row.customerName}</span>
                        <span className="block text-body-tiny tabular-nums text-text-subtlest">
                          {row.accountId ?? row.customerId}
                        </span>
                      </TableCell>
                      <TableCell>{humanise(row.action)}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {fmtInr(row.expectedValueInr)}
                      </TableCell>
                      <TableCell>{row.mode}</TableCell>
                      <TableCell className="whitespace-nowrap tabular-nums text-text-subtle">
                        {fmtDateTime(row.scheduledAt)}
                      </TableCell>
                      <TableCell className="text-right">
                        {row.enacted ? (
                          <span className="text-body-small text-text-subtlest">
                            Already carried out
                          </span>
                        ) : shadow ? (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => toast.message("View only while the engine is not live")}
                          >
                            View decision
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            disabled={enact.isPending}
                            onClick={async () => {
                              if (
                                !(await confirm({
                                  title: `Carry out ${humanise(row.action)}?`,
                                  description: `${row.customerName} · expected ${fmtInr(row.expectedValueInr)}`,
                                  confirmLabel: "Confirm and enact",
                                }))
                              )
                                return;
                              enact.mutate(
                                {
                                  decisionId: row.decisionId,
                                  idempotencyKey: idempotencyKey(`enact-${row.decisionId}`),
                                  agency: kind === "field" ? agency : undefined,
                                  scheduledDate: kind === "field" ? scheduledDate : undefined,
                                  servedAt: kind === "legal" ? servedAt : undefined,
                                  method: kind === "legal" ? method : undefined,
                                },
                                {
                                  onSuccess: (res) => {
                                    if (String(res.note).startsWith("already_enacted")) {
                                      toast.success(
                                        `Already carried out (${res.enactedRef || res.note})`,
                                      );
                                      return;
                                    }
                                    toast.success("Enacted");
                                  },
                                  onError: (err) => {
                                    if (
                                      err instanceof ApiError &&
                                      err.status === 409 &&
                                      err.detail.startsWith("already_enacted")
                                    ) {
                                      toast.success(`Already carried out (${err.detail})`);
                                      return;
                                    }
                                    toast.error(mutationErrorMessage(err));
                                  },
                                },
                              );
                            }}
                          >
                            Confirm
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </StateGate>
      </Panel>
      {confirmDialog}
      {kind === "legal" ? (
        <p className="text-body-small text-text-subtle">
          A legal hold pauses outreach. A legal notice starts a statutory clock. They are not the
          same queue.
        </p>
      ) : null}
    </div>
  );
}
