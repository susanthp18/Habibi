import type { KbSnapshot } from "@/api/kb";
import { formatKbDateTime } from "@/lib/utils";
import { Camera } from "lucide-react";

function plural(n: number, one: string, many: string) {
  return `${n} ${n === 1 ? one : many}`;
}

export function KbSnapshotsStrip({ snapshots }: { snapshots: KbSnapshot[] }) {
  if (!snapshots.length) return null;

  return (
    <div className="mt-3 overflow-hidden rounded-lg border border-[var(--border-token)] bg-surface-card">
      <div className="flex flex-wrap items-center gap-2 border-b border-[var(--border-token)] px-3 py-2">
        <Camera className="h-3.5 w-3.5 text-brand-primary" />
        <div className="text-[13px] font-medium text-brand-navy">Recent KB snapshots</div>
        <div className="text-[11px] text-text-muted">
          Frozen doc/FAQ sets for sandbox readiness (created on re-index all)
        </div>
      </div>
      <ul className="divide-y divide-[var(--border-token)]">
        {snapshots.slice(0, 6).map((s) => (
          <li
            key={s.id}
            className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-[12px]"
          >
            <div className="min-w-0">
              <div className="truncate font-medium text-brand-navy">{s.label}</div>
              <div className="font-mono text-[10px] text-text-muted">{s.id}</div>
            </div>
            <div className="flex items-center gap-3 text-text-secondary">
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
