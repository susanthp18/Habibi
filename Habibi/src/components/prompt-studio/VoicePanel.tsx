import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  Check,
  Copy,
  Info,
  Loader2,
  Play,
  RefreshCw,
  Search,
  Square,
  Volume2,
} from "lucide-react";
import { toast } from "sonner";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import {
  fetchTtsVoiceDetail,
  fetchTtsVoiceWarning,
  previewTts,
  syncTtsVoiceCatalog,
  useTtsPricing,
  useTtsVoiceCatalog,
  type TtsCatalogVoice,
} from "@/api/prompt-studio";
import { DEFAULT_VOICE, type VoiceConfig } from "@/data/prompt-studio-seed";
import { cn } from "@/lib/utils";

type Props = {
  value: VoiceConfig;
  onChange: (next: VoiceConfig) => void;
};

const DEBOUNCE_MS = 450;
const DEMO_LINE = "Hello, this is a sample of how I sound on a collections call.";

const LOCALE_PRESETS: { value: string; label: string }[] = [
  { value: "all", label: "All locales" },
  { value: "en-IN", label: "English (India)" },
  { value: "hi-IN", label: "Hindi (India)" },
  { value: "en-", label: "English (all)" },
  { value: "hi-", label: "Hindi (all)" },
  { value: "ta-", label: "Tamil" },
  { value: "te-", label: "Telugu" },
  { value: "kn-", label: "Kannada" },
  { value: "mr-", label: "Marathi" },
  { value: "bn-", label: "Bengali" },
];

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

