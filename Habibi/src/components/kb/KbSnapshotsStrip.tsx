import { useState } from "react";
import type { KbSnapshot } from "@/api/kb";
import { Camera, ChevronDown } from "lucide-react";
import { cn, formatKbDateTime } from "@/lib/utils";

function plural(n: number, one: string, many: string) {
  return `${n} ${n === 1 ? one : many}`;
}

export function KbSnapshotsStrip({ snapshots }: { snapshots: KbSnapshot[] }) {
  const [open, setOpen] = useState(false);
  if (!snapshots.length) return null;

  const latest = snapshots[0];
  const extra = snapshots.length - 1;

  return (
    <div className="shrink-0 border-b border-border bg-surface">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-100 px-200 py-075 text-left hover:bg-surface-sunken"
        aria-expanded={open}
      >
        <Camera className="h-3.5 w-3.5 shrink-0 text-text-brand" />
        <span className="truncate text-body-small text-text">
          <span className="font-medium">{latest.label}</span>
          <span className="text-text-subtlest">
            {" "}
            · {plural(latest.documentCount, "doc", "docs")} ·{" "}
            {plural(latest.faqCount, "FAQ", "FAQs")} · {formatKbDateTime(latest.createdAt)}
          </span>
        </span>
        {extra > 0 && (
          <span className="shrink-0 text-body-small text-text-subtlest">{extra} older</span>
        )}
        <ChevronDown
          className={cn(
            "ml-auto h-3.5 w-3.5 shrink-0 text-text-subtlest transition-transform",
            open && "rotate-180",
          )}
        />
      </button>
      {open && (
        <ul className="border-t border-border">
          {snapshots.slice(0, 6).map((s) => (
            <li
              key={s.id}
              className="flex flex-wrap items-center justify-between gap-100 px-200 py-075 text-body-small"
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
      )}
    </div>
  );
}
