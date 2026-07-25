import { useEffect, useRef, useState } from "react";
import { Play, Square, Volume2 } from "lucide-react";
import { toast } from "sonner";
import { Slider } from "@/components/ui/slider";
import { previewTts } from "@/api/prompt-studio";
import {
  LANGUAGES,
  PRESETS,
  renderPersonaPreview,
  type PersonaPreset,
  type PersonaState,
  type PersonaTraitKey,
  type VoiceConfig,
} from "@/data/prompt-studio-seed";

const TRAITS: Array<{ key: PersonaTraitKey; label: string; lo: string; hi: string }> = [
  { key: "empathy", label: "Empathy", lo: "Transactional", hi: "Warm" },
  { key: "firmness", label: "Firmness", lo: "Soft", hi: "Direct" },
  { key: "formality", label: "Formality", lo: "Casual", hi: "Formal" },
  { key: "verbosity", label: "Verbosity", lo: "Concise", hi: "Detailed" },
  { key: "upsell", label: "Proactive Upsell", lo: "Never", hi: "Always" },
];

type Props = {
  value: PersonaState;
  onChange: (next: PersonaState) => void;
  presets?: PersonaPreset[];
  /** Current TTS voice settings — used to speak the persona preview. */
  voice?: VoiceConfig;
};

export function PersonaSliders({ value, onChange, presets = PRESETS, voice }: Props) {
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);

  const update = (patch: Partial<PersonaState>) => onChange({ ...value, ...patch });
  const setTrait = (k: PersonaTraitKey, v: number) =>
    onChange({ ...value, traits: { ...value.traits, [k]: v } });

  const toggleFallback = (lang: string) => {
    const has = value.fallbackLanguages.includes(lang);
    update({
      fallbackLanguages: has
        ? value.fallbackLanguages.filter((l) => l !== lang)
        : [...value.fallbackLanguages, lang],
    });
  };

  const stop = () => {
    const a = audioRef.current;
    if (a) {
      a.onended = null;
      a.pause();
      a.removeAttribute("src");
      audioRef.current = null;
    }
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    }
    setPlaying(false);
    setLoading(false);
  };

  // Stop playback and revoke the blob URL if the tab unmounts mid-preview
  // (PersonaSliders is conditionally rendered), matching VoicePanel's guard.
  useEffect(() => () => stop(), []);

  const hearPreview = async () => {
    if (playing || loading) {
      stop();
      return;
    }
    if (!voice?.voiceId && !voice?.azureVoiceName) {
      toast.error("Pick a TTS voice in the Voice tab first");
      return;
    }
    const text = renderPersonaPreview(value);
    setLoading(true);
    try {
      const result = await previewTts({
        text,
        voiceId: voice.voiceId,
        shortName: voice.azureVoiceName,
        azureVoiceName: voice.azureVoiceName,
        speed: voice.speed,
        pitch: voice.pitch,
        warmth: voice.warmth,
        pauseMs: voice.pauseMs,
        style: voice.style,
      });
      const url = URL.createObjectURL(result.blob);
      urlRef.current = url;
      const audio = new Audio(url);
      audioRef.current = audio;
      audio.onended = () => setPlaying(false);
      await audio.play();
      setPlaying(true);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not speak preview");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_1fr]">
      <div className="flex flex-col gap-5">
        <div>
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-text-muted">Presets</div>
          <div className="flex flex-wrap gap-1.5">
            {presets.map((p) => (
              <button
                key={p.id}
                onClick={() => update({ traits: p.traits })}
                className="rounded-full border border-[var(--border-token)] px-2.5 py-1 text-[11.5px] text-text-secondary hover:border-brand-primary hover:text-brand-primary-dark"
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-4">
          {TRAITS.map((t) => (
            <div key={t.key}>
              <div className="mb-1 flex items-center justify-between text-[12px]">
                <span className="font-medium text-text-primary">{t.label}</span>
                <span className="font-mono text-[11px] text-text-secondary">{value.traits[t.key]}</span>
              </div>
              <Slider
                value={[value.traits[t.key]]}
                min={0}
                max={100}
                step={1}
                onValueChange={([v]) => setTrait(t.key, v)}
              />
              <div className="mt-0.5 flex justify-between text-[10px] text-text-muted">
                <span>{t.lo}</span>
                <span>{t.hi}</span>
              </div>
            </div>
          ))}
        </div>

        <div>
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-text-muted">Primary language</div>
          <select
            value={value.language}
            onChange={(e) => update({ language: e.target.value })}
            className="w-full rounded-md border border-[var(--border-token)] bg-surface-card px-2 py-1.5 text-[12.5px]"
          >
            {LANGUAGES.map((l) => (
              <option key={l}>{l}</option>
            ))}
          </select>
          <div className="mt-2 text-[11px] text-text-muted">Vernacular fallbacks</div>
          <div className="mt-1 flex flex-wrap gap-1">
            {LANGUAGES.filter((l) => l !== value.language).map((l) => {
              const on = value.fallbackLanguages.includes(l);
              return (
                <button
                  key={l}
                  onClick={() => toggleFallback(l)}
                  className={`rounded-full px-2 py-0.5 text-[11px] ${
                    on
                      ? "bg-brand-primary text-white"
                      : "border border-[var(--border-token)] bg-surface-card text-text-secondary hover:border-brand-primary"
                  }`}
                >
                  {l}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-[var(--border-token)] bg-surface-sunken p-4">
        <div className="mb-2 flex items-center justify-between">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-text-muted">Persona preview</div>
          <button
            type="button"
            onClick={() => void hearPreview()}
            disabled={loading}
            className="inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] bg-surface-card px-2 py-1 text-[11px] hover:bg-white disabled:opacity-50"
          >
            {playing || loading ? <Square className="h-3 w-3" /> : <Play className="h-3 w-3" />}
            {loading ? "Synthesizing…" : playing ? "Stop" : "Hear tone"}
          </button>
        </div>
        <div className="rounded-md border border-[var(--border-token)] bg-surface-card p-3 text-[13px] leading-relaxed text-text-primary">
          <span className="mr-2 rounded-full bg-brand-tint px-1.5 py-0.5 text-[10px] font-medium uppercase text-brand-primary-dark">
            bot
          </span>
          {renderPersonaPreview(value)}
        </div>
        <p className="mt-2 flex items-start gap-1.5 text-[11px] text-text-muted">
          <Volume2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          Spoken with the Voice tab’s TTS settings (warmth/pitch/speed). Adjust sliders, then Hear tone.
        </p>
      </div>
    </div>
  );
}
