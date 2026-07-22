import { useEffect, useRef, useState } from "react";
import { Play, Square, Volume2 } from "lucide-react";
import { Slider } from "@/components/ui/slider";
import { TTS_VOICES, type VoiceConfig } from "@/data/prompt-studio-seed";

type Props = {
  value: VoiceConfig;
  onChange: (next: VoiceConfig) => void;
};

export function VoicePanel({ value, onChange }: Props) {
  const [playing, setPlaying] = useState(false);
  const ctxRef = useRef<AudioContext | null>(null);
  const stopRef = useRef<() => void>(() => {});

  useEffect(() => () => stopRef.current(), []);

  const update = (patch: Partial<VoiceConfig>) => onChange({ ...value, ...patch });

  const play = async () => {
    stopRef.current();
    const AC = window.AudioContext || (window as any).webkitAudioContext;
    if (!AC) return;
    const ctx = new AC();
    ctxRef.current = ctx;
    if (ctx.state === "suspended") await ctx.resume().catch(() => {});

    const voiceMap: Record<string, number> = {
      priya: 240,
      anjali: 260,
      neha: 220,
      ravi: 130,
      arjun: 150,
      kabir: 120,
    };
    const base = voiceMap[value.voiceId] ?? 220;
    const pitchFactor = Math.pow(2, value.pitch / 12);
    const gainMax = 0.05 + (value.warmth / 100) * 0.15;
    const wordDur = 0.32 / Math.max(0.5, value.speed);
    const pauseDur = value.pauseMs / 1000;
    const words = value.sampleText.split(/\s+/).slice(0, 12);

    const gain = ctx.createGain();
    gain.gain.value = 0;
    gain.connect(ctx.destination);

    let t = ctx.currentTime + 0.05;
    const stops: OscillatorNode[] = [];
    words.forEach((w, i) => {
      const osc = ctx.createOscillator();
      const wobble = 1 + ((w.charCodeAt(0) % 7) - 3) * 0.02;
      osc.frequency.setValueAtTime(base * pitchFactor * wobble, t);
      osc.type = value.warmth > 55 ? "sine" : "triangle";
      osc.connect(gain);
      gain.gain.setValueAtTime(0.001, t);
      gain.gain.exponentialRampToValueAtTime(gainMax, t + 0.03);
      gain.gain.exponentialRampToValueAtTime(0.001, t + wordDur - 0.03);
      osc.start(t);
      osc.stop(t + wordDur);
      stops.push(osc);
      t += wordDur + (i % 4 === 3 ? pauseDur : 0.05);
    });

    setPlaying(true);
    const total = (t - ctx.currentTime) * 1000;
    const to = window.setTimeout(() => {
      setPlaying(false);
      ctx.close().catch(() => {});
    }, total);
    stopRef.current = () => {
      window.clearTimeout(to);
      stops.forEach((s) => {
        try {
          s.stop();
        } catch {}
      });
      ctx.close().catch(() => {});
      setPlaying(false);
    };
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_1fr]">
      <div>
        <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-text-muted">Voice</div>
        <div className="grid grid-cols-2 gap-2">
          {TTS_VOICES.map((v) => {
            const selected = v.id === value.voiceId;
            return (
              <button
                key={v.id}
                onClick={() => update({ voiceId: v.id })}
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
                    <div className="text-[10.5px] text-text-muted">{v.gender} · {v.accent}</div>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex flex-col gap-4">
        {[
          { key: "speed", label: "Speed", min: 0.5, max: 1.5, step: 0.05, format: (n: number) => `${n.toFixed(2)}×` },
          { key: "pitch", label: "Pitch", min: -6, max: 6, step: 1, format: (n: number) => `${n > 0 ? "+" : ""}${n}` },
          { key: "warmth", label: "Warmth", min: 0, max: 100, step: 1, format: (n: number) => `${n}` },
          { key: "pauseMs", label: "Pause between sentences", min: 100, max: 800, step: 20, format: (n: number) => `${n}ms` },
        ].map((s) => (
          <div key={s.key}>
            <div className="mb-1 flex items-center justify-between text-[12px]">
              <span className="font-medium text-text-primary">{s.label}</span>
              <span className="font-mono text-[11px] text-text-secondary">
                {s.format((value as any)[s.key])}
              </span>
            </div>
            <Slider
              value={[(value as any)[s.key]]}
              min={s.min}
              max={s.max}
              step={s.step}
              onValueChange={([v]) => update({ [s.key]: v } as any)}
            />
          </div>
        ))}

        <div>
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-text-muted">Sample text</div>
          <textarea
            value={value.sampleText}
            onChange={(e) => update({ sampleText: e.target.value })}
            className="w-full resize-y rounded-md border border-[var(--border-token)] bg-surface-card p-2 text-[12.5px]"
            rows={2}
          />
        </div>

        <div className="flex items-center gap-3 rounded-md border border-[var(--border-token)] bg-surface-sunken p-3">
          <button
            onClick={playing ? stopRef.current : play}
            className="inline-flex items-center gap-1.5 rounded-md bg-brand-primary px-3 py-1.5 text-[12px] font-medium text-white hover:bg-brand-primary-dark"
          >
            {playing ? <Square className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
            {playing ? "Stop" : "Preview voice"}
          </button>
          <div className="flex-1">
            <Waveform active={playing} />
          </div>
          <Volume2 className="h-4 w-4 text-text-muted" />
        </div>
        <p className="text-[11px] text-text-muted">
          Preview uses a local synth stand-in — production TTS runs through Lovable AI on publish.
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
