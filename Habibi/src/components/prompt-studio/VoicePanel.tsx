import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  Copy,
  Play,
  Square,
  Volume2,
} from "lucide-react";
import { toast } from "sonner";

import { Dialog, DialogContent } from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import {
  fetchTtsVoiceDetail,
  fetchTtsVoiceWarning,
  previewTts,
  type TtsCatalogVoice,
} from "@/api/prompt-studio";
import { DEFAULT_VOICE, type VoiceConfig } from "@/data/prompt-studio-seed";
import { cn } from "@/lib/utils";
import {
  VoiceCatalogBrowser,
  tierBadge,
  useSelectedCatalogVoice,
} from "./VoiceCatalogBrowser";

type Props = {
  value: VoiceConfig;
  onChange: (next: VoiceConfig) => void;
};

const DEBOUNCE_MS = 450;
const DEMO_LINE = "Hello, this is a sample of how I sound on a collections call.";

function selectedShortName(cfg: VoiceConfig): string {
  return (
    (cfg.azureVoiceName || "").trim() ||
    (looksLikeShortName(cfg.voiceId) ? cfg.voiceId : "") ||
    DEFAULT_VOICE.azureVoiceName ||
    "en-IN-AartiNeural"
  );
}

function looksLikeShortName(value?: string | null): boolean {
  const v = (value || "").trim();
  if (!v || /\s/.test(v)) return false;
  return /^[a-z]{2,3}-[A-Z]{2}-.+/.test(v) || /Neural|DragonHD|HDFlash|Turbo|MAI-Voice/.test(v);
}

