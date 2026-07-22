import { GitCommit, RotateCcw } from "lucide-react";
import type { PromptVersion } from "@/data/prompt-studio-seed";

type Props = {
  versions: PromptVersion[];
  onCompare: (v: PromptVersion) => void;
  onRestore: (v: PromptVersion) => void;
};

function relTime(iso: string): string {
  const d = (Date.now() - new Date(iso).getTime()) / 86400_000;
  if (d < 1) return `${Math.round(d * 24)}h ago`;
  return `${Math.round(d)}d ago`;
}

export function VersionHistory({ versions, onCompare, onRestore }: Props) {
  return (
    <div className="flex h-full min-h-0 flex-col border-l border-[var(--border-token)] bg-surface-card">
      <div className="shrink-0 border-b border-[var(--border-token)] px-4 py-3">
        <h3 className="text-[13px] font-semibold text-brand-navy">Version history</h3>
        <p className="text-[11px] text-text-muted">Every publish is captured. Compare or restore any prior version.</p>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        <ol className="relative ml-3 border-l border-[var(--border-token)]">
          {versions.map((v) => (
            <li key={v.id} className="mb-4 pl-4">
              <span className="absolute -left-[7px] mt-1.5 grid h-3.5 w-3.5 place-items-center rounded-full bg-brand-primary text-white">
                <GitCommit className="h-2.5 w-2.5" />
              </span>
              <div className="flex items-center gap-2">
                <span className="font-mono text-[12px] font-semibold text-text-primary">{v.label}</span>
                {v.status === "published" && (
                  <span className="rounded-full bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700">
                    live
                  </span>
                )}
                <span className="ml-auto text-[10.5px] text-text-muted">{relTime(v.createdAt)}</span>
              </div>
              <div className="text-[11.5px] text-text-secondary">{v.summary}</div>
              <div className="text-[10.5px] text-text-muted">by {v.author}</div>
              <div className="mt-1.5 flex gap-1.5">
                <button
                  onClick={() => onCompare(v)}
                  className="rounded-md border border-[var(--border-token)] px-2 py-0.5 text-[11px] hover:bg-surface-sunken"
                >
                  Compare
                </button>
                <button
                  onClick={() => onRestore(v)}
                  className="inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] px-2 py-0.5 text-[11px] hover:bg-surface-sunken"
                >
                  <RotateCcw className="h-3 w-3" /> Restore
                </button>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
