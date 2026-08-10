import { useState } from "react";
import { GitCommit, RotateCcw, Undo2 } from "lucide-react";
import type { PromptVersion } from "@/data/prompt-studio-seed";
import type { BotDeployment } from "@/api/prompt-studio";
import { Lozenge } from "@/components/ui/lozenge";

type Props = {
  versions: PromptVersion[];
  activeDraftId?: string | null;
  activeDeployment?: BotDeployment | null;
  priorDeployment?: BotDeployment | null;
  onCompare: (v: PromptVersion) => void;
  onRestore: (v: PromptVersion) => void;
  onLoadDraft: (v: PromptVersion) => void;
  // Promise-returning so the busy state can actually wait for the mutation —
  // a void prop made Promise.resolve(...) settle immediately and the button
  // re-enabled a frame later, allowing a second discard on the same draft.
  onDiscardDraft: (v: PromptVersion) => void | Promise<unknown>;
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
  const [discardingId, setDiscardingId] = useState<string | null>(null);
  const drafts = versions.filter((v) => v.status === "draft");
  const published = versions.find((v) => v.status === "published");

  return (
    <div className="flex h-full min-h-0 flex-col border-l border-border bg-surface">
      <div className="shrink-0 space-y-150 border-b border-border px-200 py-150">
        <div>
          <h3 className="text-body font-semibold text-text">Version history</h3>
          <p className="text-body-small text-text-subtlest">Compare, load drafts, restore, or roll back live.</p>
        </div>

        {activeDeployment && (
          <div className="rounded-medium border border-border bg-surface-sunken p-150 text-body-small">
            <div className="font-semibold text-text">Active production</div>
            <div className="mt-025 font-mono text-text-subtle">{activeDeployment.id}</div>
            <div className="text-text-subtlest">
              prompt {activeDeployment.promptVersionId}
              {published ? ` (${published.label})` : ""}
            </div>
            <div className="text-text-subtlest">
              KB {activeDeployment.kbSnapshotId ?? "—"} · voice{" "}
              {(() => {
                const tuning = activeDeployment.tuning as
                  | { tts?: { voice?: string } }
                  | undefined;
                const short =
                  (typeof tuning?.tts?.voice === "string" && tuning.tts.voice) ||
                  (typeof activeDeployment.voiceConfig?.azureVoiceName === "string"
                    ? activeDeployment.voiceConfig.azureVoiceName
                    : null) ||
                  activeDeployment.ttsVoiceId;
                return short || "—";
              })()}
            </div>
            {activeDeployment.publishedAt && (
              <div className="text-text-subtlest">published {relTime(activeDeployment.publishedAt)}</div>
            )}
            {priorDeployment && onRollback && (
              <button
                type="button"
                disabled={rollbackBusy}
                onClick={onRollback}
                className="mt-100 inline-flex items-center gap-050 rounded-medium border border-border-warning bg-background-warning-subtler px-100 py-050 text-body-small font-medium text-text-warning-bolder hover:bg-background-warning-subtler disabled:opacity-50"
              >
                <Undo2 className="h-3 w-3" />
                Rollback to {priorDeployment.promptVersionId}
              </button>
            )}
          </div>
        )}

        {drafts.length > 0 && (
          <div>
            <div className="mb-050 text-body-small font-semibold text-text-subtlest">
              Drafts ({drafts.length})
            </div>
            <div className="flex flex-col gap-050">
              {drafts.map((d) => (
                <div
                  key={d.id}
                  className={`flex items-center gap-050 rounded-medium border px-100 py-075 text-body-small ${
                    activeDraftId === d.id
                      ? "border-border-brand bg-background-brand-subtlest/40"
                      : "border-border bg-surface"
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => onLoadDraft(d)}
                    className="min-w-0 flex-1 truncate text-left font-mono hover:text-text-brand"
                    title={d.id}
                  >
                    {d.label || d.id}
                  </button>
                  <button
                    type="button"
                    disabled={discardingId === d.id}
                    onClick={() => {
                      const label = d.label || d.id;
                      if (!window.confirm(`Discard draft "${label}"? This cannot be undone.`)) return;
                      setDiscardingId(d.id);
                      Promise.resolve(onDiscardDraft(d)).finally(() => setDiscardingId(null));
                    }}
                    className="shrink-0 rounded px-075 py-025 text-text-danger-bolder hover:bg-background-danger-subtler disabled:opacity-50"
                  >
                    {discardingId === d.id ? "Discarding…" : "Discard"}
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-150">
        <ol className="relative ml-150 border-l border-border">
          {versions.map((v) => (
            <li key={v.id} className="mb-200 pl-200">
              <span className="absolute -left-100 mt-075 grid h-3.5 w-3.5 place-items-center rounded-full bg-background-brand-bold text-white">
                <GitCommit className="h-2.5 w-2.5" />
              </span>
              <div className="flex items-center gap-100">
                <span className="font-mono text-body-small font-semibold text-text">{v.label}</span>
                {v.status === "published" && <Lozenge tone="success">live</Lozenge>}
                {v.status === "draft" && <Lozenge tone="warning">draft</Lozenge>}
                <span className="ml-auto text-body-small text-text-subtlest">{relTime(v.createdAt)}</span>
              </div>
              <div className="text-body-small text-text-subtle">{v.summary}</div>
              <div className="text-body-small text-text-subtlest">by {v.author}</div>
              <div className="mt-075 flex flex-wrap gap-075">
                <button
                  onClick={() => onCompare(v)}
                  className="rounded-medium border border-border px-100 py-025 text-body-small hover:bg-surface-sunken"
                >
                  Compare
                </button>
                {v.status === "draft" ? (
                  <button
                    onClick={() => onLoadDraft(v)}
                    className="rounded-medium border border-border px-100 py-025 text-body-small hover:bg-surface-sunken"
                  >
                    Load
                  </button>
                ) : (
                  <button
                    onClick={() => onRestore(v)}
                    className="inline-flex items-center gap-050 rounded-medium border border-border px-100 py-025 text-body-small hover:bg-surface-sunken"
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
