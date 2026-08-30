import { Beaker, History, Sparkles, UploadCloud } from "lucide-react";
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
  /**
   * The costed Azure pass — a second opinion on the WRITING, not a
   * compliance check. The deterministic lint that used to sit beside it now
   * runs continuously in the editor and needs no control here.
   */
  onAiReview?: () => void;
  lintBusy?: boolean;
  /** Compiler gate: invalid conversation graph cannot ship. */
  publishBlocked?: boolean;
  flowErrorCount?: number;
  onFixFlow?: () => void;
  cardName?: string;
  /** Opens the version-history drawer. Was a permanent 320px rail. */
  onOpenHistory?: () => void;
  /** Shown on the History button so the drawer advertises what is behind it. */
  versionCount?: number;
  draftCount?: number;
  /**
   * The active-deployment read failed, so nothing on this header can honestly
   * claim what production is running.
   *
   * The fetcher behind it used to answer `null` on any failure, which this
   * header rendered as "not deployed" — a card serving every inbound call
   * reported as dark, during exactly the outage when someone would be looking.
   */
  deploymentUnknown?: boolean;
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
  onAiReview,
  lintBusy,
  publishBlocked = false,
  flowErrorCount = 0,
  onFixFlow,
  cardName,
  onOpenHistory,
  versionCount = 0,
  draftCount = 0,
  deploymentUnknown = false,
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
        <h1 className="heading-medium font-semibold text-text">
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
        {deploymentUnknown && (
          <Lozenge
            tone="warning"
            title="The active-deployment read failed. This is not a claim that the card is undeployed."
          >
            deployment state unknown
          </Lozenge>
        )}
        {dirty && (
          <Lozenge tone="warning">
            <span className="h-1.5 w-1.5 rounded-full bg-background-warning-bold" /> unsaved · draft{" "}
            {nextVersion}
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
          {onOpenHistory && (
            <button
              onClick={onOpenHistory}
              className="inline-flex items-center gap-050 rounded-medium border border-border px-150 py-075 text-body-small text-text hover:bg-surface-sunken"
            >
              <History className="h-3.5 w-3.5" />
              History
              {versionCount > 0 && (
                <span className="text-text-subtlest tabular-nums">{versionCount}</span>
              )}
              {/* A draft you forgot about is the one thing in that drawer worth
                  interrupting for, so it is the only thing that gets a dot. */}
              {draftCount > 0 && (
                <span
                  aria-label={`${draftCount} draft${draftCount === 1 ? "" : "s"}`}
                  className="h-1.5 w-1.5 rounded-full bg-background-warning-bold"
                />
              )}
            </button>
          )}
          {/* One action, not two. The deterministic lint used to sit here as
              its own button and it should never have needed one: it is
              instant, free, and answers a question the author is asking while
              typing — will the runtime keep what I just wrote? It now runs
              continuously in the editor, which is where its findings render.

              The cost of it having been a button is on record: linting every
              prompt version in the database turned up CRM tokens on three
              PUBLISHED cards — each one silently deleting the line it sits on,
              including the card every inbound call resolves to. Nobody had
              pressed it.

              What is left here is the half that genuinely has to be asked for:
              an Azure call, costed and slow, giving a second opinion on the
              writing. It is not a compliance check and no longer claims to be
              — the guardrails reach it as already enforced, so it critiques
              wording instead of listing rules the platform injects anyway. */}
          {onAiReview && (
            <button
              onClick={onAiReview}
              disabled={lintBusy}
              title="Ask the model what is weak in the words you wrote — vague directions, contradictions, promises no tool can keep. It is told the guardrails are already enforced, so it will not tell you to restate them. Advisory — it never edits your text."
              className="inline-flex items-center gap-050 rounded-medium border border-border px-150 py-075 text-body-small text-text hover:bg-surface-sunken disabled:opacity-50"
            >
              <Sparkles className="h-3.5 w-3.5" /> {lintBusy ? "Critiquing…" : "Critique wording"}
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
        Tune this card&apos;s system prompt, persona, voice, tools and evals. Drafts autosave;
        publishing is a compiler.
        {publishBlocked
          ? " An invalid conversation graph cannot publish — the API rejects it even if this button were forced."
          : null}
      </p>
    </header>
  );
}
