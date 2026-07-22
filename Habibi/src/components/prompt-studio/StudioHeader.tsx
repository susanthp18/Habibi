import { Beaker, UploadCloud } from "lucide-react";

type Props = {
  currentVersion: string;
  nextVersion: string;
  dirty: boolean;
  personaLabel: string;
  onTestSandbox: () => void;
  onPublish: () => void;
};

export function StudioHeader({ currentVersion, nextVersion, dirty, personaLabel, onTestSandbox, onPublish }: Props) {
  return (
    <header className="shrink-0 border-b border-[var(--border-token)] bg-surface-card px-5 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-[18px] font-semibold text-brand-navy">Persona & Prompt Studio</h1>
        <span className="rounded-full bg-brand-tint px-2 py-0.5 text-[11px] font-medium text-brand-primary-dark">
          {currentVersion} published
        </span>
        <span className="rounded-full bg-surface-sunken px-2 py-0.5 text-[11px] font-medium text-text-secondary">
          {personaLabel}
        </span>
        {dirty && (
          <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700">
            <span className="h-1.5 w-1.5 rounded-full bg-amber-500" /> unsaved · draft {nextVersion}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={onTestSandbox}
            className="inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] px-3 py-1.5 text-[12px] text-text-primary hover:bg-surface-sunken"
          >
            <Beaker className="h-3.5 w-3.5" /> Test in Sandbox
          </button>
          <button
            onClick={onPublish}
            disabled={!dirty}
            className="inline-flex items-center gap-1 rounded-md bg-brand-primary px-3 py-1.5 text-[12px] font-medium text-white shadow-sm hover:bg-brand-primary-dark disabled:cursor-not-allowed disabled:opacity-50"
          >
            <UploadCloud className="h-3.5 w-3.5" /> Publish {nextVersion}
          </button>
        </div>
      </div>
      <p className="text-[12px] text-text-secondary">
        Tune the bot's system prompt, persona, voice and guardrails. Every change is versioned; publishing bumps the live config.
      </p>
    </header>
  );
}
