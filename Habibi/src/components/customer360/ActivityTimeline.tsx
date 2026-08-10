import type { ActivityPreviewItem } from "@/lib/customerInsights";
import { fmtRelative } from "@/data/customer360-seed";
import { StatusChip, type ChipTone } from "./StatusChip";

function kindTone(kind: string): ChipTone {
  switch (kind) {
    case "promise":
      return "brand";
    case "dispute":
      return "warning";
    case "interaction":
      return "neutral";
    case "note":
      return "neutral";
    case "document":
      return "success";
    default:
      return "neutral";
  }
}

export function ActivityTimeline({ items }: { items: ActivityPreviewItem[] }) {
  const list = items ?? [];
  return (
    <div className="rounded-large border border-border bg-surface">
      <div className="border-b border-border px-200 py-150">
        <div className="text-body-small font-semibold text-text">Recent activity</div>
        <div className="text-body-small text-text-subtlest">Cross-channel timeline</div>
      </div>
      {list.length === 0 ? (
        <div className="px-200 py-400 text-center text-body-small text-text-subtlest">No activity yet.</div>
      ) : (
        <ul className="divide-y divide-border">
          {list.map((item) => (
            <li key={item.id} className="flex gap-150 px-200 py-150">
              <div className="mt-075 h-100 w-100 shrink-0 rounded-full bg-background-brand-bold" />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-075">
                  <StatusChip label={item.kind} tone={kindTone(item.kind)} />
                  <span className="text-body-small font-medium text-text">{item.label}</span>
                  <span className="ml-auto text-body-small text-text-subtlest tabular">{fmtRelative(item.at)}</span>
                </div>
                {item.note ? (
                  <p className="mt-050 line-clamp-2 text-body-small text-text-subtle">{item.note}</p>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
