import { Download, RotateCcw, Rocket } from "lucide-react";
import { VERSION_HISTORY } from "@/data/prompt-studio-seed";
import { KB_SNAPSHOTS, SCENARIOS } from "@/data/sandbox-seed";

type Props = {
  promptVersionId: string;
  onPromptVersion: (id: string) => void;
  kbSnapshotId: string;
  onKbSnapshot: (id: string) => void;
  scenarioId: string;
  onScenario: (id: string) => void;
  onReset: () => void;
  onExport: () => void;
  onPromote: () => void;
};

export function SandboxHeader(p: Props) {
  const activePrompt = VERSION_HISTORY.find((v) => v.id === p.promptVersionId) ?? VERSION_HISTORY[0];
  return (
    <header className="shrink-0 border-b border-[var(--border-token)] bg-surface-card px-5 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-[18px] font-semibold text-brand-navy">Call Simulation Sandbox</h1>
        <span className="rounded-full bg-brand-tint px-2 py-0.5 text-[11px] font-medium text-brand-primary-dark">
          Safe pre-prod harness
        </span>
        {activePrompt.status !== "published" && (
          <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700">
            Testing draft
          </span>
        )}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Select label="Prompt" value={p.promptVersionId} onChange={p.onPromptVersion}
            options={VERSION_HISTORY.map((v) => ({ value: v.id, label: `${v.label}${v.status === "published" ? " (live)" : ""}` }))} />
          <Select label="KB" value={p.kbSnapshotId} onChange={p.onKbSnapshot}
            options={KB_SNAPSHOTS.map((s) => ({ value: s.id, label: s.label }))} />
          <Select label="Scenario" value={p.scenarioId} onChange={p.onScenario}
            options={SCENARIOS.map((s) => ({ value: s.id, label: s.title }))} />
          <button onClick={p.onReset} className="inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] px-2.5 py-1.5 text-[12px] hover:bg-surface-sunken">
            <RotateCcw className="h-3.5 w-3.5" /> Reset
          </button>
          <button onClick={p.onExport} className="inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] px-2.5 py-1.5 text-[12px] hover:bg-surface-sunken">
            <Download className="h-3.5 w-3.5" /> Export
          </button>
          <button onClick={p.onPromote} className="inline-flex items-center gap-1 rounded-md bg-brand-primary px-2.5 py-1.5 text-[12px] font-medium text-white hover:bg-brand-primary-dark">
            <Rocket className="h-3.5 w-3.5" /> Promote to Production
          </button>
        </div>
      </div>
      <p className="text-[12px] text-text-secondary">
        Text or talk to the bot under a chosen prompt-version + KB snapshot. Watch retrieval, intent and sentiment in the right pane.
      </p>
    </header>
  );
}

function Select({
  label, value, onChange, options,
}: { label: string; value: string; onChange: (v: string) => void; options: Array<{ value: string; label: string }> }) {
  return (
    <label className="inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] bg-surface-card px-2 py-1 text-[11.5px] text-text-secondary">
      <span className="text-text-muted">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} className="bg-transparent text-text-primary focus:outline-none">
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </label>
  );
}
