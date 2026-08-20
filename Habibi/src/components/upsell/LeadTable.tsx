import { useMemo } from "react";
import { CalendarClock, ShieldAlert, ShieldCheck, Tag, User, Wallet } from "lucide-react";
import {
  fmtDateTime,
  fmtMoney,
  fmtRelative,
  leadValue,
  SOURCE_LABELS,
  STAGE_LABELS,
  type Lead,
  type LeadStage,
  type Sentiment,
} from "@/data/upsell-seed";
import { Lozenge, type LozengeTone } from "@/components/ui/lozenge";
import { cn } from "@/lib/utils";
import {
  RecordsAvatarMark,
  RecordsTable,
  type RecordsColumn,
} from "@/components/records/RecordsTable";
import { RecordsTag } from "@/components/records/RecordsTag";

interface Props {
  leads: Lead[];
  onOpen: (l: Lead) => void;
}

const stageTone: Record<LeadStage, LozengeTone> = {
  interested: "selected",
  contacted: "discovery",
  qualified: "warning",
  won: "success",
  lost: "neutral",
};

const stageRank: Record<LeadStage, number> = {
  interested: 1,
  contacted: 2,
  qualified: 3,
  won: 5,
  lost: 0,
};

const sentimentDot: Record<Sentiment, string> = {
  positive: "bg-background-success-bold",
  neutral: "bg-background-accent-gray-subtle",
  negative: "bg-background-danger-bold",
};

export function LeadTable({ leads, onOpen }: Props) {
  const columns = useMemo<RecordsColumn<Lead>[]>(
    () => [
      {
        id: "customer",
        header: "Customer",
        headerIcon: <User className="h-3.5 w-3.5" />,
        sticky: true,
        sortable: true,
        sortValue: (l) => l.customerName,
        className: "min-w-[13rem]",
        cell: (l) => (
          <button type="button" onClick={() => onOpen(l)} className="flex min-w-0 items-center gap-100 text-left">
            <RecordsAvatarMark label={l.customerName || "?"} />
            <span className="min-w-0">
              <span className="block truncate text-sm font-medium text-text-brand hover:underline">
                {l.customerName}
              </span>
              <span className="block truncate text-body-small text-text-subtlest">
                #{l.accountTail} · {l.id}
              </span>
            </span>
          </button>
        ),
        footer: (visible) => (
          <span>
            <span className="font-semibold tabular text-text">{visible.length}</span>{" "}
            <span className="text-text-subtlest">leads</span>
          </span>
        ),
      },
      {
        id: "offer",
        header: "Offer",
        headerIcon: <Tag className="h-3.5 w-3.5" />,
        sortable: true,
        sortValue: (l) => l.offer?.label ?? "",
        cell: (l) => (
          <div className="min-w-0">
            <div className="truncate text-text">{l.offer?.label ?? "—"}</div>
            <div className="truncate text-body-small text-text-subtlest">
              {SOURCE_LABELS[l.source] ?? l.source} · {l.offer?.indicativeROI ?? "—"}
            </div>
          </div>
        ),
      },
      {
        id: "stage",
        header: "Stage",
        sortable: true,
        sortValue: (l) => stageRank[l.stage] ?? 0,
        cell: (l) => (
          <Lozenge tone={stageTone[l.stage] ?? "neutral"}>{STAGE_LABELS[l.stage] ?? l.stage}</Lozenge>
        ),
        footer: (visible) => {
          const won = visible.filter((l) => l.stage === "won").length;
          return <span className="text-text-subtlest">{won} won</span>;
        },
      },
      {
        id: "value",
        header: "Value",
        headerIcon: <Wallet className="h-3.5 w-3.5" />,
        sortable: true,
        sortValue: (l) => leadValue(l),
        align: "right",
        cell: (l) => {
          const failing = (l.eligibilityFlags ?? []).filter((f) => !f.ok).length;
          return (
            <div className="tabular-nums">
              <div className="font-semibold text-text">{fmtMoney(leadValue(l))}</div>
              {failing > 0 ? (
                <div className="inline-flex items-center gap-050 text-body-small text-text-warning-bolder">
                  <ShieldAlert className="h-3 w-3" /> {failing} flag{failing > 1 ? "s" : ""}
                </div>
              ) : (
                <div className="inline-flex items-center gap-050 text-body-small text-text-success-bolder">
                  <ShieldCheck className="h-3 w-3" /> Eligible
                </div>
              )}
            </div>
          );
        },
        footer: (visible) => {
          const total = visible.reduce((s, l) => s + leadValue(l), 0);
          return <span className="font-semibold tabular text-text">{fmtMoney(total)}</span>;
        },
      },
      {
        id: "owner",
        header: "Owner · Team",
        sortable: true,
        sortValue: (l) => l.owner || "",
        cell: (l) => (
          <div className="min-w-0">
            <div
              className={cn(
                "truncate",
                !l.owner || l.owner === "Unassigned" ? "italic text-text-subtlest" : "text-text",
              )}
            >
              {l.owner || "Unassigned"}
            </div>
            <div className="truncate text-body-small text-text-subtlest">{l.team || "Unrouted"}</div>
          </div>
        ),
      },
      {
        id: "followup",
        header: "Next follow-up",
        headerIcon: <CalendarClock className="h-3.5 w-3.5" />,
        sortable: true,
        sortValue: (l) => (l.nextFollowUpAt ? new Date(l.nextFollowUpAt).getTime() : Number.MAX_SAFE_INTEGER),
        cell: (l) =>
          l.nextFollowUpAt ? (
            <span className="inline-flex items-center gap-050 text-text-subtle">
              <CalendarClock className="h-3 w-3 text-text-subtlest" />
              {fmtDateTime(l.nextFollowUpAt)}
              <span className="text-text-subtlest">({fmtRelative(l.nextFollowUpAt)})</span>
            </span>
          ) : (
            <span className="text-text-subtlest">—</span>
          ),
      },
      {
        id: "sentiment",
        header: "Sentiment",
        sortable: true,
        sortValue: (l) => l.sentimentScore ?? 0,
        align: "right",
        cell: (l) => (
          <div className="flex items-center justify-end gap-075">
            <span
              className={cn("h-1.5 w-1.5 rounded-full", sentimentDot[l.sentimentAtCapture] ?? sentimentDot.neutral)}
              aria-hidden
            />
            <span className="capitalize text-text-subtle">{l.sentimentAtCapture || "—"}</span>
          </div>
        ),
      },
    ],
    [onOpen],
  );

  return (
    <RecordsTable
      rows={leads}
      getRowId={(l) => l.id}
      columns={columns}
      emptyMessage="No leads match the filters."
      ariaLabel="Upsell leads table"
      defaultSort={{ id: "value", dir: -1 }}
      className="h-full min-h-0 flex-1"
    />
  );
}
