import { useMemo } from "react";
import { Bot, MessageCircle, MessageSquare, Phone } from "lucide-react";
import { RecordsTable, type RecordsColumn } from "@/components/records/RecordsTable";
import { Lozenge, type LozengeProps } from "@/components/ui/lozenge";
import { SentimentBubble } from "./SentimentBubble";
import {
  channelLabel,
  LIVE_QA_STATUS_LABEL,
  LIVE_QA_STATUS_TONE,
  type ActiveCall,
} from "@/data/floor-seed";
import { OFFER_STATUS_LABEL, OFFER_STATUS_TONE } from "@/lib/offer-policy";
import { AUTHORITY_STATUS_LABEL, AUTHORITY_STATUS_TONE } from "@/lib/authority-policy";
import { cn } from "@/lib/utils";

const fmtDur = (s: number) => {
  const m = Math.floor(s / 60)
    .toString()
    .padStart(2, "0");
  const r = Math.floor(s % 60)
    .toString()
    .padStart(2, "0");
  return `${m}:${r}`;
};

const riskTone = {
  high: "danger",
  medium: "warning",
  low: "success",
} as const satisfies Record<ActiveCall["risk"], LozengeProps["tone"]>;

const ChannelIcon = ({ ch }: { ch: ActiveCall["channel"] }) => {
  const I = ch === "whatsapp" ? MessageCircle : ch === "sms" ? MessageSquare : Phone;
  return <I className="h-3 w-3" />;
};

export function LiveTable({
  rows,
  activeId,
  onSelect,
}: {
  rows: ActiveCall[];
  activeId: string | null;
  onSelect: (call: ActiveCall) => void;
}) {
  const columns = useMemo<RecordsColumn<ActiveCall>[]>(
    () => [
      {
        id: "customer",
        header: "Customer",
        sticky: true,
        sortable: true,
        sortValue: (r) => r.customer,
        cell: (r) => (
          <div className="min-w-0">
            <div className="flex items-center gap-075">
              <span className="truncate font-semibold text-text">{r.customer}</span>
              {r.pendingHandoff && <Lozenge tone="warning">Queue</Lozenge>}
              {r.offerPolicy && r.offerPolicy.status !== "none" ? (
                <Lozenge tone={OFFER_STATUS_TONE[r.offerPolicy.status]}>
                  {OFFER_STATUS_LABEL[r.offerPolicy.status]}
                </Lozenge>
              ) : null}
              {r.authorityPolicy && r.authorityPolicy.status !== "none" ? (
                <Lozenge tone={AUTHORITY_STATUS_TONE[r.authorityPolicy.status]}>
                  {AUTHORITY_STATUS_LABEL[r.authorityPolicy.status]}
                </Lozenge>
              ) : null}
              {r.liveQa && r.liveQa.status && r.liveQa.status !== "none" ? (
                <Lozenge tone={LIVE_QA_STATUS_TONE[r.liveQa.status] ?? "warning"}>
                  {LIVE_QA_STATUS_LABEL[r.liveQa.status] ??
                    r.liveQa.reason?.replace(/-/g, " ") ??
                    "Live QA"}
                </Lozenge>
              ) : null}
            </div>
            <div className="mt-025 flex items-center gap-050 text-body-small text-text-subtlest">
              <span className="tabular">••{r.accountTail}</span>
              <span>·</span>
              <ChannelIcon ch={r.channel} />
              <span>{channelLabel[r.channel]}</span>
            </div>
          </div>
        ),
      },
      {
        id: "handler",
        header: "Handler",
        sortable: true,
        sortValue: (r) => r.handler.name,
        cell: (r) => (
          <div className="flex items-center gap-075">
            {r.handler.kind === "bot" ? (
              <Bot className="h-3.5 w-3.5 text-text-warning" />
            ) : (
              <span className="grid h-300 w-300 place-items-center rounded-full bg-background-brand-subtlest text-body-small font-semibold text-text-brand">
                {r.handler.initials}
              </span>
            )}
            <span className="truncate text-body-small text-text">{r.handler.name}</span>
          </div>
        ),
      },
      {
        id: "topic",
        header: "Topic",
        sortable: true,
        sortValue: (r) => r.topic,
        cell: (r) => <span className="truncate text-body-small text-text-subtle">{r.topic}</span>,
      },
      {
        id: "duration",
        header: "Time",
        sortable: true,
        sortValue: (r) => r.durationSec,
        align: "right",
        cell: (r) => (
          <span className="tabular text-body-small font-semibold text-text">
            {fmtDur(r.durationSec)}
          </span>
        ),
      },
      {
        id: "sentiment",
        header: "Sentiment",
        sortable: true,
        sortValue: (r) => r.sentiment,
        cell: (r) => <SentimentBubble value={r.sentiment} trend={r.sentimentTrend} />,
      },
      {
        id: "risk",
        header: "Risk",
        sortable: true,
        sortValue: (r) => ({ high: 3, medium: 2, low: 1 })[r.risk],
        cell: (r) => <Lozenge tone={riskTone[r.risk]}>{r.risk}</Lozenge>,
      },
      {
        id: "last",
        header: "Last line",
        cell: (r) => (
          <p className="line-clamp-1 max-w-[22rem] text-body-small italic text-text-subtle">
            “{r.lastLine}”
          </p>
        ),
      },
    ],
    [],
  );

  return (
    <div className={cn("min-h-0 min-w-0 flex-1 overflow-hidden")}>
      <RecordsTable
        rows={rows}
        getRowId={(r) => r.id}
        columns={columns}
        activeRowId={activeId}
        onRowClick={onSelect}
        defaultSort={{ id: "risk", dir: -1 }}
        emptyMessage="No live sessions match."
        ariaLabel="Live floor sessions"
        tableClassName="min-w-[56rem]"
      />
    </div>
  );
}
