import { useMemo, useState } from "react";
import { RotateCcw } from "lucide-react";
import {
  AGENT_TUNING_PRESETS,
  clampAgentTuning,
  tuningFingerprint,
  type AgentTuning,
} from "@/data/agent-tuning";
import { cn } from "@/lib/utils";

type Props = {
  value: AgentTuning;
  onChange: (next: AgentTuning) => void;
  /** Live LLM/TTS delta (hot-swappable). */
  onLiveApply?: (delta: Partial<AgentTuning>) => void;
  callLive?: boolean;
  nextCallDirty?: boolean;
  onRestartCall?: () => void;
  disabled?: boolean;
};

type SectionKey = "voice" | "reasoning" | "listening" | "turn";

const LIVE_BADGE = (
  <span className="rounded bg-emerald-50 px-1 py-0.5 text-[9px] font-semibold uppercase text-emerald-700">
    live
  </span>
);
const NEXT_BADGE = (
  <span className="rounded bg-amber-50 px-1 py-0.5 text-[9px] font-semibold uppercase text-amber-700">
    next call
  </span>
);

export function TuningStudio({
  value,
  onChange,
  onLiveApply,
  callLive = false,
  nextCallDirty = false,
  onRestartCall,
  disabled,
}: Props) {
  const [open, setOpen] = useState<Record<SectionKey, boolean>>({
    voice: true,
    reasoning: true,
    listening: false,
    turn: false,
  });
  const [presetId, setPresetId] = useState("empathetic-collections");

  const activePreset = AGENT_TUNING_PRESETS.find((p) => p.id === presetId);
  const dirtyVsPreset = useMemo(() => {
    if (!activePreset) return false;
    return tuningFingerprint(value) !== tuningFingerprint(activePreset.tuning);
  }, [value, activePreset]);

  const patch = (partial: Partial<AgentTuning>, live?: boolean) => {
    const next = clampAgentTuning({
      ...value,
      ...partial,
      llm: partial.llm ? { ...value.llm, ...partial.llm } : value.llm,
      tts: partial.tts ? { ...value.tts, ...partial.tts } : value.tts,
      stt: partial.stt ? { ...value.stt, ...partial.stt } : value.stt,
      vad: partial.vad ? { ...value.vad, ...partial.vad } : value.vad,
      turn: partial.turn ? { ...value.turn, ...partial.turn } : value.turn,
      interaction: partial.interaction
        ? { ...value.interaction, ...partial.interaction }
        : value.interaction,
    });
    onChange(next);
    if (live && onLiveApply) onLiveApply(partial);
  };

  return (
    <aside className="hidden h-full min-h-0 w-[300px] shrink-0 flex-col border-r border-[var(--border-token)] bg-surface-card lg:flex">
      <div className="shrink-0 border-b border-[var(--border-token)] p-3">
        <div className="flex items-center justify-between gap-2">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-text-muted">
            Agent Tuning
          </div>
          {dirtyVsPreset && (
            <span className="h-1.5 w-1.5 rounded-full bg-brand-primary" title="Modified from preset" />
          )}
        </div>
        <label className="mt-1.5 flex items-center gap-1 text-[11px] text-text-secondary">
          <span className="text-text-muted">Preset</span>
          <select
            value={presetId}
            disabled={disabled}
            onChange={(e) => {
              const id = e.target.value;
              setPresetId(id);
              const p = AGENT_TUNING_PRESETS.find((x) => x.id === id);
              if (p) onChange(clampAgentTuning(p.tuning));
            }}
            className="min-w-0 flex-1 rounded border border-[var(--border-token)] bg-surface-card px-1.5 py-1 text-[11.5px]"
          >
            {AGENT_TUNING_PRESETS.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        {callLive && nextCallDirty && onRestartCall && (
          <button
            type="button"
            onClick={onRestartCall}
            className="mt-2 inline-flex w-full items-center justify-center gap-1 rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5 text-[11.5px] font-medium text-amber-800 hover:bg-amber-100"
          >
            <RotateCcw className="h-3 w-3" /> Restart call with these settings
          </button>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        <Section
          title="Voice & delivery"
          badge={LIVE_BADGE}
          open={open.voice}
          onToggle={() => setOpen((o) => ({ ...o, voice: !o.voice }))}
        >
          <SelectRow
            label="Style"
            value={value.tts.style}
            options={["empathetic", "friendly", "cheerful", "hopeful"]}
            disabled={disabled}
            onChange={(v) => patch({ tts: { ...value.tts, style: v } }, true)}
          />
          <SliderRow
            label="Style degree"
            min={0.01}
            max={2}
            step={0.05}
            value={Number(value.tts.style_degree)}
            disabled={disabled}
            onChange={(n) =>
              patch({ tts: { ...value.tts, style_degree: String(n) } }, true)
            }
          />
          <SliderRow
            label="Rate"
            min={0.85}
            max={1.25}
            step={0.01}
            value={Number(value.tts.rate)}
            disabled={disabled}
            onChange={(n) => patch({ tts: { ...value.tts, rate: n.toFixed(2) } }, true)}
          />
          <TextRow
            label="Pitch"
            value={value.tts.pitch}
            disabled={disabled}
            onChange={(v) => patch({ tts: { ...value.tts, pitch: v } }, true)}
          />
          <SelectRow
            label="Aggregation"
            value={value.tts.text_aggregation_mode}
            options={["SENTENCE", "TOKEN"]}
            disabled={disabled}
            onChange={(v) =>
              patch({
                tts: {
                  ...value.tts,
                  text_aggregation_mode: v as "SENTENCE" | "TOKEN",
                },
              })
            }
            nextCall
          />
        </Section>

        <Section
          title="Reasoning"
          badge={LIVE_BADGE}
          open={open.reasoning}
          onToggle={() => setOpen((o) => ({ ...o, reasoning: !o.reasoning }))}
        >
          <SliderRow
            label="Temperature"
            min={0}
            max={2}
            step={0.05}
            value={value.llm.temperature}
            disabled={disabled}
            onChange={(n) => patch({ llm: { ...value.llm, temperature: n } }, true)}
          />
          <SliderRow
            label="Top P"
            min={0}
            max={1}
            step={0.05}
            value={value.llm.top_p}
            disabled={disabled}
            onChange={(n) => patch({ llm: { ...value.llm, top_p: n } }, true)}
          />
          <SliderRow
            label="Freq. penalty"
            min={-2}
            max={2}
            step={0.1}
            value={value.llm.frequency_penalty}
            disabled={disabled}
            onChange={(n) => patch({ llm: { ...value.llm, frequency_penalty: n } }, true)}
          />
          <SliderRow
            label="Max tokens"
            min={40}
            max={400}
            step={10}
            value={value.llm.max_completion_tokens}
            disabled={disabled}
            onChange={(n) =>
              patch({ llm: { ...value.llm, max_completion_tokens: Math.round(n) } }, true)
            }
          />
        </Section>

        <Section
          title="Listening"
          badge={NEXT_BADGE}
          open={open.listening}
          onToggle={() => setOpen((o) => ({ ...o, listening: !o.listening }))}
        >
          <SliderRow
            label="VAD confidence"
            min={0.1}
            max={1}
            step={0.05}
            value={value.vad.confidence}
            disabled={disabled}
            onChange={(n) => patch({ vad: { ...value.vad, confidence: n } })}
          />
          <SliderRow
            label="VAD start (s)"
            min={0.05}
            max={1}
            step={0.05}
            value={value.vad.start_secs}
            disabled={disabled}
            onChange={(n) => patch({ vad: { ...value.vad, start_secs: n } })}
          />
          <SliderRow
            label="Smart-Turn stop (s)"
            min={1}
            max={8}
            step={0.5}
            value={value.turn.stop_secs}
            disabled={disabled}
            onChange={(n) => patch({ turn: { ...value.turn, stop_secs: n } })}
          />
          <SelectRow
            label="STT language"
            value={value.stt.language}
            options={["en-IN", "en-US", "hi-IN"]}
            disabled={disabled}
            onChange={(v) => patch({ stt: { ...value.stt, language: v } })}
          />
        </Section>

        <Section
          title="Turn-taking"
          badge={NEXT_BADGE}
          open={open.turn}
          onToggle={() => setOpen((o) => ({ ...o, turn: !o.turn }))}
        >
          <SelectRow
            label="Barge-in"
            value={value.interaction.barge_in}
            options={["on", "min_words", "locked"]}
            disabled={disabled}
            onChange={(v) =>
              patch({
                interaction: {
                  ...value.interaction,
                  barge_in: v as AgentTuning["interaction"]["barge_in"],
                },
              })
            }
          />
          {value.interaction.barge_in === "min_words" && (
            <SliderRow
              label="Min words"
              min={1}
              max={8}
              step={1}
              value={value.interaction.min_words}
              disabled={disabled}
              onChange={(n) =>
                patch({
                  interaction: { ...value.interaction, min_words: Math.round(n) },
                })
              }
            />
          )}
          <SliderRow
            label="Idle timeout (s)"
            min={0}
            max={20}
            step={1}
            value={value.interaction.idle_timeout_secs}
            disabled={disabled}
            onChange={(n) =>
              patch({
                interaction: { ...value.interaction, idle_timeout_secs: n },
              })
            }
          />
        </Section>
      </div>
    </aside>
  );
}

function Section({
  title,
  badge,
  open,
  onToggle,
  children,
}: {
  title: string;
  badge: React.ReactNode;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-2 rounded-md border border-[var(--border-token)]">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-2 px-2.5 py-2 text-left text-[12px] font-medium text-text-primary hover:bg-surface-sunken"
      >
        <span>{title}</span>
        <span className="flex items-center gap-1">
          {badge}
          <span className="text-text-muted">{open ? "▾" : "▸"}</span>
        </span>
      </button>
      {open && <div className="space-y-2 border-t border-[var(--border-token)] px-2.5 py-2">{children}</div>}
    </div>
  );
}

function SliderRow({
  label,
  value,
  min,
  max,
  step,
  onChange,
  disabled,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (n: number) => void;
  disabled?: boolean;
}) {
  return (
    <label className="block text-[11px] text-text-secondary">
      <div className="mb-0.5 flex justify-between">
        <span>{label}</span>
        <span className="font-mono text-text-muted">{Number(value).toFixed(step < 1 ? 2 : 0)}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-[var(--brand-primary)]"
      />
    </label>
  );
}

function SelectRow({
  label,
  value,
  options,
  onChange,
  disabled,
  nextCall,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
  disabled?: boolean;
  nextCall?: boolean;
}) {
  return (
    <label className="flex items-center justify-between gap-2 text-[11px] text-text-secondary">
      <span className="inline-flex items-center gap-1">
        {label}
        {nextCall ? NEXT_BADGE : null}
      </span>
      <select
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className={cn(
          "rounded border border-[var(--border-token)] bg-surface-card px-1.5 py-0.5 text-[11px]",
        )}
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}

function TextRow({
  label,
  value,
  onChange,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
}) {
  return (
    <label className="flex items-center justify-between gap-2 text-[11px] text-text-secondary">
      <span>{label}</span>
      <input
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="w-24 rounded border border-[var(--border-token)] bg-surface-card px-1.5 py-0.5 font-mono text-[11px]"
      />
    </label>
  );
}
