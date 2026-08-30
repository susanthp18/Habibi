import { useMemo, useState } from "react";
import { GitCommit, RotateCcw, Undo2 } from "lucide-react";
import type { PromptVersion } from "@/data/prompt-studio-seed";
import type { BotDeployment } from "@/api/prompt-studio";
import { Lozenge, type LozengeTone } from "@/components/ui/lozenge";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

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

/**
 * Coarsest unit that still says something.
 *
 * The previous version only knew hours and days, so everything newer than
 * thirty minutes read "0h ago" — including the autosave that had just landed,
 * which is exactly the row you are looking at the timestamp to confirm. It also
 * had no floor, so a server clock a few seconds ahead produced "-0h ago".
 */
function relTime(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(ms)) return "—";
  const mins = Math.round(ms / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

/**
 * Every row says which of the three things it is.
 *
 * Only `published` and `draft` used to carry a chip, which left archived rows —
 * the great majority — indistinguishable from live ones at a glance. On kaia
 * that produced four consecutive rows reading "v1.5" where exactly one was the
 * resumable draft and three were abandoned attempts.
 */
const STATUS_TONE: Record<PromptVersion["status"], LozengeTone> = {
  published: "success",
  draft: "warning",
  archived: "neutral",
};
const STATUS_LABEL: Record<PromptVersion["status"], string> = {
  published: "live",
  draft: "draft",
  archived: "archived",
};

/**
 * Same label, several rows.
 *
 * A draft inherits the label of the version it descends from, and autosave, a
 * sandbox promote and an authored edit each write one — so a label is not an
 * identity and the drawer was presenting it as though it were.
 *
 * Numbered oldest-first on purpose: assigned from the top of a newest-first
 * list, every row's number would shift the moment another autosave landed, and
 * "attempt 2" has to mean the same row tomorrow for it to be worth printing.
 */
function attemptSuffixes(versions: PromptVersion[]): Map<string, string> {
  const byLabel = new Map<string, PromptVersion[]>();
  for (const v of versions) {
    const key = v.label || v.id;
    const bucket = byLabel.get(key);
    if (bucket) bucket.push(v);
    else byLabel.set(key, [v]);
  }
  const out = new Map<string, string>();
  for (const rows of byLabel.values()) {
    if (rows.length < 2) continue;
    [...rows]
      .sort((a, b) =>
        a.createdAt === b.createdAt ? a.id.localeCompare(b.id) : a.createdAt < b.createdAt ? -1 : 1,
      )
      .forEach((v, i) => {
        if (i > 0) out.set(v.id, ` · attempt ${i + 1}`);
      });
  }
  return out;
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
  /** The draft awaiting discard confirmation; see the AlertDialog below. */
  const [discardPending, setDiscardPending] = useState<PromptVersion | null>(null);
  const drafts = versions.filter((v) => v.status === "draft");
  const published = versions.find((v) => v.status === "published");
  const suffixes = useMemo(() => attemptSuffixes(versions), [versions]);

  // The one the editor comes back to. `_studio_card_versions` picks the newest
  // draft, and so does publish-by-bot, so on a card with more than one draft
  // this is the row that "resume where you left off" actually means.
  const resumableDraftId = drafts[0]?.id ?? null;

  // Grouped rather than one flat timeline. Chronological order is the honest
  // way to show *what happened*; it is the wrong way to show *what is live*,
  // and this drawer is opened to answer the second question.
  const groups = useMemo(
    () =>
      (
        [
          ["Live", versions.filter((v) => v.status === "published")],
          ["Active draft", versions.filter((v) => v.status === "draft")],
          ["Archived", versions.filter((v) => v.status === "archived")],
        ] as const
      ).filter(([, rows]) => rows.length > 0),
    [versions],
  );

  return (
    <div className="flex h-full min-h-0 flex-col border-l border-border bg-surface">
      <div className="shrink-0 space-y-150 border-b border-border px-200 py-150">
        <div>
          <h3 className="text-body font-semibold text-text">Version history</h3>
          <p className="text-body-small text-text-subtlest">
            Compare, load drafts, restore, or roll back live.
          </p>
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
                const tuning = activeDeployment.tuning as { tts?: { voice?: string } } | undefined;
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
              <div className="text-text-subtlest">
                published {relTime(activeDeployment.publishedAt)}
              </div>
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
            {/* "Drafts (1)" sat above a timeline showing four rows labelled
                v1.5, so the count read as wrong when it was the only honest
                number on screen. Naming what it counts is what reconciles the
                two. */}
            <div className="mb-050 text-body-small font-semibold text-text-subtlest">
              Active {drafts.length === 1 ? "draft" : "drafts"} ({drafts.length})
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
                    // Asked in the product's own surface rather than through
                    // `window.confirm`, which paints as browser chrome titled
                    // "localhost:8080 says" and blocks the renderer. The app
                    // ships the themed replacement; this was one of the last
                    // Agent Studio call sites still bypassing it.
                    onClick={() => setDiscardPending(d)}
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

      <div className="min-h-0 flex-1 space-y-200 overflow-y-auto p-150">
        {groups.map(([title, rows]) => (
          <section key={title}>
            <h4 className="mb-075 text-body-small font-semibold text-text-subtlest">
              {title} ({rows.length})
            </h4>
            <ol className="relative ml-150 border-l border-border">
              {rows.map((v) => (
                <li key={v.id} className="mb-200 pl-200">
                  <span
                    className={`absolute -left-100 mt-075 grid h-3.5 w-3.5 place-items-center rounded-full text-white ${
                      v.status === "archived" ? "bg-border-bold" : "bg-background-brand-bold"
                    }`}
                  >
                    <GitCommit className="h-2.5 w-2.5" />
                  </span>
                  <div className="flex flex-wrap items-center gap-100">
                    <span className="font-mono text-body-small font-semibold text-text">
                      {v.label}
                      {suffixes.get(v.id) ?? ""}
                    </span>
                    <Lozenge tone={STATUS_TONE[v.status]}>{STATUS_LABEL[v.status]}</Lozenge>
                    {v.id === resumableDraftId && drafts.length > 1 ? (
                      <Lozenge tone="information" title="The editor resumes this one on reload.">
                        resumable
                      </Lozenge>
                    ) : null}
                    <span className="ml-auto text-body-small text-text-subtlest">
                      {relTime(v.createdAt)}
                    </span>
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
          </section>
        ))}
      </div>
      {/* Replaces a window.confirm. Discarding a draft cannot be undone, so it
          is worth asking — but asked in the product's own surface: themed,
          escapable, and naming the draft rather than restating the click. */}
      <AlertDialog
        open={discardPending !== null}
        onOpenChange={(next) => {
          if (!next) setDiscardPending(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Discard draft {discardPending?.label || discardPending?.id}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              This cannot be undone. The published version is unaffected.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep the draft</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                const d = discardPending;
                setDiscardPending(null);
                if (!d) return;
                setDiscardingId(d.id);
                Promise.resolve(onDiscardDraft(d)).finally(() => setDiscardingId(null));
              }}
            >
              Discard it
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
