import { ArrowRight, CalendarClock, FileText, HandCoins, PhoneCall, Scale } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { NbaActionKind, NbaItem } from "@/lib/customerInsights";
import { StatusChip, type ChipTone } from "./StatusChip";
import { cn } from "@/lib/utils";

const PRIORITY_TONE: Record<NbaItem["priority"], ChipTone> = {
  high: "danger",
  medium: "warning",
  low: "neutral",
};

const ACTION_ICON: Record<NbaActionKind, typeof PhoneCall> = {
  ptp: HandCoins,
  dispute: Scale,
  statement: FileText,
  call: PhoneCall,
  callback: CalendarClock,
  review: Scale,
};

type Handlers = {
  onAction: (action: NbaActionKind) => void;
};

export function NextBestActionCard({ items, onAction }: { items: NbaItem[] } & Handlers) {
  const list = items ?? [];
  const primary = list[0];
  const rest = list.slice(1);

  return (
    <div className="rounded-large border border-border bg-surface">
      <div className="border-b border-border px-200 py-150">
        <div className="text-body-small font-semibold text-text">Next best action</div>
        <div className="text-body-small text-text-subtlest">Ranked for this account right now</div>
      </div>

      {primary ? (
        <div className="border-b border-border bg-background-brand-subtlest/40 px-200 py-150">
          <div className="flex items-start justify-between gap-100">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-075">
                <StatusChip label={`#${primary.rank}`} tone="brand" />
                <StatusChip label={primary.priority} tone={PRIORITY_TONE[primary.priority]} />
              </div>
              <div className="mt-075 text-body font-semibold text-text">{primary.title}</div>
              <p className="mt-050 text-body-small leading-snug text-text-subtle">{primary.reason}</p>
            </div>
          </div>
          <Button
            size="sm"
            className="mt-150 h-400 bg-background-brand-bold hover:bg-background-brand-bold-hovered"
            onClick={() => onAction(primary.action)}
          >
            Take action
            <ArrowRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      ) : null}

      {rest.length > 0 ? (
        <ul className="divide-y divide-border">
          {rest.map((item) => {
            const Icon = ACTION_ICON[item.action];
            return (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => onAction(item.action)}
                  className={cn(
                    "flex w-full items-start gap-150 px-200 py-150 text-left transition-colors hover:bg-surface-sunken",
                  )}
                >
                  <Icon className="mt-025 h-4 w-4 shrink-0 text-text-brand" />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-075">
                      <span className="text-body-small font-semibold text-text">{item.title}</span>
                      <StatusChip label={item.priority} tone={PRIORITY_TONE[item.priority]} />
                    </div>
                    <p className="mt-025 text-body-small text-text-subtle">{item.reason}</p>
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
