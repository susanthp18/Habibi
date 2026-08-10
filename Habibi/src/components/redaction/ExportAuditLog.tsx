import { FileText, FileSpreadsheet, FileArchive, Download, RotateCcw, AlertCircle, CheckCircle2, Clock } from "lucide-react";
import type { ExportJob } from "@/data/redaction-seed";
import { formatDateTime } from "@/data/redaction-seed";
import { Lozenge } from "@/components/ui/lozenge";

const FMT_ICON = { pdf: FileText, csv: FileSpreadsheet, "audio-zip": FileArchive } as const;

interface Props {
  jobs: ExportJob[];
  onDownload: (id: string) => void;
  onRetry: (id: string) => void;
}

export function ExportAuditLog({ jobs, onDownload, onRetry }: Props) {
  return (
    <div className="rounded-large border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-150 py-100">
        <div className="text-body-small font-semibold text-text">Export audit log</div>
        <div className="text-body-small text-text-subtlest">Immutable · last {jobs.length}</div>
      </div>
      <ul className="max-h-[17.5rem] overflow-y-auto">
        {jobs.map((j) => {
          const Icon = FMT_ICON[j.format];
          return (
            <li key={j.id} className="border-b border-border px-150 py-100 last:border-b-0">
              <div className="flex items-start gap-100">
                <div className="grid h-7 w-7 shrink-0 place-items-center rounded-medium bg-surface-sunken text-text-brand">
                  <Icon className="h-3.5 w-3.5" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-100">
                    <span className="text-body-small font-semibold text-text">{j.id}</span>
                    <StatusPill status={j.status} />
                    <span className="ml-auto text-body-small text-text-subtlest">{formatDateTime(j.at)}</span>
                  </div>
                  <div className="mt-025 truncate text-body-small text-text-subtle">
                    {j.actor} · {j.actorRole}
                  </div>
                  <div className="mt-025 flex flex-wrap items-center gap-x-100 gap-y-025 text-body-small text-text-subtlest">
                    <span>{j.recordIds.length} record{j.recordIds.length === 1 ? "" : "s"}</span>
                    <span>·</span>
                    <span>{j.entitiesRedacted} redacted</span>
                    <span>·</span>
                    <span>DL × {j.downloadCount}</span>
                  </div>
                  <div className="mt-025 truncate text-body-small italic text-text-subtlest">"{j.watermark}"</div>
                </div>
              </div>
              <div className="mt-075 flex justify-end gap-050">
                {j.status === "ready" && (
                  <button
                    onClick={() => onDownload(j.id)}
                    className="inline-flex items-center gap-050 rounded-medium border border-border px-100 py-025 text-body-small text-text hover:bg-surface-sunken"
                  >
                    <Download className="h-3 w-3" /> Download
                  </button>
                )}
                {j.status === "failed" && (
                  <button
                    onClick={() => onRetry(j.id)}
                    className="inline-flex items-center gap-050 rounded-medium border border-border px-100 py-025 text-body-small text-text-brand hover:bg-background-brand-subtlest"
                  >
                    <RotateCcw className="h-3 w-3" /> Retry
                  </button>
                )}
              </div>
            </li>
          );
        })}
        {jobs.length === 0 && (
          <li className="px-150 py-300 text-center text-body-small text-text-subtlest">No exports yet</li>
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
    <Lozenge style={{ backgroundColor: s.bg, color: s.fg, borderColor: s.fg }}>
      <Icon />
      {s.label}
    </Lozenge>
  );
}