function relativeSynced(iso: string | null | undefined): string {
  if (!iso) return "Never synced";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "Synced";
  const mins = Math.max(0, Math.round((Date.now() - t) / 60_000));
  if (mins < 1) return "Synced just now";
  if (mins < 60) return `Synced ${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 48) return `Synced ${hrs}h ago`;
  return `Synced ${Math.round(hrs / 24)}d ago`;
}

function tierBadge(voice: TtsCatalogVoice): { label: string; className: string } {
  const tier = voice.priceTier || "standard";
  const usd = voice.approxUsdPer1MChars;
  const cost = usd != null ? ` · ~$${usd}/1M` : "";
  if (tier === "standard") {
    return {
      label: `Standard${cost}`,
      className: "border-emerald-200 bg-emerald-50 text-emerald-800",
    };
  }
  if (tier === "hd_flash") {
    return {
      label: `HD Flash${cost}`,
      className: "border-amber-200 bg-amber-50 text-amber-900",
    };
  }
  if (tier === "turbo") {
    return {
      label: `Turbo${cost}`,
      className: "border-rose-200 bg-rose-50 text-rose-900",
    };
  }
  return {
    label: `HD${cost}`,
    className: "border-orange-200 bg-orange-50 text-orange-900",
  };
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return name.slice(0, 2).toUpperCase() || "?";
}

export function VoicePanel({ value, onChange }: Props) {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [qDebounced, setQDebounced] = useState("");
  const [locale, setLocale] = useState("all");
  const [gender, setGender] = useState("all");
  const [showPremium, setShowPremium] = useState(false);
  const [status, setStatus] = useState("GA");
  const [detailVoice, setDetailVoice] = useState<TtsCatalogVoice | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(false);
  const [cardPreviewing, setCardPreviewing] = useState<string | null>(null);
  const [meta, setMeta] = useState<string | null>(null);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);
  const debounceRef = useRef<number | null>(null);
  const requestGen = useRef(0);
  const valueRef = useRef(value);
  valueRef.current = value;
  const livePreviewRef = useRef(false);

  useEffect(() => {
    const t = window.setTimeout(() => setQDebounced(q.trim()), 250);
    return () => window.clearTimeout(t);
  }, [q]);

  const catalogQuery = useTtsVoiceCatalog({
    q: qDebounced || undefined,
    locale: locale === "all" ? undefined : locale,
    gender: gender === "all" ? undefined : gender,
    status: status || "GA",
    includePremium: showPremium,
    limit: 80,
  });
  const pricingQuery = useTtsPricing();

  const shortName = selectedShortName(value);
  const items = catalogQuery.data?.items ?? [];
  const selectedInList = useMemo(
    () => items.find((v) => v.shortName === shortName) ?? null,
    [items, shortName],
  );

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

  const syncMutation = useMutation({
    mutationFn: syncTtsVoiceCatalog,
    onSuccess: (run) => {
      void qc.invalidateQueries({ queryKey: ["tts-voice-catalog"] });
      if (run.error) toast.error(`Sync failed: ${run.error}`);
      else toast.success(`Catalog refreshed · ${run.fetchedCount} voices`);
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : "Sync failed"),
  });

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
    update({
      azureVoiceName: voice.shortName,
      voiceId: looksLikeShortName(valueRef.current.voiceId)
        ? voice.shortName
        : valueRef.current.voiceId || "priya",
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

  const styles = selectedInList?.styles ?? detailVoice?.styles ?? [];
  const pricingHint =
    pricingQuery.data?.find((t) => t.tier === "standard")?.approxUsdPer1MChars ?? 15;

  return (
    <div className="flex flex-col gap-5">
      {/* Toolbar */}
      <div className="rounded-xl border border-[var(--border-token)] bg-surface-card p-3 shadow-sm">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[200px] flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-muted" />
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search voices, locales, ShortName…"
              className="h-9 pl-8 text-[12.5px]"
            />
          </div>
          <Select value={locale} onValueChange={setLocale}>
            <SelectTrigger className="h-9 w-[170px] text-[12px]">
              <SelectValue placeholder="Locale" />
            </SelectTrigger>
            <SelectContent>
              {LOCALE_PRESETS.map((o) => (
                <SelectItem key={o.value} value={o.value} className="text-[12px]">
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={gender} onValueChange={setGender}>
            <SelectTrigger className="h-9 w-[120px] text-[12px]">
              <SelectValue placeholder="Gender" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All genders</SelectItem>
              <SelectItem value="Female">Female</SelectItem>
              <SelectItem value="Male">Male</SelectItem>
              <SelectItem value="Neutral">Neutral</SelectItem>
            </SelectContent>
          </Select>
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="h-9 w-[110px] text-[12px]">
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="GA">GA</SelectItem>
              <SelectItem value="Preview">Preview</SelectItem>
            </SelectContent>
          </Select>
          <label className="inline-flex items-center gap-2 rounded-md border border-[var(--border-token)] bg-surface-sunken px-2.5 py-1.5 text-[11.5px] text-text-secondary">
            <Switch checked={showPremium} onCheckedChange={setShowPremium} />
            Show premium
          </label>
          <div className="ml-auto flex items-center gap-2 text-[11px] text-text-muted">
            <span>{relativeSynced(catalogQuery.data?.lastSyncedAt)}</span>
            <button
              type="button"
              disabled={syncMutation.isPending}
              onClick={() => syncMutation.mutate()}
              className="inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] bg-surface-card px-2 py-1 font-medium text-text-secondary hover:border-brand-primary hover:text-brand-primary-dark disabled:opacity-50"
            >
              {syncMutation.isPending ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <RefreshCw className="h-3 w-3" />
              )}
              Refresh
            </button>
          </div>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-text-muted">
          <span>
            {catalogQuery.isFetching ? "Loading…" : `${catalogQuery.data?.total ?? 0} voices`}
            {!showPremium ? " · premium hidden" : ""}
          </span>
          <span className="text-text-muted/70">
            Approx. Standard ~${pricingHint}/1M chars · verify on Azure Pricing
          </span>
        </div>
      </div>

      {warning ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-900">
          {warning}
        </div>
      ) : null}

      <div className="grid gap-5 lg:grid-cols-[1.35fr_1fr]">
        {/* Results */}
        <div className="min-h-[320px] rounded-xl border border-[var(--border-token)] bg-surface-card">
          <div className="flex items-center justify-between border-b border-[var(--border-token)] px-3 py-2">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-text-muted">
              Voice catalog
            </div>
            <div className="text-[11px] text-text-muted">Click ▶ to hear · ⓘ for details</div>
          </div>
          <ScrollArea className="h-[420px]">
            <div className="grid gap-2 p-2 sm:grid-cols-2">
              {catalogQuery.isLoading && !items.length ? (
                <div className="col-span-full flex items-center justify-center gap-2 py-16 text-[12px] text-text-muted">
                  <Loader2 className="h-4 w-4 animate-spin" /> Loading catalog…
                </div>
              ) : null}
              {!catalogQuery.isLoading && !items.length ? (
                <div className="col-span-full py-16 text-center text-[12px] text-text-muted">
                  No voices match these filters.
                </div>
              ) : null}
              {items.map((voice) => {
                const selected = voice.shortName === shortName;
                const badge = tierBadge(voice);
                return (
                  <div
                    key={voice.shortName}
                    className={cn(
                      "group relative rounded-lg border p-2.5 transition",
                      selected
                        ? "border-brand-primary bg-brand-tint/40 ring-1 ring-brand-primary/30"
                        : "border-[var(--border-token)] bg-surface-card hover:border-brand-primary/50 hover:bg-surface-sunken/40",
                    )}
                  >
                    <button
                      type="button"
                      onClick={() => selectVoice(voice)}
                      className="w-full text-left"
                    >
                      <div className="flex items-start gap-2.5">
                        <div
                          className={cn(
                            "grid h-9 w-9 shrink-0 place-items-center rounded-full text-[11px] font-semibold",
                            selected
                              ? "bg-brand-primary text-white"
                              : "bg-brand-primary/10 text-brand-primary-dark",
                          )}
                        >
                          {selected ? <Check className="h-4 w-4" /> : initials(voice.displayName)}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-1.5">
                            <div className="truncate text-[13px] font-semibold text-text-primary">
                              {voice.displayName}
                            </div>
                            {voice.isPremium ? (
                              <Badge
                                variant="outline"
                                className="h-4 px-1 text-[9px] font-semibold uppercase tracking-wide"
                              >
                                Premium
                              </Badge>
                            ) : null}
                          </div>
                          <div className="mt-0.5 truncate text-[10.5px] text-text-muted">
                            {voice.gender} · {voice.localeName || voice.locale}
                          </div>
                          <div className="mt-1.5 flex flex-wrap gap-1">
                            <span
                              className={cn(
                                "inline-flex rounded border px-1.5 py-0.5 text-[10px] font-medium",
                                badge.className,
                              )}
                            >
                              {badge.label}
                            </span>
                            {voice.styles.slice(0, 2).map((s) => (
                              <span
                                key={s}
                                className="rounded border border-[var(--border-token)] bg-surface-sunken px-1.5 py-0.5 text-[10px] text-text-secondary"
                              >
                                {s}
                              </span>
                            ))}
                          </div>
                        </div>
                      </div>
                    </button>
                    <div className="mt-2 flex items-center justify-end gap-1">
                      <button
                        type="button"
                        title="Voice details"
                        onClick={() => void openDetail(voice)}
                        className="inline-flex h-7 w-7 items-center justify-center rounded-md text-text-muted hover:bg-surface-sunken hover:text-text-primary"
                      >
                        <Info className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        title="Play demo"
                        disabled={loading && cardPreviewing === voice.shortName}
                        onClick={() => {
                          if (playing && cardPreviewing === voice.shortName) {
                            stopAll();
                            return;
                          }
                          void previewCard(voice);
                        }}
                        className="inline-flex h-7 items-center gap-1 rounded-md bg-brand-primary/10 px-2 text-[11px] font-medium text-brand-primary-dark hover:bg-brand-primary/20 disabled:opacity-50"
                      >
                        {cardPreviewing === voice.shortName && (playing || loading) ? (
                          <Square className="h-3 w-3" />
                        ) : (
                          <Play className="h-3 w-3" />
                        )}
                        Demo
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </ScrollArea>
        </div>

        {/* Selected strip + prosody */}
        <div className="flex flex-col gap-4 rounded-xl border border-[var(--border-token)] bg-surface-card p-4">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-text-muted">
              Selected voice
            </div>
            <div className="mt-1 text-[16px] font-semibold text-text-primary">
              {selectedInList?.displayName || shortName}
            </div>
            <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[11.5px] text-text-secondary">
              <code className="rounded bg-surface-sunken px-1.5 py-0.5 font-mono text-[11px]">
                {shortName}
              </code>
              <button
                type="button"
                className="inline-flex items-center gap-1 text-text-muted hover:text-text-primary"
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
              {selectedInList ? (
                <span>
                  {selectedInList.gender} · {selectedInList.localeName || selectedInList.locale}
                </span>
              ) : null}
            </div>
          </div>

          {styles.length > 0 ? (
            <div>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-text-muted">
                Speaking style
              </div>
              <Select
                value={value.style || styles[0]}
                onValueChange={(s) => onSlider({ style: s })}
              >
                <SelectTrigger className="h-9 text-[12px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {styles.map((s) => (
                    <SelectItem key={s} value={s} className="text-[12px]">
                      {s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ) : (
            <p className="text-[11px] text-text-muted">
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
            <Volume2 className="h-4 w-4 text-text-muted" />
          </div>
          <p className="text-[11px] text-text-muted">
            Preview uses Azure Speech neural TTS
            {meta ? ` · ${meta}` : ""}. Selection is saved as Azure ShortName into deployment tuning.
          </p>
        </div>
      </div>

      {/* Detail dialog */}
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

function VoiceDetailCard({
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
    <div className="p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-[15px] font-semibold text-text-primary">{voice.displayName}</div>
          <div className="text-[11px] text-text-muted">{voice.localName || voice.displayName}</div>
        </div>
        <span className={cn("rounded border px-1.5 py-0.5 text-[10px] font-medium", badge.className)}>
          {badge.label}
        </span>
      </div>
      <div className="mt-2 space-y-1.5 text-[11.5px] text-text-secondary">
        <Row
          label="ShortName"
          value={
            <code className="rounded bg-surface-sunken px-1 font-mono text-[11px]">
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
              : "See Azure Pricing"
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
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          onClick={onPlay}
          className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md border border-[var(--border-token)] px-2 py-1.5 text-[12px] font-medium hover:bg-surface-sunken"
        >
          {playing ? <Square className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
          {playing ? "Stop" : "Play demo"}
        </button>
        <button
          type="button"
          onClick={onUse}
          className="inline-flex flex-1 items-center justify-center rounded-md bg-brand-primary px-2 py-1.5 text-[12px] font-medium text-white hover:bg-brand-primary-dark"
        >
          Use this voice
        </button>
      </div>
      {voice.raw ? (
        <div className="mt-3 border-t border-[var(--border-token)] pt-2">
          <button
            type="button"
            className="text-[11px] font-medium text-text-muted hover:text-text-primary"
            onClick={() => setShowRaw((v) => !v)}
          >
            {showRaw ? "Hide technical" : "Show technical"}
          </button>
          {showRaw ? (
            <pre className="mt-1 max-h-40 overflow-auto rounded bg-surface-sunken p-2 text-[10px] leading-relaxed text-text-secondary">
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
    <div className="grid grid-cols-[88px_1fr] gap-2">
      <div className="text-text-muted">{label}</div>
      <div className="min-w-0 break-words">{value}</div>
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
