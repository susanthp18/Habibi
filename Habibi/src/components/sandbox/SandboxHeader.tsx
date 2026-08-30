import { Link } from "@tanstack/react-router";
import { ChevronDown, Download, Pencil, RotateCcw, Rocket } from "lucide-react";
import type { PromptVersion } from "@/data/prompt-studio-seed";
import type { Scenario } from "@/data/sandbox-seed";
import { cn } from "@/lib/utils";
import { Lozenge } from "@/components/ui/lozenge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export type SandboxMode = "text" | "live";

type KbOption = { id: string; label: string };

type Props = {
  mode: SandboxMode;
  onMode: (m: SandboxMode) => void;
  liveEnabled?: boolean;
  promptVersionId: string;
  promptVersions: PromptVersion[];
  onPromptVersion: (id: string) => void;
  cardId?: string;
  cards?: { id: string; label: string }[];
  onCard?: (id: string) => void;
  skillSlug?: string;
  skills?: { slug: string; label: string }[];
  onSkill?: (slug: string) => void;
  kbSnapshotId: string;
  kbSnapshots: KbOption[];
  onKbSnapshot: (id: string) => void;
  scenarioId: string;
  scenarios: Scenario[];
  onScenario: (id: string) => void;
  turnsUsed: number;
  turnsMax: number;
  statusLabel?: string;
  /** Card the run is against. Present, it offers the way back to the editor —
   *  the fleet index and the editor both link *into* the sandbox, and there was
   *  no link out. */
  editBotId?: string | null;
  onReset: () => void;
  onExport: () => void;
  /** CRM interaction backing the current call; gates the server-side exports. */
  interactionId?: string | null;
  onExportReport?: (format: "md" | "json") => void;
  onPromote: () => void;
};

