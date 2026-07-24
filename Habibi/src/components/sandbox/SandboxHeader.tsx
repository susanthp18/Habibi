import { Download, RotateCcw, Rocket } from "lucide-react";
import type { PromptVersion } from "@/data/prompt-studio-seed";
import type { Scenario } from "@/data/sandbox-seed";
import { cn } from "@/lib/utils";

export type SandboxMode = "text" | "live";

type KbOption = { id: string; label: string };

type Props = {
  mode: SandboxMode;
  onMode: (m: SandboxMode) => void;
  liveEnabled?: boolean;
  promptVersionId: string;
  promptVersions: PromptVersion[];
  onPromptVersion: (id: string) => void;
  kbSnapshotId: string;
  kbSnapshots: KbOption[];
  onKbSnapshot: (id: string) => void;
  scenarioId: string;
  scenarios: Scenario[];
  onScenario: (id: string) => void;
  turnsUsed: number;
  turnsMax: number;
  statusLabel?: string;
  onReset: () => void;
  onExport: () => void;
  onPromote: () => void;
};

export function SandboxHeader(p: Props) {
  const activePrompt =
    p.promptVersions.find((v) => v.id === p.promptVersionId) ?? p.promptVersions[0];
  const remaining = Math.max(0, p.turnsMax - p.turnsUsed);
  return (
    <header className="shrink-0 border-b border-[var(--border-token)] bg-surface-card px-5 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-[18px] font-semibold text-brand-navy">Call Simulation Sandbox</h1>
        <span className="rounded-full bg-brand-tint px-2 py-0.5 text-[11px] font-medium text-brand-primary-dark">
          Safe pre-prod harness
        </span>
        {activePrompt && activePrompt.status !== "published" && (
          <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700">
            Testing draft
          </span>
        )}
        {p.statusLabel && (
          <span className="rounded-full bg-surface-sunken px-2 py-0.5 text-[11px] font-medium text-text-secondary">
            {p.statusLabel}
          </span>
        )}

        <div className="inline-flex rounded-md border border-[var(--border-token)] p-0.5 text-[11.5px]">
          <button
            type="button"
            onClick={() => p.onMode("text")}
            className={cn(
              "rounded px-2.5 py-1 font-medium",
              p.mode === "text"
                ? "bg-brand-primary text-white"
                : "text-text-secondary hover:bg-surface-sunken",
            )}
            title="Rehearse prompts and KB without writing CRM rows"
          >
            Prompt rehearsal
          </button>
          <button
            type="button"
            onClick={() => {
              if (!p.liveEnabled) return;
              p.onMode("live");
            }}
            disabled={!p.liveEnabled}
            title={
              p.liveEnabled
                ? "Live CRM call — writes real interactions, promises, and leads"
                : "Live CRM call — start voice worker first (python -m voice.bot)"
            }
            className={cn(
              "rounded px-2.5 py-1 font-medium",
              p.mode === "live"
                ? "bg-brand-primary text-white"
                : "text-text-secondary hover:bg-surface-sunken",
              !p.liveEnabled && "cursor-not-allowed opacity-50",
            )}
          >
            Live CRM call
          </button>
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          {p.mode === "text" && (
            <span
              className={cn(
                "rounded-full px-2 py-0.5 text-[11px] font-medium",
                remaining <= 0
                  ? "bg-red-50 text-red-700"
                  : remaining === 1
                    ? "bg-amber-50 text-amber-700"
                    : "bg-surface-sunken text-text-secondary",
              )}
              title="Customer→bot exchanges left in this text run"
            >
              {remaining}/{p.turnsMax} turns left
            </span>
          )}
          <Select
            label="Prompt"
            value={p.promptVersionId}
            onChange={p.onPromptVersion}
            options={p.promptVersions.map((v) => ({
              value: v.id,
              label: `${v.label}${v.status === "published" ? " (live)" : v.status === "draft" ? " (draft)" : ""}`,
            }))}
          />
          <Select
            label="KB"
            value={p.kbSnapshotId}
            onChange={p.onKbSnapshot}
            options={p.kbSnapshots.map((s) => ({ value: s.id, label: s.label }))}
          />
          <Select
            label="Scenario"
            value={p.scenarioId}
            onChange={p.onScenario}
            options={p.scenarios.map((s) => ({ value: s.id, label: s.title }))}
          />
          <button
            type="button"
            onClick={p.onReset}
            className="inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] px-2.5 py-1.5 text-[12px] hover:bg-surface-sunken"
          >
            <RotateCcw className="h-3.5 w-3.5" /> Reset
          </button>
          <button
            type="button"
            onClick={p.onExport}
            className="inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] px-2.5 py-1.5 text-[12px] hover:bg-surface-sunken"
          >
            <Download className="h-3.5 w-3.5" /> Export
          </button>
          <button
            type="button"
            onClick={p.onPromote}
            className="inline-flex items-center gap-1 rounded-md bg-brand-primary px-2.5 py-1.5 text-[12px] font-medium text-white hover:bg-brand-primary-dark"
          >
            <Rocket className="h-3.5 w-3.5" /> Promote to Production
          </button>
        </div>
      </div>
      <p className="mt-1.5 text-[12px] text-text-secondary">
        Rehearse the collections bot before production. Prompt rehearsal spends chat tokens only.
        Live CRM call is a real duplex session via Pipecat — it writes real CRM rows (interactions,
        promises, leads) against the prompt and knowledge you selected.
      </p>
    </header>
  );
}

function Select({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: Array<{ value: string; label: string }>;
}) {
  return (
    <label className="inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] bg-surface-card px-2 py-1 text-[11.5px] text-text-secondary">
      <span className="text-text-muted">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-transparent text-text-primary focus:outline-none"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}
