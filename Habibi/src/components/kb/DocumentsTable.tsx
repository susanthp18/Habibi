import { cn } from "@/lib/utils";
import { Switch } from "@/components/ui/switch";
import { DOC_TYPE_LABEL, STATUS_LABEL, type KbDocument } from "@/data/kb-seed";
import { FileText, RefreshCw } from "lucide-react";

const statusStyles: Record<string, string> = {
  indexed: "bg-emerald-50 text-emerald-700 border-emerald-200",
  indexing: "bg-brand-tint text-brand-primary-dark border-brand-primary/30",
  stale: "bg-amber-50 text-amber-700 border-amber-200",
  failed: "bg-red-50 text-red-700 border-red-200",
  draft: "bg-surface-sunken text-text-secondary border-[var(--border-token)]",
};

export function DocumentsTable({
  docs,
  selectedId,
  onSelect,
  onToggle,
  onReindex,
  reindexing,
}: {
  docs: KbDocument[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onToggle: (id: string, enabled: boolean) => void;
  onReindex: (id: string) => void;
  reindexing: Set<string>;
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-[var(--border-token)] bg-surface-card">
      <table className="w-full text-[13px]">
        <thead className="bg-surface-sunken text-[11px] font-medium uppercase tracking-wide text-text-muted">
          <tr>
            <th className="px-3 py-2 text-left">Document</th>
            <th className="px-3 py-2 text-left">Type</th>
            <th className="px-2 py-2 text-left">Ver</th>
            <th className="px-2 py-2 text-right">Chunks</th>
            <th className="px-3 py-2 text-left">Status</th>
            <th className="px-3 py-2 text-left">Last indexed</th>
            <th className="px-3 py-2 text-center">Enabled</th>
            <th className="px-2 py-2" />
          </tr>
        </thead>
        <tbody>
          {docs.map((d) => {
            const active = d.id === selectedId;
            const busy = reindexing.has(d.id);
            return (
              <tr
                key={d.id}
                onClick={() => onSelect(d.id)}
                className={cn(
                  "cursor-pointer border-t border-[var(--border-token)] hover:bg-surface-sunken/60",
                  active && "bg-brand-tint/50",
                )}
              >
                <td className="px-3 py-2.5">
                  <div className="flex items-center gap-2">
                    <FileText className="h-4 w-4 text-text-muted" />
                    <div className="min-w-0">
                      <div className="truncate font-medium text-brand-navy">{d.title}</div>
                      <div className="truncate text-[11px] text-text-muted">{d.filename}</div>
                    </div>
                  </div>
                </td>
                <td className="px-3 py-2.5 text-text-secondary">{DOC_TYPE_LABEL[d.type]}</td>
                <td className="px-2 py-2.5 font-mono text-[12px] text-text-secondary">{d.version}</td>
                <td className="px-2 py-2.5 text-right tabular-nums text-text-secondary">{d.chunks}</td>
                <td className="px-3 py-2.5">
                  <span
                    className={cn(
                      "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium",
                      statusStyles[busy ? "indexing" : d.status],
                    )}
                  >
                    {busy && <RefreshCw className="mr-1 h-3 w-3 animate-spin" />}
                    {STATUS_LABEL[busy ? "indexing" : d.status]}
                  </span>
                </td>
                <td className="px-3 py-2.5 text-[12px] text-text-secondary">
                  {new Date(d.lastIndexed).toLocaleDateString(undefined, {
                    day: "2-digit",
                    month: "short",
                    year: "2-digit",
                  })}
                </td>
                <td className="px-3 py-2.5 text-center" onClick={(e) => e.stopPropagation()}>
                  <Switch checked={d.enabled} onCheckedChange={(v) => onToggle(d.id, v)} />
                </td>
                <td className="px-2 py-2.5 text-right" onClick={(e) => e.stopPropagation()}>
                  <button
                    onClick={() => onReindex(d.id)}
                    disabled={busy}
                    className="rounded-md p-1.5 text-text-muted hover:bg-surface-sunken hover:text-brand-primary disabled:opacity-40"
                    aria-label="Re-index"
                  >
                    <RefreshCw className={cn("h-3.5 w-3.5", busy && "animate-spin")} />
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
