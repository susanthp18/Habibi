import { GitCommit, RotateCcw, Undo2 } from "lucide-react";
import type { PromptVersion } from "@/data/prompt-studio-seed";
import type { BotDeployment } from "@/api/prompt-studio";

type Props = {
  versions: PromptVersion[];
  activeDraftId?: string | null;
  activeDeployment?: BotDeployment | null;
  priorDeployment?: BotDeployment | null;
  onCompare: (v: PromptVersion) => void;
  onRestore: (v: PromptVersion) => void;
  onLoadDraft: (v: PromptVersion) => void;
  onDiscardDraft: (v: PromptVersion) => void;
  onRollback?: () => void;
  rollbackBusy?: boolean;
};

function relTime(iso: string): string {
  const d = (Date.now() - new Date(iso).getTime()) / 86400_000;
  if (d < 1) return `${Math.round(d * 24)}h ago`;
  return `${Math.round(d)}d ago`;
}

export function VersionHistory({
  versions,
  activeDraftId,
  activeDeployment,
  priorDeployment,
  onCompare,
  onRestore,
  onLoadDraft,
  onDiscardDraft,
  onRollback,
  rollbackBusy,
}: Props) {
  const drafts = versions.filter((v) => v.status === "draft");
  const published = versions.find((v) => v.status === "published");

  return (
    <div className="flex h-full min-h-0 flex-col border-l border-[var(--border-token)] bg-surface-card">
      <div className="shrink-0 space-y-3 border-b border-[var(--border-token)] px-4 py-3">
        <div>
          <h3 className="text-[13px] font-semibold text-brand-navy">Version history</h3>
          <p className="text-[11px] text-text-muted">Compare, load drafts, restore, or roll back live.</p>
        </div>

        {activeDeployment && (
          <div className="rounded-md border border-[var(--border-token)] bg-surface-sunken p-2.5 text-[11px]">
            <div className="font-semibold text-brand-navy">Active production</div>
            <div className="mt-0.5 font-mono text-text-secondary">{activeDeployment.id}</div>
            <div className="text-text-muted">
              prompt {activeDeployment.promptVersionId}
              {published ? ` (${published.label})` : ""}
            </div>
            <div className="text-text-muted">
              KB {activeDeployment.kbSnapshotId ?? "—"} · voice {activeDeployment.ttsVoiceId ?? "—"}
            </div>
            {activeDeployment.publishedAt && (
              <div className="text-text-muted">published {relTime(activeDeployment.publishedAt)}</div>
            )}
            {priorDeployment && onRollback && (
              <button
                type="button"
                disabled={rollbackBusy}
                onClick={onRollback}
                className="mt-2 inline-flex items-center gap-1 rounded-md border border-amber-300 bg-amber-50 px-2 py-1 text-[11px] font-medium text-amber-900 hover:bg-amber-100 disabled:opacity-50"
              >
                <Undo2 className="h-3 w-3" />
                Rollback to {priorDeployment.promptVersionId}
              </button>
            )}
          </div>
        )}

        {drafts.length > 0 && (
          <div>
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-text-muted">
              Drafts ({drafts.length})
            </div>
            <div className="flex flex-col gap-1">
              {drafts.map((d) => (
                <div
                  key={d.id}
                  className={`flex items-center gap-1 rounded-md border px-2 py-1.5 text-[11px] ${
                    activeDraftId === d.id
                      ? "border-brand-primary bg-brand-tint/40"
                      : "border-[var(--border-token)] bg-white"
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => onLoadDraft(d)}
                    className="min-w-0 flex-1 truncate text-left font-mono hover:text-brand-primary"
                    title={d.id}
                  >
                    {d.label || d.id}
                  </button>
                  <button
                    type="button"
                    onClick={() => onDiscardDraft(d)}
                    className="shrink-0 rounded px-1.5 py-0.5 text-rose-700 hover:bg-rose-50"
                  >
                    Discard
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
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
                {v.status === "draft" && (
                  <span className="rounded-full bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">
                    draft
                  </span>
                )}
                <span className="ml-auto text-[10.5px] text-text-muted">{relTime(v.createdAt)}</span>
              </div>
              <div className="text-[11.5px] text-text-secondary">{v.summary}</div>
              <div className="text-[10.5px] text-text-muted">by {v.author}</div>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                <button
                  onClick={() => onCompare(v)}
                  className="rounded-md border border-[var(--border-token)] px-2 py-0.5 text-[11px] hover:bg-surface-sunken"
                >
                  Compare
                </button>
                {v.status === "draft" ? (
                  <button
                    onClick={() => onLoadDraft(v)}
                    className="rounded-md border border-[var(--border-token)] px-2 py-0.5 text-[11px] hover:bg-surface-sunken"
                  >
                    Load
                  </button>
                ) : (
                  <button
                    onClick={() => onRestore(v)}
                    className="inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] px-2 py-0.5 text-[11px] hover:bg-surface-sunken"
                  >
                    <RotateCcw className="h-3 w-3" /> Restore
                  </button>
                )}
              </div>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
