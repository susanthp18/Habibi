import { Beaker, ShieldCheck, UploadCloud } from "lucide-react";
import { Lozenge } from "@/components/ui/lozenge";

type Props = {
  currentVersion: string;
  nextVersion: string;
  dirty: boolean;
  personaLabel: string;
  saveStatus?: "idle" | "saving" | "saved" | "error";
  onTestSandbox: () => void;
  onPublish: () => void;
  onLint?: () => void;
  lintBusy?: boolean;
};

export function StudioHeader({
  currentVersion,
  nextVersion,
  dirty,
  personaLabel,
  saveStatus = "idle",
  onTestSandbox,
  onPublish,
  onLint,
  lintBusy,
}: Props) {
  return (
    <header className="shrink-0 border-b border-border bg-surface px-250 py-150">
      <div className="flex flex-wrap items-center gap-100">
        <h1 className="text-[1.25rem] font-semibold text-text">Persona & prompt studio</h1>
        <Lozenge tone="selected">
          {currentVersion} published
        </Lozenge>
        <Lozenge tone="neutral">
          {personaLabel}
        </Lozenge>
        {dirty && (
          <Lozenge tone="warning">
            <span className="h-1.5 w-1.5 rounded-full bg-background-warning-bold" /> unsaved · draft {nextVersion}
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
          <button
            onClick={onPublish}
            disabled={!dirty}
            className="inline-flex items-center gap-050 rounded-medium bg-background-brand-bold px-150 py-075 text-body-small font-medium text-white hover:bg-background-brand-bold-pressed disabled:cursor-not-allowed disabled:opacity-50"
          >
            <UploadCloud className="h-3.5 w-3.5" /> Publish {nextVersion}
          </button>
        </div>
      </div>
      <p className="text-body-small text-text-subtle">
        Tune the bot&apos;s system prompt, persona, voice and guardrails. Drafts autosave; publishing bumps the live
        config.
      </p>
    </header>
  );
}