export function SandboxHeader(p: Props) {
  const activePrompt = p.promptVersions.find((v) => v.id === p.promptVersionId);
  const remaining = Math.max(0, p.turnsMax - p.turnsUsed);
  return (
    <header className="shrink-0 border-b border-border bg-surface px-250 py-150">
      <div className="flex flex-wrap items-center gap-100">
        <h1 className="heading-medium font-semibold text-text">Call simulation sandbox</h1>
        <Lozenge tone="selected">Safe pre-prod harness</Lozenge>
        {activePrompt && activePrompt.status !== "published" && (
          <Lozenge tone="warning">Testing draft</Lozenge>
        )}
        {p.statusLabel && <Lozenge tone="neutral">{p.statusLabel}</Lozenge>}
        {p.editBotId ? (
          <Link
            to="/agent-studio/$botId"
            params={{ botId: p.editBotId }}
            className="inline-flex items-center gap-050 text-body-small text-text-brand hover:underline"
            title="Open this card in Agent Studio"
          >
            <Pencil className="h-3 w-3" /> Edit card
          </Link>
        ) : null}

        <div className="inline-flex rounded-medium border border-border p-025 text-body-small">
          <button
            type="button"
            onClick={() => p.onMode("text")}
            className={cn(
              "rounded px-150 py-050 font-medium",
              p.mode === "text"
                ? "bg-background-brand-bold text-white"
                : "text-text-subtle hover:bg-surface-sunken",
            )}
            // Was "without writing CRM rows", which is not true: when a
            // customer is pinned to the run, sandbox_runtime enables the write
            // tools and create_promise_to_pay / flag_dispute / capture_lead go
            // straight to domain.*, exactly as they do on a live call.
            title="Text-only: same prompt and KB, no voice pipeline and no call flow. Still writes CRM rows when a customer is pinned."
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
              "rounded px-150 py-050 font-medium",
              p.mode === "live"
                ? "bg-background-brand-bold text-white"
                : "text-text-subtle hover:bg-surface-sunken",
              !p.liveEnabled && "cursor-not-allowed opacity-50",
            )}
          >
            Live CRM call
          </button>
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-100">
          {p.mode === "text" && (
            <Lozenge
              tone={remaining <= 0 ? "danger" : remaining === 1 ? "warning" : "neutral"}
              title="Customer→bot exchanges left in this text run"
            >
              {remaining}/{p.turnsMax} turns left
            </Lozenge>
          )}
          {p.cards && p.cards.length > 0 && p.onCard && (
            <Select
              label="Card"
              value={p.cardId ?? p.cards[0]!.id}
              onChange={p.onCard}
              options={p.cards.map((c) => ({ value: c.id, label: c.label }))}
            />
          )}
          {p.skills && p.skills.length > 0 && p.onSkill && (
            <Select
              label="Skill"
              value={p.skillSlug ?? ""}
              onChange={p.onSkill}
              options={[
                { value: "", label: "Auto (intent)" },
                ...p.skills.map((s) => ({ value: s.slug, label: s.label })),
              ]}
            />
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
            className="inline-flex items-center gap-050 rounded-medium border border-border px-150 py-075 text-body-small hover:bg-surface-sunken"
          >
            <RotateCcw className="h-3.5 w-3.5" /> Reset
          </button>
          {/* Three renderings of one call. The report is the one to reach for
              when you want a second opinion from another model — it carries the
              latency split, the tool calls and the guardrail flags, which the
              turn dump never did. Both server exports need a live interaction. */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="inline-flex items-center gap-050 rounded-medium border border-border px-150 py-075 text-body-small hover:bg-surface-sunken"
              >
                <Download className="h-3.5 w-3.5" /> Export
                <ChevronDown className="h-3 w-3" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-72">
              <DropdownMenuItem
                disabled={!p.interactionId}
                onSelect={() => p.onExportReport?.("md")}
              >
                <div>
                  <div className="font-medium">Full call report (Markdown)</div>
                  <div className="text-body-small text-text-subtlest">
                    Transcript, latency by stage, tools, guardrails — paste into a model
                  </div>
                </div>
              </DropdownMenuItem>
              <DropdownMenuItem
                disabled={!p.interactionId}
                onSelect={() => p.onExportReport?.("json")}
              >
                <div>
                  <div className="font-medium">Full call data (JSON)</div>
                  <div className="text-body-small text-text-subtlest">
                    Same record, machine-readable
                  </div>
                </div>
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={p.onExport}>
                <div>
                  <div className="font-medium">Turns only (JSON)</div>
                  <div className="text-body-small text-text-subtlest">
                    What is on screen — works without a call
                  </div>
                </div>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <button
            type="button"
            onClick={p.onPromote}
            className="inline-flex items-center gap-050 rounded-medium bg-background-brand-bold px-150 py-075 text-body-small font-medium text-white hover:bg-background-brand-bold-pressed"
          >
            <Rocket className="h-3.5 w-3.5" /> Promote to Production
          </button>
        </div>
      </div>
      {/* The two modes are different runtimes, not two skins on one. Saying so
          matters: a prompt that rehearses cleanly can still misbehave on a
          call, because rehearsal never executes the flow graph's node prompts —
          which is where greeting, verification and hub behaviour actually live. */}
      <p className="mt-075 text-body-small text-text-subtle">
        <span className="font-medium text-text-subtle">Prompt rehearsal</span> replays the prompt
        and knowledge base over text, one turn at a time — it does not run the call flow, voice
        pipeline, or identity verification, so greeting and turn-taking behaviour cannot be tested
        here. <span className="font-medium text-text-subtle">Live CRM call</span> is a real duplex
        session via Pipecat that exercises the full flow graph. Both write real CRM rows
        (interactions, promises, leads) when a customer is pinned.
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
    <label className="inline-flex items-center gap-050 rounded-medium border border-border bg-surface px-100 py-050 text-body-small text-text-subtle">
      <span className="text-text-subtlest">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-transparent text-text focus:outline-none"
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
