import { useEffect, useRef, useState } from "react";
import { Play, Square, Volume2 } from "lucide-react";
import { toast } from "sonner";
import { Slider } from "@/components/ui/slider";
import { previewTts } from "@/api/prompt-studio";
import { TTS_VOICES, type TtsVoice, type VoiceConfig } from "@/data/prompt-studio-seed";

type Props = {
  value: VoiceConfig;
  onChange: (next: VoiceConfig) => void;
  voices?: TtsVoice[];
};

const DEBOUNCE_MS = 450;

export function VoicePanel({ value, onChange, voices = TTS_VOICES }: Props) {
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(false);
  const [meta, setMeta] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);
  const debounceRef = useRef<number | null>(null);
  const requestGen = useRef(0);
  const valueRef = useRef(value);
  valueRef.current = value;
  /** When true, slider nudges re-preview (debounced) instead of every pixel. */
  const livePreviewRef = useRef(false);

  const stopPlayback = () => {
    const a = audioRef.current;
    if (a) {
      a.onended = null;
      a.onerror = null;
      a.pause();
      a.removeAttribute("src");
      a.load();
      audioRef.current = null;
    }
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    }
    setPlaying(false);
  };

  const stopAll = () => {
    if (debounceRef.current) {
      window.clearTimeout(debounceRef.current);
      debounceRef.current = null;
    }
    requestGen.current += 1;
    stopPlayback();
    setLoading(false);
    livePreviewRef.current = false;
  };

  useEffect(() => () => stopAll(), []);

  const update = (patch: Partial<VoiceConfig>) => {
    const next = { ...valueRef.current, ...patch };
    valueRef.current = next;
    onChange(next);
  };

  const runPreview = async () => {
    const gen = ++requestGen.current;
    if (debounceRef.current) {
      window.clearTimeout(debounceRef.current);
      debounceRef.current = null;
    }
    stopPlayback();
    setLoading(true);
    setMeta(null);
    const cfg = valueRef.current;
    try {
      const result = await previewTts({
        text: cfg.sampleText,
        voiceId: cfg.voiceId,
        speed: cfg.speed,
        pitch: cfg.pitch,
        warmth: cfg.warmth,
        pauseMs: cfg.pauseMs,
      });
      if (gen !== requestGen.current) return;

      const url = URL.createObjectURL(result.blob);
      urlRef.current = url;
      const audio = new Audio(url);
      audioRef.current = audio;
      audio.onended = () => {
        setPlaying(false);
        livePreviewRef.current = false;
      };
      audio.onerror = () => {
        toast.error("Couldn’t play synthesized audio");
        setPlaying(false);
        livePreviewRef.current = false;
      };
      await audio.play();
      setPlaying(true);
      livePreviewRef.current = true;
      const bits = [
        result.cacheHit ? "cache hit" : "live synthesize",
        result.voiceName,
        result.latencyMs != null ? `${result.latencyMs}ms` : null,
      ].filter(Boolean);
      setMeta(bits.join(" · "));
    } catch (err) {
      if (gen !== requestGen.current) return;
      livePreviewRef.current = false;
      toast.error(err instanceof Error ? err.message : "TTS preview failed");
    } finally {
      if (gen === requestGen.current) setLoading(false);
    }
  };

  const scheduleLivePreview = () => {
    if (!livePreviewRef.current) return;
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      debounceRef.current = null;
      void runPreview();
    }, DEBOUNCE_MS);
  };

  const onSlider = (patch: Partial<VoiceConfig>) => {
    update(patch);
    scheduleLivePreview();
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_1fr]">
      <div>
        <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-text-muted">
          Voice
        </div>
        <div className="grid grid-cols-2 gap-2">
          {voices.map((v) => {
            const selected = v.id === value.voiceId;
            return (
              <button
                key={v.id}
                type="button"
                onClick={() => {
                  update({ voiceId: v.id });
                  if (livePreviewRef.current) scheduleLivePreview();
                }}
                className={`rounded-md border p-2.5 text-left text-[12px] transition ${
                  selected
                    ? "border-brand-primary bg-brand-tint/50"
                    : "border-[var(--border-token)] bg-surface-card hover:border-brand-primary"
                }`}
              >
                <div className="flex items-center gap-2">
                  <div className="grid h-8 w-8 place-items-center rounded-full bg-brand-primary/10 text-[11px] font-semibold text-brand-primary-dark">
                    {v.name.slice(0, 2).toUpperCase()}
                  </div>
                  <div>
                    <div className="font-medium text-text-primary">{v.name}</div>
                    <div className="text-[10.5px] text-text-muted">
                      {v.gender} · {v.accent}
                    </div>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex flex-col gap-4">
        {[
          {
            key: "speed" as const,
            label: "Speed",
            min: 0.5,
            max: 1.5,
            step: 0.05,
            format: (n: number) => `${n.toFixed(2)}×`,
          },
          {
            key: "pitch" as const,
            label: "Pitch",
            min: -6,
            max: 6,
            step: 1,
            format: (n: number) => `${n > 0 ? "+" : ""}${n}`,
          },
          {
            key: "warmth" as const,
            label: "Warmth (timbre)",
            min: 0,
            max: 100,
            step: 1,
            format: (n: number) => `${n}`,
          },
          {
            key: "pauseMs" as const,
            label: "Pause between sentences",
            min: 100,
            max: 800,
            step: 20,
            format: (n: number) => `${n}ms`,
          },
        ].map((s) => (
          <div key={s.key}>
            <div className="mb-1 flex items-center justify-between text-[12px]">
              <span className="font-medium text-text-primary">{s.label}</span>
              <span className="font-mono text-[11px] text-text-secondary">
                {s.format(value[s.key])}
              </span>
            </div>
            <Slider
              value={[value[s.key]]}
              min={s.min}
              max={s.max}
              step={s.step}
              onValueChange={([v]) => onSlider({ [s.key]: v } as Partial<VoiceConfig>)}
            />
          </div>
        ))}

        <div>
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-text-muted">
            Sample text
          </div>
          <textarea
            value={value.sampleText}
            onChange={(e) => update({ sampleText: e.target.value })}
            className="w-full resize-y rounded-md border border-[var(--border-token)] bg-surface-card p-2 text-[12.5px]"
            rows={2}
          />
        </div>

        <div className="flex items-center gap-3 rounded-md border border-[var(--border-token)] bg-surface-sunken p-3">
          <button
            type="button"
            disabled={loading || !value.sampleText.trim()}
            onClick={() => {
              if (playing || loading) {
                stopAll();
                return;
              }
              void runPreview();
            }}
            className="inline-flex items-center gap-1.5 rounded-md bg-brand-primary px-3 py-1.5 text-[12px] font-medium text-white hover:bg-brand-primary-dark disabled:cursor-not-allowed disabled:opacity-50"
          >
            {playing || loading ? <Square className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
            {loading ? "Synthesizing…" : playing ? "Stop" : "Preview voice"}
          </button>
          <div className="flex-1">
            <Waveform active={playing || loading} />
          </div>
          <Volume2 className="h-4 w-4 text-text-muted" />
        </div>
        <p className="text-[11px] text-text-muted">
          Preview uses Azure Speech neural TTS
          {meta ? ` · ${meta}` : ""}. Warmth biases pitch/rate/volume (and speaking style when the
          voice supports it) — not volume alone. Slider nudges while playing are debounced; identical
          params hit the server cache.
        </p>
      </div>
    </div>
  );
}

function Waveform({ active }: { active: boolean }) {
  return (
    <div className="flex h-8 items-end gap-[2px]">
      {Array.from({ length: 40 }).map((_, i) => {
        const h = 20 + ((i * 37) % 60);
        return (
          <div
            key={i}
            style={{
              height: `${h}%`,
              animationDelay: `${i * 40}ms`,
            }}
            className={`w-[3px] rounded-sm bg-brand-primary/60 ${active ? "animate-pulse" : "opacity-40"}`}
          />
        );
      })}
    </div>
  );
}
