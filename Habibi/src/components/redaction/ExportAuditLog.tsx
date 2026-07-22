import { FileText, FileSpreadsheet, FileArchive, Download, RotateCcw, AlertCircle, CheckCircle2, Clock } from "lucide-react";
import type { ExportJob } from "@/data/redaction-seed";
import { formatDateTime } from "@/data/redaction-seed";
import { cn } from "@/lib/utils";

const FMT_ICON = { pdf: FileText, csv: FileSpreadsheet, "audio-zip": FileArchive } as const;

interface Props {
  jobs: ExportJob[];
  onDownload: (id: string) => void;
  onRetry: (id: string) => void;
}

export function ExportAuditLog({ jobs, onDownload, onRetry }: Props) {
  return (
    <div className="rounded-lg border border-[var(--border-token)] bg-surface-card">
      <div className="flex items-center justify-between border-b border-[var(--border-token)] px-3 py-2">
        <div className="text-[12px] font-semibold text-brand-navy">Export audit log</div>
        <div className="text-[10px] text-text-muted">Immutable · last {jobs.length}</div>
      </div>
      <ul className="max-h-[280px] overflow-y-auto">
        {jobs.map((j) => {
          const Icon = FMT_ICON[j.format];
          return (
            <li key={j.id} className="border-b border-[var(--border-token)] px-3 py-2 last:border-b-0">
              <div className="flex items-start gap-2">
                <div className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-surface-sunken text-brand-primary-dark">
                  <Icon className="h-3.5 w-3.5" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[12px] font-semibold text-brand-navy">{j.id}</span>
                    <StatusPill status={j.status} />
                    <span className="ml-auto text-[10px] text-text-muted">{formatDateTime(j.at)}</span>
                  </div>
                  <div className="mt-0.5 truncate text-[11px] text-text-secondary">
                    {j.actor} · {j.actorRole}
                  </div>
                  <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] text-text-muted">
                    <span>{j.recordIds.length} record{j.recordIds.length === 1 ? "" : "s"}</span>
                    <span>·</span>
                    <span>{j.entitiesRedacted} redacted</span>
                    <span>·</span>
                    <span>DL × {j.downloadCount}</span>
                  </div>
                  <div className="mt-0.5 truncate text-[10px] italic text-text-muted">"{j.watermark}"</div>
                </div>
              </div>
              <div className="mt-1.5 flex justify-end gap-1">
                {j.status === "ready" && (
                  <button
                    onClick={() => onDownload(j.id)}
                    className="inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] px-2 py-0.5 text-[11px] text-text-primary hover:bg-surface-sunken"
                  >
                    <Download className="h-3 w-3" /> Download
                  </button>
                )}
                {j.status === "failed" && (
                  <button
                    onClick={() => onRetry(j.id)}
                    className="inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] px-2 py-0.5 text-[11px] text-brand-primary hover:bg-brand-tint"
                  >
                    <RotateCcw className="h-3 w-3" /> Retry
                  </button>
                )}
              </div>
            </li>
          );
        })}
        {jobs.length === 0 && (
          <li className="px-3 py-6 text-center text-[12px] text-text-muted">No exports yet</li>
        )}
      </ul>
    </div>
  );
}

function StatusPill({ status }: { status: ExportJob["status"] }) {
  const map = {
    ready:  { icon: CheckCircle2, bg: "var(--success-bg)",  fg: "var(--success)",  label: "Ready" },
    queued: { icon: Clock,        bg: "var(--warning-bg)",  fg: "var(--warning)",  label: "Queued" },
    failed: { icon: AlertCircle,  bg: "var(--danger-bg)",   fg: "var(--danger)",   label: "Failed" },
  } as const;
  const s = map[status];
  const Icon = s.icon;
  return (
    <span
      className={cn("inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-semibold")}
      style={{ backgroundColor: s.bg, color: s.fg }}
    >
      <Icon className="h-2.5 w-2.5" />
      {s.label}
    </span>
  );
}
