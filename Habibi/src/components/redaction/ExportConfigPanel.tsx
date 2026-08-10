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
const ROLES = ["Compliance officer", "DPO", "Head of collections", "External auditor (read-only)"];

export function ExportConfigPanel(p: Props) {
  const canExport = p.selectedCount > 0 && p.scope.length > 0 && p.watermark.trim().length > 0;
  const toggleScope = (s: ExportScope) => {
    p.onScope(p.scope.includes(s) ? p.scope.filter((x) => x !== s) : [...p.scope, s]);
  };
  return (
    <div className="space-y-150 rounded-large border border-border bg-surface p-150">
      <div className="flex items-center gap-100 text-body font-semibold text-text">
        <ShieldCheck className="h-4 w-4 text-text-brand" />
        Export configuration
      </div>

      <div>
        <div className="mb-050 text-body-small font-semibold text-text-subtlest">Format</div>
        <div className="grid grid-cols-3 gap-075">
          {FORMATS.map((f) => {
            const Icon = f.icon;
            const active = p.format === f.id;
            return (
              <button
                key={f.id}
                onClick={() => p.onFormat(f.id)}
                className={cn(
                  "flex flex-col items-center gap-050 rounded-medium border px-100 py-100 text-body-small transition-colors",
                  active
                    ? "border-border-brand bg-background-brand-subtlest text-text-brand"
                    : "border-border text-text-subtle hover:bg-surface-sunken",
                )}
              >
                <Icon className="h-4 w-4" />
                <span className="font-semibold">{f.label}</span>
                <span className="text-body-small text-text-subtlest">{f.hint}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div>
        <div className="mb-050 text-body-small font-semibold text-text-subtlest">Scope</div>
        <div className="flex flex-wrap gap-075">
          {SCOPES.map((s) => (
            <label
              key={s}
              className={cn(
                "inline-flex cursor-pointer items-center gap-050 rounded-full border px-100 py-025 text-body-small capitalize",
                p.scope.includes(s)
                  ? "border-border-brand bg-background-brand-subtlest text-text-brand"
                  : "border-border text-text-subtle",
              )}
            >
              <input
                type="checkbox"
                className="h-3 w-3 accent-[var(--background-brand-bold)]"
                checked={p.scope.includes(s)}
                onChange={() => toggleScope(s)}
              />
              {s}
            </label>
          ))}
        </div>
      </div>

      <div>
        <div className="mb-050 text-body-small font-semibold text-text-subtlest">Watermark</div>
        <input
          value={p.watermark}
          onChange={(e) => p.onWatermark(e.target.value)}
          placeholder="e.g. RBI Audit Q2 · Ticket #123"
          className="w-full rounded-medium border border-border bg-surface-sunken px-100 py-075 text-body-small focus:border-border-brand focus:outline-none"
        />
      </div>

      <div>
        <div className="mb-050 text-body-small font-semibold text-text-subtlest">Access</div>
        <select
          value={p.accessRole}
          onChange={(e) => p.onAccessRole(e.target.value)}
          className="w-full rounded-medium border border-border bg-surface-sunken px-100 py-075 text-body-small focus:border-border-brand focus:outline-none"
        >
          {ROLES.map((r) => <option key={r}>{r}</option>)}
        </select>
      </div>

      <div className="flex items-center justify-between rounded-medium bg-surface-sunken px-100 py-075 text-body-small">
        <span className="text-text-subtle">
          {p.selectedCount} record{p.selectedCount === 1 ? "" : "s"} selected
        </span>
        {p.pendingReview > 0 && (
          <span className="text-text-warning">{p.pendingReview} unreviewed</span>
        )}
      </div>

      <button
        onClick={p.onGenerate}
        disabled={!canExport}
        className={cn(
          "flex w-full items-center justify-center gap-100 rounded-medium py-100 text-body font-semibold text-white transition-colors",
          canExport ? "bg-background-brand-bold hover:bg-background-brand-bold-hovered" : "cursor-not-allowed bg-text-muted",
        )}
      >
        <Play className="h-4 w-4" />
        Generate export
      </button>
    </div>
  );
}
