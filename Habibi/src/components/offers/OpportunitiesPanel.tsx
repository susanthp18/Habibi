/** Opportunities: buying signals customers expressed, and the offers they led to. */
import { useState } from "react";
import { Inbox, Sparkles } from "lucide-react";

import { Lozenge } from "@/components/ui/lozenge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Panel, StateGate } from "@/components/treatment/chrome";
import { humanise } from "@/api/treatment";
import { useOfferLog, useOpportunities, useSignalHealth } from "@/api/offer-trace";
import { fmtDateTime } from "@/lib/format";

import { OfferTraceSheet, SignalRow } from "./OfferTraceSheet";

/** The upsell page's queue: every offer decision, and how the signal sweep is doing. */
export function OpportunitiesQueue() {
  const log = useOfferLog();
  const health = useSignalHealth();
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className="grid shrink-0 gap-150 lg:grid-cols-3">
      <div className="lg:col-span-2">
        <Panel
          title="Opportunities"
          description="Offers the engine decided, most from what customers said on calls and chats. Offers are never raised on a collections call; they go out separately, only with marketing consent."
        >
          <StateGate
            query={log}
            loadingLabel="Loading offers"
            isEmpty={(rows) => rows.length === 0}
            emptyTitle="No offer decisions yet"
            emptyBody="Offers are decided nightly for customers who said something a product could serve and who have agreed to marketing."
            emptyIcon={Inbox}
          >
            {(rows) => (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>When</TableHead>
                    <TableHead>Customer</TableHead>
                    <TableHead>Offer</TableHead>
                    <TableHead>Why</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.slice(0, 25).map((r) => (
                    <TableRow key={r.id} className="cursor-pointer" onClick={() => setOpen(r.id)}>
                      <TableCell className="whitespace-nowrap tabular-nums text-text-subtle">
                        {fmtDateTime(r.created_at)}
                      </TableCell>
                      <TableCell>{r.customer_name ?? r.customer_id}</TableCell>
                      <TableCell>{r.product_name ?? (r.suppression_reason ? "None" : "—")}</TableCell>
                      <TableCell className="text-body-small text-text-subtle">
                        {r.holdReasonText ??
                          (r.signals ? `${r.signals} thing${r.signals > 1 ? "s" : ""} they said` : "scored on a call")}
                      </TableCell>
                      <TableCell>
                        {r.response ? (
                          <Lozenge tone={r.response === "interested" ? "success" : "neutral"}>
                            {humanise(r.response)}
                          </Lozenge>
                        ) : r.presented ? (
                          <Lozenge tone="success">Sent</Lozenge>
                        ) : r.suppression_reason ? (
                          <Lozenge>Held</Lozenge>
                        ) : (
                          <Lozenge tone="information">Queued</Lozenge>
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
      <Panel
        title="Listening for signals"
        description="Finished conversations read for buying signals in the last 30 days, and why some were not read."
      >
        <StateGate query={health} loadingLabel="Loading">
          {(h) => (
            <div className="flex flex-col gap-150 text-body-small">
              <ul className="flex flex-col gap-050">
                {h.scans.length === 0 ? <li className="text-text-subtle">No conversation read yet.</li> : null}
                {h.scans.map((s) => (
                  <li key={`${s.status}-${s.skip_reason}`} className="flex justify-between gap-100">
                    <span className="text-text">
                      {s.status === "done" ? "Read" : s.status === "skipped" ? `Not read: ${s.skipText}` : humanise(s.status)}
                    </span>
                    <span className="tabular-nums text-text-subtle">{s.n}</span>
                  </li>
                ))}
              </ul>
              {h.codes.length ? (
                <ul className="flex flex-col gap-050 border-t border-border pt-100">
                  {h.codes.map((c) => (
                    <li key={c.signal_code} className="flex justify-between gap-100">
                      <span className="text-text">{c.label}</span>
                      <span className="tabular-nums text-text-subtle">
                        {c.found}
                        {c.right + c.wrong ? ` · ${Math.round((100 * c.right) / (c.right + c.wrong))}% right` : ""}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          )}
        </StateGate>
      </Panel>
      <OfferTraceSheet decisionId={open} onClose={() => setOpen(null)} />
    </div>
  );
}

/** The customer card's panel: what they said, and what was offered because of it. */
export function CustomerOpportunities({ customerId }: { customerId: string }) {
  const data = useOpportunities(customerId);
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className="rounded-large border border-border bg-surface">
      <div className="border-b border-border px-200 py-150">
        <div className="flex items-center gap-075 text-body-small font-semibold text-text">
          <Sparkles className="h-3.5 w-3.5 text-text-brand" /> Opportunities
        </div>
        <div className="text-body-small text-text-subtlest">
          What this customer said that a product could serve. Never raised on a collections call.
        </div>
      </div>
      <div className="px-200 py-150">
        <StateGate query={data} loadingLabel="Loading">
          {(d) => (
            <div className="flex flex-col gap-150">
              {d.signals.length ? (
                <ul className="flex flex-col gap-100">
                  {d.signals.slice(0, 5).map((s) => (
                    <SignalRow key={s.id} s={s} />
                  ))}
                </ul>
              ) : (
                <p className="text-body-small text-text-subtle">
                  Nothing heard yet. Conversations are read only when the customer has agreed to marketing.
                </p>
              )}
              {d.decision ? (
                <button
                  type="button"
                  className="text-left text-body-small text-text-link underline"
                  onClick={() => setOpen(d.decision!.id)}
                >
                  Latest offer: {d.decision.choice.name ?? "none"}
                  {d.decision.choice.holdReasonText ? ` (${d.decision.choice.holdReasonText})` : ""}. Why?
                </button>
              ) : null}
            </div>
          )}
        </StateGate>
      </div>
      <OfferTraceSheet decisionId={open} onClose={() => setOpen(null)} />
    </div>
  );
}
