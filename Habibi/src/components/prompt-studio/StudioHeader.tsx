import { Beaker, ShieldCheck, UploadCloud } from "lucide-react";
import { Lozenge } from "@/components/ui/lozenge";

type Props = {
  currentVersion: string;
  /** Something exists to publish (a saved draft, or edits vs the live row). */
  canPublish?: boolean;
  nextVersion: string;
  dirty: boolean;
  personaLabel: string;
  saveStatus?: "idle" | "saving" | "saved" | "error";
  onTestSandbox: () => void;
  onPublish: () => void;
  onLint?: () => void;
  lintBusy?: boolean;
  /** Compiler gate: invalid conversation graph cannot ship. */
  publishBlocked?: boolean;
  flowErrorCount?: number;
  onFixFlow?: () => void;
  cardName?: string;
};

export function StudioHeader({
  currentVersion,
  canPublish,
  nextVersion,
  dirty,
  personaLabel,
  saveStatus = "idle",
  onTestSandbox,
  onPublish,
  onLint,
  lintBusy,
  publishBlocked = false,
  flowErrorCount = 0,
  onFixFlow,
  cardName,
}: Props) {
  // `dirty` means "differs from the live version", which is not the same as
  // "there is something to publish". On a card that has never shipped, the
  // baseline for `dirty` is the draft itself, so it goes false the moment
  // autosave settles — and gating Publish on it left a cloned card with no way
  // to ever publish its first version. A saved draft is publishable.
  const publishDisabled = !(canPublish ?? dirty) || publishBlocked;
  return (
    <header className="shrink-0 border-b border-border bg-surface px-250 py-150">
      <div className="flex flex-wrap items-center gap-100">
        <h1 className="text-[1.25rem] font-semibold text-text">
          {cardName ? cardName : "Agent studio"}
        </h1>
        {/* "published" was hardcoded, and currentVersion fell back to the
            newest version of any status — so a freshly cloned card with a
            single draft announced itself as "Collections-clone v1 published"
            while the fleet page correctly called it "draft only, unreachable". */}
        {currentVersion === "—" ? (
          <Lozenge tone="warning">never published</Lozenge>
        ) : (
          <Lozenge tone="selected">{currentVersion} published</Lozenge>
        )}
        <Lozenge tone="neutral">{personaLabel}</Lozenge>
        {dirty && (
          <Lozenge tone="warning">
            <span className="h-1.5 w-1.5 rounded-full bg-background-warning-bold" /> unsaved · draft {nextVersion}
          </Lozenge>
        )}
        {publishBlocked && (
          <Lozenge tone="danger">
            {flowErrorCount} flow error{flowErrorCount === 1 ? "" : "s"} — publish blocked
          </Lozenge>
        )}
        {saveStatus === "saving" && <Lozenge tone="neutral">Autosaving…</Lozenge>}
        {saveStatus === "saved" && !dirty && <Lozenge tone="success">Draft saved</Lozenge>}
        {saveStatus === "error" && <Lozenge tone="danger">Autosave failed</Lozenge>}
        <div className="ml-auto flex items-center gap-100">
          {onLint && (
            <button
              onClick={onLint}
              disabled={lintBusy}
              className="inline-flex items-center gap-050 rounded-medium border border-border px-150 py-075 text-body-small text-text hover:bg-surface-sunken disabled:opacity-50"
            >
              <ShieldCheck className="h-3.5 w-3.5" /> {lintBusy ? "Linting…" : "Lint prompt"}
            </button>
          )}
          <button
            onClick={onTestSandbox}
            className="inline-flex items-center gap-050 rounded-medium border border-border px-150 py-075 text-body-small text-text hover:bg-surface-sunken"
          >
            <Beaker className="h-3.5 w-3.5" /> Test in Sandbox
          </button>
          {publishBlocked && onFixFlow ? (
            <button
              onClick={onFixFlow}
              className="inline-flex items-center gap-050 rounded-medium border border-border-danger px-150 py-075 text-body-small font-medium text-text-danger-bolder hover:bg-background-danger-subtler"
            >
              Fix flow
            </button>
          ) : (
            <button
              onClick={onPublish}
              disabled={publishDisabled}
              className="inline-flex items-center gap-050 rounded-medium bg-background-brand-bold px-150 py-075 text-body-small font-medium text-white hover:bg-background-brand-bold-pressed disabled:cursor-not-allowed disabled:opacity-50"
            >
              <UploadCloud className="h-3.5 w-3.5" /> Publish {nextVersion}
            </button>
          )}
        </div>
      </div>
      <p className="text-body-small text-text-subtle">
        Tune this card&apos;s system prompt, persona, voice, tools and evals. Drafts autosave; publishing is a
        compiler.
        {publishBlocked
          ? " An invalid conversation graph cannot publish — the API rejects it even if this button were forced."
          : null}
      </p>
    </header>
  );
}
