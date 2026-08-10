import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronRight, RotateCcw } from "lucide-react";
import {
  AGENT_TUNING_PRESETS,
  clampAgentTuning,
  tuningFingerprint,
  type AgentTuning,
} from "@/data/agent-tuning";
import { VoiceCatalogBrowser } from "@/components/prompt-studio/VoiceCatalogBrowser";
import { VoiceDetailCard } from "@/components/prompt-studio/VoicePanel";
import { useVoicePreview } from "@/components/prompt-studio/useVoicePreview";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { fetchTtsVoiceDetail, type TtsCatalogVoice } from "@/api/prompt-studio";
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
  /** Layout override — SplitPanes supplies the width, so the fixed one goes. */
  className?: string;
};

type SectionKey = "voice" | "reasoning" | "listening" | "turn";

const LIVE_BADGE = (
  <span className="rounded bg-background-success-subtler px-050 py-025 text-body-small font-semibold text-text-success-bolder">
    live
  </span>
);
const NEXT_BADGE = (
  <span className="rounded bg-background-warning-subtler px-050 py-025 text-body-small font-semibold text-text-warning-bolder">
    next call
  </span>
);

// Trailing-edge window for live tuning applies (slider drags, pitch typing).
const LIVE_APPLY_DEBOUNCE_MS = 250;

function liveDeltaFromPartial(
  partial: Partial<AgentTuning>,
  next: AgentTuning,
): Partial<AgentTuning> {
  const pick = <T extends object>(sub: Partial<T> | undefined, full: T): Partial<T> | undefined => {
    if (!sub) return undefined;
    const keys = Object.keys(sub) as (keyof T)[];
    if (!keys.length) return undefined;
    const out: Partial<T> = {};
    for (const key of keys) out[key] = full[key];
    return out;
  };

  const delta: Partial<AgentTuning> = {};
  const llm = pick(partial.llm, next.llm);
  const tts = pick(partial.tts, next.tts);
  const stt = pick(partial.stt, next.stt);
  const vad = pick(partial.vad, next.vad);
  const turn = pick(partial.turn, next.turn);
  const interaction = pick(partial.interaction, next.interaction);
  if (llm) delta.llm = llm as AgentTuning["llm"];
  if (tts) delta.tts = tts as AgentTuning["tts"];
  if (stt) delta.stt = stt as AgentTuning["stt"];
  if (vad) delta.vad = vad as AgentTuning["vad"];
  if (turn) delta.turn = turn as AgentTuning["turn"];
  if (interaction) delta.interaction = interaction as AgentTuning["interaction"];
  return delta;
}

export function TuningStudio({
  value,
  onChange,
  onLiveApply,
  callLive = false,
  nextCallDirty = false,
  onRestartCall,
  disabled,
  className,
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

  // Live applies are debounced: each one is an HTTP PUT plus a data-channel
  // message, and the range inputs / free-text pitch field below fire on every
  // frame of a drag or every keystroke. Local state still updates immediately —
  // only the network side waits for the drag to settle. Deltas are merged so
  // the trailing call carries everything moved during the window.
  const pendingLive = useRef<Partial<AgentTuning>>({});
  const liveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (liveTimer.current) clearTimeout(liveTimer.current);
    },
    [],
  );

  const queueLiveApply = (delta: Partial<AgentTuning>) => {
    if (!onLiveApply) return;
    const merged = pendingLive.current;
    for (const [section, values] of Object.entries(delta)) {
      const key = section as keyof AgentTuning;
      merged[key] = { ...(merged[key] as object), ...(values as object) } as never;
    }
    if (liveTimer.current) clearTimeout(liveTimer.current);
    liveTimer.current = setTimeout(() => {
      const payload = pendingLive.current;
      pendingLive.current = {};
      liveTimer.current = null;
      if (Object.keys(payload).length) onLiveApply(payload);
    }, LIVE_APPLY_DEBOUNCE_MS);
  };

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
    if (live) queueLiveApply(liveDeltaFromPartial(partial, next));
  };

  return (
    <aside
      className={cn(
        "hidden h-full min-h-0 w-[18.75rem] shrink-0 flex-col border-r border-border bg-surface lg:flex",
        className,
      )}
    >
      <div className="shrink-0 border-b border-border p-150">
        <div className="flex items-center justify-between gap-100">
          <div className="text-body-small font-semibold text-text-subtlest">
            Agent Tuning
          </div>
          {dirtyVsPreset && (
            <span className="h-1.5 w-1.5 rounded-full bg-background-brand-bold" title="Modified from preset" />
          )}
        </div>
        <label className="mt-075 flex items-center gap-050 text-body-small text-text-subtle">
          <span className="text-text-subtlest">Preset</span>
          <select
            value={presetId}
            disabled={disabled}
            onChange={(e) => {
              const id = e.target.value;
              setPresetId(id);
              const p = AGENT_TUNING_PRESETS.find((x) => x.id === id);
              if (p) {
                // Same live path every other control uses. Gating on callLive
                // here meant a preset switch was the one change the parent
                // never saw as a live edit; applyTune is already a no-op when
                // no session is up, so the gate bought nothing.
                const next = clampAgentTuning(p.tuning);
                onChange(next);
                queueLiveApply({ llm: next.llm, tts: next.tts });
              }
            }}
            className="min-w-0 flex-1 rounded border border-border bg-surface px-075 py-050 text-body-small"
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
            className="mt-100 inline-flex w-full items-center justify-center gap-050 rounded-medium border border-border-warning-subtle bg-background-warning-subtler px-100 py-075 text-body-small font-medium text-text-warning-bolder hover:bg-background-warning-subtler"
          >
            <RotateCcw className="h-3 w-3" /> Restart call with these settings
          </button>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-100">
        <Section
          title="Voice & delivery"
          badge={LIVE_BADGE}
          open={open.voice}
          onToggle={() => setOpen((o) => ({ ...o, voice: !o.voice }))}
        >
          <TuningVoicePicker
            value={value.tts.voice}
            disabled={disabled}
            onChange={(shortName) =>
              patch({ tts: { ...value.tts, voice: shortName, style: value.tts.style } }, true)
            }
          />
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
    <div className="mb-100 rounded-medium border border-border">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-100 px-150 py-100 text-left text-body-small font-medium text-text hover:bg-surface-sunken"
      >
        <span>{title}</span>
        <span className="flex items-center gap-050">
          {badge}
          <span className="text-text-subtlest">
            {open ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
          </span>
        </span>
      </button>
      {open && <div className="space-y-100 border-t border-border px-150 py-100">{children}</div>}
    </div>
  );
}

