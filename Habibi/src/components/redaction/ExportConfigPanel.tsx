import { FileText, FileSpreadsheet, FileArchive, ShieldCheck, Play } from "lucide-react";
import type { ExportFormat, ExportScope } from "@/data/redaction-seed";
import { cn } from "@/lib/utils";

interface Props {
  selectedCount: number;
  pendingReview: number;
  format: ExportFormat;
  scope: ExportScope[];
  watermark: string;
  accessRole: string;
  onFormat: (f: ExportFormat) => void;
  onScope: (s: ExportScope[]) => void;
  onWatermark: (w: string) => void;
  onAccessRole: (r: string) => void;
  onGenerate: () => void;
}

const FORMATS: Array<{ id: ExportFormat; label: string; icon: typeof FileText; hint: string }> = [
  { id: "pdf",       label: "PDF",       icon: FileText,       hint: "Watermarked transcript" },
  { id: "csv",       label: "CSV",       icon: FileSpreadsheet, hint: "Metadata rows only" },
  { id: "audio-zip", label: "Audio ZIP", icon: FileArchive,    hint: "WAV + beeped segments" },
];
const SCOPES: ExportScope[] = ["transcript", "audio", "metadata"];
const ROLES = ["Compliance Officer", "DPO", "Head of Collections", "External Auditor (read-only)"];

export function ExportConfigPanel(p: Props) {
  const canExport = p.selectedCount > 0 && p.scope.length > 0 && p.watermark.trim().length > 0;
  const toggleScope = (s: ExportScope) => {
    p.onScope(p.scope.includes(s) ? p.scope.filter((x) => x !== s) : [...p.scope, s]);
  };
  return (
    <div className="space-y-3 rounded-lg border border-[var(--border-token)] bg-surface-card p-3">
      <div className="flex items-center gap-2 text-[13px] font-semibold text-brand-navy">
        <ShieldCheck className="h-4 w-4 text-brand-primary" />
        Export configuration
      </div>

      <div>
        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-text-muted">Format</div>
        <div className="grid grid-cols-3 gap-1.5">
          {FORMATS.map((f) => {
            const Icon = f.icon;
            const active = p.format === f.id;
            return (
              <button
                key={f.id}
                onClick={() => p.onFormat(f.id)}
                className={cn(
                  "flex flex-col items-center gap-1 rounded-md border px-2 py-2 text-[11px] transition-colors",
                  active
                    ? "border-brand-primary bg-brand-tint text-brand-primary-dark"
                    : "border-[var(--border-token)] text-text-secondary hover:bg-surface-sunken",
                )}
              >
                <Icon className="h-4 w-4" />
                <span className="font-semibold">{f.label}</span>
                <span className="text-[10px] text-text-muted">{f.hint}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div>
        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-text-muted">Scope</div>
        <div className="flex flex-wrap gap-1.5">
          {SCOPES.map((s) => (
            <label
              key={s}
              className={cn(
                "inline-flex cursor-pointer items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] capitalize",
                p.scope.includes(s)
                  ? "border-brand-primary bg-brand-tint text-brand-primary-dark"
                  : "border-[var(--border-token)] text-text-secondary",
              )}
            >
              <input
                type="checkbox"
                className="h-3 w-3 accent-[var(--brand-primary)]"
                checked={p.scope.includes(s)}
                onChange={() => toggleScope(s)}
              />
              {s}
            </label>
          ))}
        </div>
      </div>

      <div>
        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-text-muted">Watermark</div>
        <input
          value={p.watermark}
          onChange={(e) => p.onWatermark(e.target.value)}
          placeholder="e.g. RBI Audit Q2 · Ticket #123"
          className="w-full rounded-md border border-[var(--border-token)] bg-surface-sunken px-2 py-1.5 text-[12px] focus:border-brand-primary focus:outline-none"
        />
      </div>

      <div>
        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-text-muted">Access</div>
        <select
          value={p.accessRole}
          onChange={(e) => p.onAccessRole(e.target.value)}
          className="w-full rounded-md border border-[var(--border-token)] bg-surface-sunken px-2 py-1.5 text-[12px] focus:border-brand-primary focus:outline-none"
        >
          {ROLES.map((r) => <option key={r}>{r}</option>)}
        </select>
      </div>

      <div className="flex items-center justify-between rounded-md bg-surface-sunken px-2 py-1.5 text-[11px]">
        <span className="text-text-secondary">
          {p.selectedCount} record{p.selectedCount === 1 ? "" : "s"} selected
        </span>
        {p.pendingReview > 0 && (
          <span className="text-[var(--warning)]">{p.pendingReview} unreviewed</span>
        )}
      </div>

      <button
        onClick={p.onGenerate}
        disabled={!canExport}
        className={cn(
          "flex w-full items-center justify-center gap-2 rounded-md py-2 text-[13px] font-semibold text-white transition-colors",
          canExport ? "bg-brand-primary hover:bg-brand-primary-hover" : "cursor-not-allowed bg-text-muted",
        )}
      >
        <Play className="h-4 w-4" />
        Generate export
      </button>
    </div>
  );
}