export function VoicePanel({ value, onChange }: Props) {
  const [detailVoice, setDetailVoice] = useState<TtsCatalogVoice | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(false);
  const [cardPreviewing, setCardPreviewing] = useState<string | null>(null);
  const [meta, setMeta] = useState<string | null>(null);
  const [loadedItems, setLoadedItems] = useState<TtsCatalogVoice[]>([]);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);
  const debounceRef = useRef<number | null>(null);
  const requestGen = useRef(0);
  const valueRef = useRef(value);
  valueRef.current = value;
  const livePreviewRef = useRef(false);

  const shortName = selectedShortName(value);
  const selectedVoice = useSelectedCatalogVoice(shortName, loadedItems);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const w = await fetchTtsVoiceWarning(shortName);
        if (!cancelled) setWarning(w?.message ?? null);
      } catch {
        if (!cancelled) setWarning(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [shortName]);

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
    setCardPreviewing(null);
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

  const selectVoice = (voice: TtsCatalogVoice) => {
    setLoadedItems((prev) =>
      prev.some((v) => v.shortName === voice.shortName) ? prev : [...prev, voice],
    );
    update({
      azureVoiceName: voice.shortName,
      // Store Azure ShortName as voiceId — deployments.tts_voice_id is ShortName text.
      voiceId: voice.shortName,
      style: voice.styles[0] ?? null,
    });
    if (livePreviewRef.current) scheduleLivePreview();
  };

  const playBlob = async (blob: Blob, label: string) => {
    stopPlayback();
    const url = URL.createObjectURL(blob);
    urlRef.current = url;
    const audio = new Audio(url);
    audioRef.current = audio;
    audio.onended = () => {
      setPlaying(false);
      setCardPreviewing(null);
      livePreviewRef.current = false;
    };
    audio.onerror = () => {
      toast.error("Couldn’t play synthesized audio");
      setPlaying(false);
      setCardPreviewing(null);
      livePreviewRef.current = false;
    };
    await audio.play();
    setPlaying(true);
    setMeta(label);
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
        shortName: selectedShortName(cfg),
        azureVoiceName: selectedShortName(cfg),
        voiceId: cfg.voiceId,
        speed: cfg.speed,
        pitch: cfg.pitch,
        warmth: cfg.warmth,
        pauseMs: cfg.pauseMs,
        style: cfg.style,
      });
      if (gen !== requestGen.current) return;
      const bits = [
        result.cacheHit ? "cache hit" : "live synthesize",
        result.voiceName,
        result.latencyMs != null ? `${result.latencyMs}ms` : null,
      ].filter(Boolean);
      livePreviewRef.current = true;
      await playBlob(result.blob, bits.join(" · "));
    } catch (err) {
      if (gen !== requestGen.current) return;
      livePreviewRef.current = false;
      toast.error(err instanceof Error ? err.message : "TTS preview failed");
    } finally {
      if (gen === requestGen.current) setLoading(false);
    }
  };

  const previewCard = async (voice: TtsCatalogVoice) => {
    const gen = ++requestGen.current;
    stopPlayback();
    setCardPreviewing(voice.shortName);
    setLoading(true);
    try {
      const result = await previewTts({
        text: DEMO_LINE,
        shortName: voice.shortName,
        azureVoiceName: voice.shortName,
        speed: 1,
        pitch: 0,
        warmth: 55,
        pauseMs: 280,
      });
      if (gen !== requestGen.current) return;
      await playBlob(
        result.blob,
        [voice.displayName, result.latencyMs != null ? `${result.latencyMs}ms` : null]
          .filter(Boolean)
          .join(" · "),
      );
    } catch (err) {
      if (gen !== requestGen.current) return;
      setCardPreviewing(null);
      toast.error(err instanceof Error ? err.message : "Preview failed");
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

  const openDetail = async (voice: TtsCatalogVoice) => {
    setDetailVoice(voice);
    try {
      const full = await fetchTtsVoiceDetail(voice.shortName);
      setDetailVoice(full);
    } catch {
      /* keep list row */
    }
  };

  const styles = selectedVoice?.styles ?? detailVoice?.styles ?? [];

  useEffect(() => {
    if (!styles.length) return;
    if (value.style && styles.includes(value.style)) return;
    update({ style: styles[0] });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- fires once per voice's style list
  }, [styles.join("|"), value.style]);

  return (
    <div className="flex flex-col gap-250">
      {warning ? (
        <div className="rounded-large border border-border-warning-subtle bg-background-warning-subtler px-150 py-100 text-body-small text-text-warning-bolder">
          {warning}
        </div>
      ) : null}

      <div className="grid gap-250 lg:grid-cols-[1.35fr_1fr]">
        <VoiceCatalogBrowser
          mode="full"
          value={shortName}
          onSelect={(voice) => {
            setLoadedItems((prev) => {
              const merged = [...prev];
              if (!merged.some((v) => v.shortName === voice.shortName)) merged.push(voice);
              return merged;
            });
            selectVoice(voice);
          }}
          onOpenDetail={(voice) => void openDetail(voice)}
          onPreview={(voice) => {
            if (playing && cardPreviewing === voice.shortName) {
              stopAll();
              return;
            }
            void previewCard(voice);
          }}
          previewingShortName={cardPreviewing}
          previewBusy={playing || loading}
          showSyncControls
        />

        <div className="flex flex-col gap-200 rounded-xlarge border border-border bg-surface p-200">
          <div>
            <div className="text-body-small font-semibold text-text-subtlest">
              Selected voice
            </div>
            <div className="mt-050 text-[1rem] font-semibold text-text">
              {selectedVoice?.displayName || shortName}
            </div>
            <div className="mt-025 flex flex-wrap items-center gap-100 text-body-small text-text-subtle">
              <code className="rounded bg-surface-sunken px-075 py-025 font-mono text-body-small">
                {shortName}
              </code>
              <button
                type="button"
                className="inline-flex items-center gap-050 text-text-subtlest hover:text-text"
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(shortName);
                    toast.success("ShortName copied");
                  } catch {
                    toast.error("Copy failed");
                  }
                }}
              >
                <Copy className="h-3 w-3" /> Copy
              </button>
              {selectedVoice ? (
                <span>
                  {selectedVoice.gender} · {selectedVoice.localeName || selectedVoice.locale}
                </span>
              ) : null}
            </div>
          </div>

          {styles.length > 0 ? (
            <div>
              <div className="mb-050 text-body-small font-semibold text-text-subtlest">
                Speaking style
              </div>
              <Select
                value={value.style || styles[0]}
                onValueChange={(s) => onSlider({ style: s })}
              >
                <SelectTrigger className="h-9 text-body-small">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {styles.map((s) => (
                    <SelectItem key={s} value={s} className="text-body-small">
                      {s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ) : (
            <p className="text-body-small text-text-subtlest">
              This voice has no Azure speaking styles — prosody uses speed / pitch / warmth only.
            </p>
          )}

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
              <div className="mb-050 flex items-center justify-between text-body-small">
                <span className="font-medium text-text">{s.label}</span>
                <span className="font-mono text-body-small text-text-subtle">
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
            <div className="mb-050 text-body-small font-semibold text-text-subtlest">
              Sample text
            </div>
            <textarea
              value={value.sampleText}
              onChange={(e) => update({ sampleText: e.target.value })}
              className="w-full resize-y rounded-medium border border-border bg-surface p-100 text-body-small"
              rows={2}
            />
          </div>

          <div className="flex items-center gap-150 rounded-medium border border-border bg-surface-sunken p-150">
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
              className="inline-flex items-center gap-075 rounded-medium bg-background-brand-bold px-150 py-075 text-body-small font-medium text-white hover:bg-background-brand-bold-pressed disabled:cursor-not-allowed disabled:opacity-50"
            >
              {playing || loading ? (
                <Square className="h-3.5 w-3.5" />
              ) : (
                <Play className="h-3.5 w-3.5" />
              )}
              {loading ? "Synthesizing…" : playing ? "Stop" : "Preview voice"}
            </button>
            <div className="flex-1">
              <Waveform active={playing || loading} />
            </div>
            <Volume2 className="h-4 w-4 text-text-subtlest" />
          </div>
          <p className="text-body-small text-text-subtlest">
            Preview uses Azure Speech neural TTS
            {meta ? ` · ${meta}` : ""}. Selection is saved as Azure ShortName into deployment tuning.
          </p>
        </div>
      </div>

      <Dialog open={!!detailVoice} onOpenChange={(o) => !o && setDetailVoice(null)}>
        <DialogContent className="max-w-md p-0 gap-0 overflow-hidden">
          {detailVoice ? (
            <VoiceDetailCard
              voice={detailVoice}
              onUse={() => {
                selectVoice(detailVoice);
                setDetailVoice(null);
              }}
              onPlay={() => void previewCard(detailVoice)}
              playing={cardPreviewing === detailVoice.shortName && playing}
            />
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}

/** Exported so the Sandbox's compact picker can show the same detail sheet. */
export function VoiceDetailCard({
  voice,
  onUse,
  onPlay,
  playing,
}: {
  voice: TtsCatalogVoice;
  onUse: () => void;
  onPlay: () => void;
  playing: boolean;
}) {
  const badge = tierBadge(voice);
  const [showRaw, setShowRaw] = useState(false);
  return (
    <div className="p-150">
      <div className="flex items-start justify-between gap-100">
        <div>
          <div className="text-[0.875rem] font-semibold text-text">{voice.displayName}</div>
          <div className="text-body-small text-text-subtlest">{voice.localName || voice.displayName}</div>
        </div>
        <span className={cn("rounded border px-075 py-025 text-body-small font-medium", badge.className)}>
          {badge.label}
        </span>
      </div>
      <div className="mt-100 space-y-075 text-body-small text-text-subtle">
        <Row
          label="ShortName"
          value={
            <code className="rounded bg-surface-sunken px-050 font-mono text-body-small">
              {voice.shortName}
            </code>
          }
        />
        <Row label="Language" value={`${voice.localeName || "—"} (${voice.locale})`} />
        <Row label="Gender" value={voice.gender} />
        <Row label="Status" value={`${voice.status} · ${voice.voiceType}`} />
        <Row
          label="Model"
          value={voice.modelSeries.length ? voice.modelSeries.join(", ") : "—"}
        />
        <Row
          label="Cost"
          value={
            voice.approxUsdPer1MChars != null
              ? `~$${voice.approxUsdPer1MChars} / 1M chars · approximate`
              : "See Azure pricing"
          }
        />
        {voice.styles.length ? <Row label="Styles" value={voice.styles.join(", ")} /> : null}
        {voice.personalities.length ? (
          <Row label="Personality" value={voice.personalities.join(", ")} />
        ) : null}
        {voice.scenarios.length ? (
          <Row label="Scenarios" value={voice.scenarios.join(", ")} />
        ) : null}
        <Row
          label="Audio"
          value={[
            voice.wordsPerMinute != null ? `${voice.wordsPerMinute} wpm` : null,
            voice.sampleRateHertz != null ? `${voice.sampleRateHertz} Hz` : null,
          ]
            .filter(Boolean)
            .join(" · ") || "—"}
        />
      </div>
      <div className="mt-150 flex gap-100">
        <button
          type="button"
          onClick={onPlay}
          className="inline-flex flex-1 items-center justify-center gap-075 rounded-medium border border-border px-100 py-075 text-body-small font-medium hover:bg-surface-sunken"
        >
          {playing ? <Square className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
          {playing ? "Stop" : "Play demo"}
        </button>
        <button
          type="button"
          onClick={onUse}
          className="inline-flex flex-1 items-center justify-center rounded-medium bg-background-brand-bold px-100 py-075 text-body-small font-medium text-white hover:bg-background-brand-bold-pressed"
        >
          Use this voice
        </button>
      </div>
      {voice.raw ? (
        <div className="mt-150 border-t border-border pt-100">
          <button
            type="button"
            className="text-body-small font-medium text-text-subtlest hover:text-text"
            onClick={() => setShowRaw((v) => !v)}
          >
            {showRaw ? "Hide technical" : "Show technical"}
          </button>
          {showRaw ? (
            <pre className="mt-050 max-h-40 overflow-auto rounded bg-surface-sunken p-100 text-body-small leading-relaxed text-text-subtle">
              {JSON.stringify(voice.raw, null, 2)}
            </pre>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="grid grid-cols-[88px_1fr] gap-100">
      <div className="text-text-subtlest">{label}</div>
      <div className="min-w-0 break-words">{value}</div>
    </div>
  );
}

function Waveform({ active }: { active: boolean }) {
  return (
    <div className="flex h-400 items-end gap-025">
      {Array.from({ length: 40 }).map((_, i) => {
        const h = 20 + ((i * 37) % 60);
        return (
          <div
            key={i}
            style={{
              height: `${h}%`,
              animationDelay: `${i * 40}ms`,
            }}
            className={`w-[0.1875rem] rounded-small bg-background-brand-bold/60 ${active ? "animate-pulse" : "opacity-40"}`}
          />
        );
      })}
    </div>
  );
}
