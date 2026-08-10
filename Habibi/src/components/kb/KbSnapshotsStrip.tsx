import type { KbSnapshot } from "@/api/kb";
import { formatKbDateTime } from "@/lib/utils";
import { Camera } from "lucide-react";

function plural(n: number, one: string, many: string) {
  return `${n} ${n === 1 ? one : many}`;
}

export function KbSnapshotsStrip({ snapshots }: { snapshots: KbSnapshot[] }) {
  if (!snapshots.length) return null;

  return (
    <div className="mt-150 overflow-hidden rounded-large border border-border bg-surface">
      <div className="flex flex-wrap items-center gap-100 border-b border-border px-150 py-100">
        <Camera className="h-3.5 w-3.5 text-text-brand" />
        <div className="text-body font-medium text-text">Recent KB snapshots</div>
        <div className="text-body-small text-text-subtlest">
          Frozen doc/FAQ sets for sandbox readiness (created on re-index all)
        </div>
      </div>
      <ul className="divide-y divide-border">
        {snapshots.slice(0, 6).map((s) => (
          <li
            key={s.id}
            className="flex flex-wrap items-center justify-between gap-100 px-150 py-100 text-body-small"
          >
            <div className="min-w-0">
              <div className="truncate font-medium text-text">{s.label}</div>
              <div className="font-mono text-body-small text-text-subtlest">{s.id}</div>
            </div>
            <div className="flex items-center gap-150 text-text-subtle">
              <span>
                {plural(s.documentCount, "doc", "docs")} · {plural(s.faqCount, "FAQ", "FAQs")}
              </span>
              <span className="tabular-nums">{formatKbDateTime(s.createdAt)}</span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