function TuningVoicePicker({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (shortName: string) => void;
  disabled?: boolean;
}) {
  // The picker used to be name-only: 546 voices, no way to hear one and no way
  // to see anything about it. Both capabilities already existed on the full
  // browser — they were simply never passed down here.
  const preview = useVoicePreview();
  const [detail, setDetail] = useState<TtsCatalogVoice | null>(null);

  const openDetail = async (voice: TtsCatalogVoice) => {
    setDetail(voice);
    try {
      // The list payload is trimmed; styles/personalities/pricing come from the
      // per-voice endpoint. Show the row immediately, enrich when it lands.
      const full = await fetchTtsVoiceDetail(voice.shortName);
      setDetail((current) => (current?.shortName === voice.shortName ? full : current));
    } catch {
      /* keep the list-level detail rather than blanking the sheet */
    }
  };

  return (
    <>
      <VoiceCatalogBrowser
        mode="compact"
        value={value}
        disabled={disabled}
        showSyncControls={false}
        listHeight={200}
        onSelect={(voice) => onChange(voice.shortName)}
        onPreview={(voice) => preview.toggleVoice(voice)}
        onOpenDetail={(voice) => void openDetail(voice)}
        previewingShortName={preview.previewing}
        previewBusy={preview.playing || preview.loading}
      />
      <Dialog open={!!detail} onOpenChange={(open) => !open && setDetail(null)}>
        <DialogContent className="max-w-md gap-0 overflow-hidden p-0">
          {detail ? (
            <VoiceDetailCard
              voice={detail}
              onUse={() => {
                onChange(detail.shortName);
                setDetail(null);
              }}
              onPlay={() => preview.toggleVoice(detail)}
              playing={preview.previewing === detail.shortName && preview.playing}
            />
          ) : null}
        </DialogContent>
      </Dialog>
    </>
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
    <label className="block text-body-small text-text-subtle">
      <div className="mb-025 flex justify-between">
        <span>{label}</span>
        <span className="font-mono text-text-subtlest">{Number(value).toFixed(step < 1 ? 2 : 0)}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-[var(--background-brand-bold)]"
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
    <label className="flex items-center justify-between gap-100 text-body-small text-text-subtle">
      <span className="inline-flex items-center gap-050">
        {label}
        {nextCall ? NEXT_BADGE : null}
      </span>
      <select
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="rounded border border-border bg-surface px-075 py-025 text-body-small"
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
    <label className="flex items-center justify-between gap-100 text-body-small text-text-subtle">
      <span>{label}</span>
      <input
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="w-24 rounded border border-border bg-surface px-075 py-025 font-mono text-body-small"
      />
    </label>
  );
}
