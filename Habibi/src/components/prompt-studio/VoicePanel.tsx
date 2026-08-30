import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, Copy, Play, RefreshCw, Square, Volume2 } from "lucide-react";
import { toast } from "sonner";

import { Dialog, DialogContent } from "@/components/ui/dialog";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Lozenge } from "@/components/ui/lozenge";
import {
  fetchTtsVoiceDetail,
  fetchTtsVoiceWarning,
  previewTts,
  type TtsCatalogVoice,
} from "@/api/prompt-studio";
import { DEFAULT_VOICE, type VoiceConfig, type VoiceParamValue } from "@/data/prompt-studio-seed";
import { cn } from "@/lib/utils";
import { useProviderModels, type ProviderModel } from "@/api/providers";
import { VoiceCatalogBrowser, tierBadge, useSelectedCatalogVoice } from "./VoiceCatalogBrowser";
import { VoiceParamsPanel } from "./VoiceParamsPanel";

type Props = {
  value: VoiceConfig;
  onChange: (next: VoiceConfig) => void;
  /**
   * Every BCP-47 tag the card's persona claims — primary language first, then
   * the vernacular fallbacks. The first opens the catalog filter, so the list
   * does not start at af-ZA; the whole set is what the locale guard judges
   * against, because a Hindi voice on an English card with a Hindi fallback is
   * authored rather than accidental.
   */
  cardLocales?: string[];
};

const DEBOUNCE_MS = 450;
const DEMO_LINE = "Hello, this is a sample of how I sound on a collections call.";

/** Stable identity for the un-authored case: a fresh `{}` each render would
 *  invalidate `effectiveParams` on every render, which is what it exists to
 *  avoid. */
const EMPTY_PARAMS: Record<string, VoiceParamValue> = Object.freeze({});

/** Same reason as EMPTY_PARAMS: a default `[]` literal is a new array a render. */
const EMPTY_LOCALES: string[] = [];

/**
 * `en-IN` and `en` are the same language to the locale guard.
 *
 * Only Azure publishes region-qualified locales. Every other provider the
 * registry syncs carries a bare language code — Fish's Arabic rows are `ar`,
 * not `ar-EG` — so comparing whole tags would warn on every non-Azure English
 * voice a card legitimately uses, and a warning that fires on the correct case
 * is one an operator learns to click past. Mirrors `_primary_subtag` in
 * `agent_core/cards/compile.py`, which is what G15 compares with server-side.
 */
function primarySubtag(tag: string): string {
  return (tag || "").trim().replace(/_/g, "-").split("-")[0].toLowerCase();
}

/** Narrow a control's value to what `VoiceConfig.params` may carry. The schema
 *  declares only number / enum / bool controls, so anything else is a provider
 *  row we do not understand and must not persist. */
function asParamValue(raw: unknown): VoiceParamValue | undefined {
  return typeof raw === "string" || typeof raw === "number" || typeof raw === "boolean"
    ? raw
    : undefined;
}

/**
 * Where the operator left the split, remembered across sessions.
 *
 * v4 of react-resizable-panels dropped `autoSaveId`, so persistence is explicit:
 * `defaultLayout` in, `onLayoutChanged` out, keyed on the panel ids.
 */
const LAYOUT_KEY = "voice-studio-panes";
const CATALOG_MIN = 30;
const INSPECTOR_MIN = 24;

/**
 * A stored layout is only honoured if it is one the panels would accept today.
 *
 * Learned the hard way: a transient layout bug persisted `{catalog: 95.4,
 * inspector: 4.6}`, and because it was read back on every mount the pane stayed
 * a 60px sliver long after the bug was fixed — a corrupt cache that outlives its
 * cause and cannot be cleared from inside the UI. Validating on read means the
 * worst case is falling back to the defaults, which are always usable.
 */
function readLayout(): Record<string, number> | undefined {
  try {
    const raw = window.localStorage.getItem(LAYOUT_KEY);
    if (!raw) return undefined;
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return undefined;
    const { catalog, inspector } = parsed as Record<string, unknown>;
    if (typeof catalog !== "number" || typeof inspector !== "number") return undefined;
    if (catalog < CATALOG_MIN || inspector < INSPECTOR_MIN) return undefined;
    if (Math.abs(catalog + inspector - 100) > 1) return undefined;
    return { catalog, inspector };
  } catch {
    return undefined;
  }
}

function selectedShortName(cfg: VoiceConfig): string {
  return (
    (cfg.azureVoiceName || "").trim() ||
    (looksLikeShortName(cfg.voiceId) ? cfg.voiceId : "") ||
    DEFAULT_VOICE.azureVoiceName ||
    "en-IN-AartiNeural"
  );
}

/**
 * Which vendor owns this id, from the id alone.
 *
 * The multi-provider sync namespaces every non-Azure short_name as
 * `{provider}:{ref}`; rows written before the registry have no prefix and are
 * Azure by construction. Same rule `provider_tts.voice_row` applies server-side,
 * so the two cannot disagree about who is about to speak.
 */
function providerFromShortName(shortName: string): string {
  const idx = shortName.indexOf(":");
  return idx > 0 ? shortName.slice(0, idx) : "azure";
}

/**
 * Model params that also have a dedicated `VoiceConfig` column.
 *
 * Azure's four controls are named the same as fields this type has carried
 * since before the registry existed, and both are folded into `AgentTuning.tts`
 * at save. Writing only the generic bag would leave `speed`/`pitch`/`warmth`/
 * `pauseMs` behind, and those are what the SSML preview and
 * `apply_voice_config_overlay` read; writing only the columns would lose every
 * other provider's controls. So these four write both, and the rest write the
 * bag. `tts_settings_kwargs` resolves the overlap in one direction — the
 * columns win — so the two cannot disagree at runtime.
 */
const PARAM_RATE = "rate";
const PARAM_PITCH = "pitch";
const PARAM_WARMTH = "warmth";
const PARAM_PAUSE_MS = "pause_ms";

/**
 * Does this id name a catalog voice, rather than a legacy `tts_voices` row?
 *
 * The two patterns below describe Azure short names — `en-IN-AartiNeural` and
 * the model-suffix families. Every non-Azure voice the multi-provider sync
 * writes is namespaced `{provider}:{ref}` (`fish:s2.1-pro`), which matches
 * neither — so a row whose `azureVoiceName` was empty and whose `voiceId` held
 * a perfectly good Fish id was judged "not a short name" and silently resolved
 * to the hardcoded `en-IN-AartiNeural`: a different vendor, a different
 * language, with nothing on screen saying so.
 *
 * `providerFromShortName` directly above already knows this shape. Both rules
 * now agree about what an id looks like.
 */
function looksLikeShortName(value?: string | null): boolean {
  const v = (value || "").trim();
  if (!v || /\s/.test(v)) return false;
  if (/^[a-z0-9_]+:.+/.test(v)) return true;
  return /^[a-z]{2,3}-[A-Z]{2}-.+/.test(v) || /Neural|DragonHD|HDFlash|Turbo|MAI-Voice/.test(v);
}

export function VoicePanel({ value, onChange, cardLocales = EMPTY_LOCALES }: Props) {
  const [detailVoice, setDetailVoice] = useState<TtsCatalogVoice | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(false);
  const [cardPreviewing, setCardPreviewing] = useState<string | null>(null);
  const [meta, setMeta] = useState<string | null>(null);
  const [loadedItems, setLoadedItems] = useState<TtsCatalogVoice[]>([]);

  // Read once on mount: re-reading on every render would fight the drag.
  const [savedLayout] = useState(readLayout);
  // Only a deliberate drag is worth remembering. Every other source — mount,
  // constraint recompute, a container resize — reports a layout too, and
  // storing those is how a momentary bad measurement becomes a permanent
  // preference.
  const persistLayout = (layout: Record<string, number>, meta: { isUserInteraction: boolean }) => {
    if (!meta.isUserInteraction) return;
    try {
      window.localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout));
    } catch {
      /* private mode — the split still drags, it just won't be remembered */
    }
  };

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);
  const debounceRef = useRef<number | null>(null);
  const requestGen = useRef(0);
  const valueRef = useRef(value);
  valueRef.current = value;
  // runPreview is called from a debounced timer, so it must read the latest
  // params rather than the ones captured when the timer was scheduled.
  const modelParamsRef = useRef<Record<string, unknown>>({});
  const livePreviewRef = useRef(false);

  const shortName = selectedShortName(value);
  const { voice: selectedVoice, resolution } = useSelectedCatalogVoice(shortName, loadedItems);

  /**
   * The voice speaks a language the card does not claim.
   *
   * The bug this exists for: a kaia draft stored an Arabic Fish voice while the
   * persona said English. This panel rendered it as Selected — correctly, it is
   * what the draft holds — the compiler passed every gate, and Publish was
   * enabled. Nothing in the product joined the two facts. The server says the
   * same thing as G15 `voice_locale`; saying it here too is what stops an
   * operator from only learning it in the publish dialog.
   */
  const localeMismatch = useMemo(() => {
    const spoken = (selectedVoice?.locale || "").trim();
    if (!spoken || cardLocales.length === 0) return null;
    if (cardLocales.some((tag) => primarySubtag(tag) === primarySubtag(spoken))) return null;
    return { spoken, card: cardLocales.join(", ") };
  }, [selectedVoice?.locale, cardLocales]);

  // Which model's controls to render. Resolved from the voice's provider, not
  // from the voice itself: capability belongs to the model, and every voice a
  // provider ships is driven by the same one.
  const ttsModelsQuery = useProviderModels("tts");
  const selectedModel: ProviderModel | null = (() => {
    // The catalog row is authoritative, but it arrives a request later than the
    // voice id does. This used to fall back to "azure" in that window, so a
    // Deepgram voice rendered Azure's identity, Azure's controls and no "new
    // take" button for a moment before correcting itself — the same untruth as
    // the hardcoded Azure strings this panel already had removed.
    //
    // The id carries the answer: the multi-provider sync namespaces every
    // non-Azure short_name as "{provider}:{ref}", and legacy un-prefixed rows
    // are Azure by construction. That is the rule the backend resolves with too.
    const provider = selectedVoice?.providerId || providerFromShortName(shortName);
    const models = ttsModelsQuery.data ?? [];
    return models.find((m) => m.providerId === provider) ?? null;
  })();

  // Values for the model-declared controls, read straight off the edited
  // version rather than held beside it.
  //
  // This was `useState`, and the state was the whole bug: a control that lives
  // only in a component cannot mark the editor dirty, cannot autosave, cannot
  // survive the tab being unmounted, and cannot be published. It is on
  // `VoiceConfig` now, which gets all four for free — and removes the class of
  // divergence where the panel shows one thing and the saved version holds
  // another, because there is no longer a second copy to diverge.
  const modelParams = value.params ?? EMPTY_PARAMS;
  const setModelParams = (next: Record<string, VoiceParamValue>) => update({ params: next });

  /**
   * What the panel is *showing*, which is what has to go on the wire.
   *
   * `modelParams` holds only what the operator has touched plus whatever the
   * seeding effect below has managed to write. The controls themselves render
   * `values[key] ?? spec.default`, so a panel that has not been seeded yet
   * displays temperature 0.7 while sending no temperature at all.
   *
   * That divergence stopped being cosmetic the moment previews were cached on
   * their params: `{}` and `{temperature: 0.7}` are different cache keys, so
   * the same voice at the same visible settings came back as a *different
   * take* depending on whether the catalog row had landed yet — measured, on a
   * tab switch. That is the "sounds different every time" this cache exists to
   * end, reintroduced one layer up.
   *
   * Reading the defaults back out of the schema makes the request describe the
   * screen by construction, whatever the seeding has or has not done yet. It
   * also drops keys belonging to a provider that is no longer selected.
   *
   * This is the *preview* payload specifically, and it is deliberately not what
   * gets saved. Persisting a default the operator never chose would mark a
   * freshly opened card dirty; leaving it out means an untouched control falls
   * through to the provider's own default on a real call, which is the same
   * value by a shorter route.
   */
  const effectiveParams = useMemo(() => {
    const out: Record<string, unknown> = {};
    for (const spec of (selectedModel?.paramsSchema ?? []) as Array<Record<string, unknown>>) {
      // Markers are sample text, not settings — they travel in the line itself.
      if (spec.kind === "tag_palette") continue;
      const v = modelParams[String(spec.key)] ?? spec.default;
      if (v !== undefined) out[String(spec.key)] = v;
    }
    return out;
  }, [selectedModel, modelParams]);
  modelParamsRef.current = effectiveParams;

  // Resolved the same way `selectedModel` is, and for the same reason: keyed on
  // the catalog row alone this read "azure" for a Fish voice until the row
  // arrived, so a provider change reset the controls a beat after the controls
  // themselves had already switched.
  const providerKey = selectedVoice?.providerId || providerFromShortName(shortName);
  const lastProviderRef = useRef(providerKey);
  useEffect(() => {
    // Guarded on a *change*, and the ref is seeded with the current provider so
    // this cannot fire on mount. That matters more now that it writes to the
    // version: seeding defaults on mount would mark a card dirty that nobody
    // touched, and every visit to the Voice tab would offer to save.
    if (lastProviderRef.current === providerKey) return;
    lastProviderRef.current = providerKey;
    const defaults: Record<string, VoiceParamValue> = {};
    for (const spec of (selectedModel?.paramsSchema ?? []) as Array<Record<string, unknown>>) {
      if (spec.kind === "tag_palette") continue;
      const v = asParamValue(spec.default);
      if (v !== undefined) defaults[String(spec.key)] = v;
    }
    // Replace, never merge. `apply_voice_config_overlay` replaces for the same
    // reason: the panel shows one model's controls, so a key that is no longer
    // on screen is one the operator can neither see nor clear, and leaving it
    // bound would ship a Fish temperature on an Azure voice.
    setModelParams(defaults);
    // `setModelParams` is intentionally absent: it closes over `update`, which
    // is rebuilt every render, so depending on it would re-seed continuously.
  }, [providerKey, selectedModel]);

  useEffect(() => {
    // The preview note describes a take of the *previous* voice, so it has to
    // go the moment the selection changes. Leaving it made the footer read
    // "Azure Neural TTS · same take" for a voice that had never been played —
    // an accurate provider next to a stale verdict, which is worse than either
    // alone because the sentence looks whole.
    setMeta(null);
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

  /** @param label Footer provenance, or null when what played is not the
   *  selected voice and the footer would therefore be describing something
   *  other than what it names. */
  const playBlob = async (blob: Blob, label: string | null) => {
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

  /**
   * @param fresh Take a new sample rather than replaying the stored one.
   *
   * Off for everything automatic — the debounced slider preview included. A
   * param change already produces a different cache key, so tuning still
   * re-synthesises; but dragging a slider back to where it was replays the
   * exact take you heard there, which is what makes comparing two settings a
   * comparison rather than two unrelated samples.
   */
  const runPreview = async (fresh = false) => {
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
        params: modelParamsRef.current,
        fresh,
      });
      if (gen !== requestGen.current) return;
      const bits = [
        // Named for what it means to the operator, not for the mechanism: the
        // question this answers is "am I hearing the same performance as last
        // time?", and "cache hit" does not answer it.
        //
        // The voice id used to be in here too and is not any more — the panel
        // header two bands up already shows it, and in a pinned one-line footer
        // the repeat pushed the latency off the end.
        result.cacheHit ? "same take" : fresh ? "new take" : "synthesized",
        result.latencyMs ? `${result.latencyMs}ms` : null,
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
      // The inspector footer is provenance for the *selected* voice, and a
      // catalog demo is some other voice at neutral settings on a different
      // line. Writing the demo there produced "Fish Audio · Fish S2.1 Pro ·
      // Adri · 2569ms" — Adri being an Azure voice, credited to Fish, next to
      // a latency for audio the selected voice never produced.
      //
      // Cleared rather than left alone: once you have listened to something
      // else, the previous note no longer describes what you last heard. The
      // row's own stop button is the feedback a demo needs.
      await playBlob(result.blob, null);
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

  /**
   * A stored style this voice does not offer is reported, not rewritten.
   *
   * This used to call `update({ style: styles[0] })`, which marks the editor
   * dirty and autosaves — so merely OPENING the Voice tab on a legacy draft
   * silently changed what the bot sounds like and wrote it to the server, with
   * no operator action and nothing on screen to undo. A tab that edits the
   * document by being looked at is not a viewer.
   *
   * The runtime already falls back safely; the author picks the replacement.
   */
  const styleUnavailable = Boolean(styles.length && value.style && !styles.includes(value.style));

  return (
    <div className="flex h-full min-h-0 flex-col gap-150">
      {warning ? (
        <div className="shrink-0 rounded-large border border-border-warning-subtle bg-background-warning-subtler px-150 py-100 text-body-small text-text-warning-bolder">
          {warning}
        </div>
      ) : null}
      {styleUnavailable ? (
        <div className="shrink-0 rounded-large border border-border-warning-subtle bg-background-warning-subtler px-150 py-100 text-body-small text-text-warning-bolder">
          This version stores the style <span className="font-mono">{value.style}</span>, which{" "}
          <span className="font-mono">{selectedShortName(value)}</span> does not offer
          {styles.length ? ` (it has ${styles.join(", ")})` : ""}. Pick one below — nothing is
          changed until you do.
        </div>
      ) : null}

      {/* Was a fixed `1.75fr / 1fr` grid. The ratio is a guess about someone
          else's screen and their task: browsing wants the catalog wide, tuning
          wants the inspector wide, and no constant serves both. It is a drag
          handle now, and where you leave it is remembered.

          `min-w-0` on both panels stays load-bearing for the same reason it did
          under the grid — the catalog table's columns are wider than the pane,
          and without it that overflow escapes upward and scrolls the whole tab
          sideways. */}
      <ResizablePanelGroup
        orientation="horizontal"
        defaultLayout={savedLayout}
        onLayoutChanged={persistLayout}
        className="min-h-0 flex-1"
      >
        {/* Sizes are strings on purpose. react-resizable-panels v4 reads a bare
            number as *pixels* and only a string as a percentage, so
            `defaultSize={62}` silently means 62px — which rendered the
            inspector as a 60px sliver and the catalog at 95% of the group. */}
        <ResizablePanel id="catalog" defaultSize="62%" minSize="30%" className="min-w-0 pr-100">
          <VoiceCatalogBrowser
            className="h-full min-w-0"
            mode="full"
            defaultLocale={cardLocales[0]}
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
        </ResizablePanel>

        <ResizableHandle withHandle />

        <ResizablePanel
          id="inspector"
          defaultSize="38%"
          minSize="24%"
          maxSize="60%"
          className="min-w-0 pl-100"
        >
          {/* Three bands, and only the middle one scrolls. Identity stays put
              so you always know which voice you are editing, and Preview stays
              put because it is the reason the panel exists — it used to sit at
              the bottom of the scroll, so auditioning a change meant scrolling
              down to press it and back up to adjust the knob again. */}
          <aside className="flex h-full min-h-0 flex-col overflow-hidden rounded-xlarge border border-border bg-surface">
            <div className="shrink-0 border-b border-border px-200 py-150">
              <div className="flex flex-wrap items-center justify-between gap-050">
                <div className="text-body-small font-semibold text-text-subtlest">
                  Selected voice
                </div>
                {localeMismatch ? (
                  <Lozenge
                    tone="warning"
                    className="min-w-0 truncate"
                    title={`Publishing this version ships a voice that speaks ${localeMismatch.spoken} on a card authored for ${localeMismatch.card}. The compiler reports it as G15 voice_locale and the publish dialog will ask you to confirm it deliberately.`}
                  >
                    <AlertTriangle /> Locale mismatch — voice speaks {localeMismatch.spoken}, card
                    speaks {localeMismatch.card}
                  </Lozenge>
                ) : null}
              </div>
              <div className="mt-050 truncate heading-small font-semibold text-text">
                {/* An id nothing resolves is not a voice with a long name. The
                    runtime will speak the fallback, so naming the id plainly is
                    the only honest thing this line can say. */}
                {resolution === "unknown"
                  ? `Unknown voice ${shortName}`
                  : selectedVoice?.displayName || shortName}
              </div>
              <div className="mt-025 flex flex-wrap items-center gap-100 text-body-small text-text-subtle">
                <code
                  title={shortName}
                  className="max-w-full truncate rounded bg-surface-sunken px-075 py-025 font-mono text-body-small"
                >
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

            {/* The one scrolling region in this pane. Everything that can grow
                without bound — a nine-control schema, a style list, the sample
                text — lives here; nothing above or below it moves. */}
            <div className="flex min-h-0 flex-1 flex-col gap-200 overflow-y-auto px-200 py-150">
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
                // Named per provider. "no Azure speaking styles" was hardcoded here
                // and read as a fact about a Cartesia or Fish voice, which has no
                // relationship to Azure's style list at all; the controls it then
                // pointed at (speed/pitch/warmth) are Azure's and mostly do not
                // exist on the other providers.
                <p className="text-body-small text-text-subtlest">
                  {selectedModel?.displayName ?? "This voice"} exposes no speaking styles — see the
                  controls below for what it does support.
                </p>
              )}

              {/* Controls come from the selected voice's model, not from a
              fixed Azure set. Azure keeps its four sliders because its
              schema declares exactly those; a Fish voice gets nine
              different ones and Deepgram gets almost none, which is the
              truth about those APIs. */}
              <VoiceParamsPanel
                model={selectedModel}
                values={modelParams}
                modelsLoading={ttsModelsQuery.isLoading}
                disabled={false}
                onChange={(k, v) => {
                  const scalar = asParamValue(v);
                  if (scalar === undefined) return;
                  // One write, not two. The bag and the column used to be
                  // separate `update()` calls, and each rebuilt its patch from
                  // `valueRef.current` — so the second silently discarded the
                  // first and Azure's four controls never reached `params`.
                  const patch: Partial<VoiceConfig> = {
                    params: { ...modelParams, [k]: scalar },
                  };
                  const n = Number(scalar);
                  if (k === PARAM_RATE) patch.speed = n;
                  else if (k === PARAM_PITCH) patch.pitch = n;
                  else if (k === PARAM_WARMTH) patch.warmth = n;
                  else if (k === PARAM_PAUSE_MS) patch.pauseMs = n;
                  update(patch);
                  scheduleLivePreview();
                }}
                onInsertTag={(tag) => {
                  // Markers are text, not settings — they go into the sample
                  // line so the operator hears exactly what they wrote.
                  update({ sampleText: `${valueRef.current.sampleText} [${tag}]`.trim() });
                  scheduleLivePreview();
                }}
              />

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
            </div>

            {/* Pinned. Preview is the primary action of the whole tab and it
                was the last thing in a long scroll, so the tune → listen →
                tune loop cost two scrolls per iteration. */}
            <div className="shrink-0 border-t border-border bg-surface px-200 py-150">
              <div className="flex items-center gap-150 rounded-medium border border-border bg-surface-sunken p-150">
                <button
                  type="button"
                  // Not disabled while loading. The click handler right below
                  // already treats a click during synthesis as Stop, and
                  // disabling the button meant that branch could never be
                  // reached: the control read "Synthesizing…", refused every
                  // click, and stayed that way until the 60s blob timeout —
                  // uncancellable, with a Stop icon on it.
                  disabled={!value.sampleText.trim()}
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

                {/* Only for engines that actually sample. Azure returns the
                    same performance every time (measured: identical duration
                    across three cache-cleared synthesises), so a "new take"
                    there would be a button that visibly does nothing. */}
                {selectedModel?.sampling ? (
                  <button
                    type="button"
                    disabled={loading || !value.sampleText.trim()}
                    onClick={() => void runPreview(true)}
                    title={`${selectedModel.displayName} generates a new performance each time. This takes another one — pacing and emphasis will differ.`}
                    className="inline-flex shrink-0 items-center gap-050 rounded-medium border border-border bg-surface px-150 py-075 text-body-small font-medium text-text-subtle hover:border-border-brand hover:text-text-brand disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <RefreshCw className="h-3.5 w-3.5" />
                    New take
                  </button>
                ) : null}

                <div className="min-w-0 flex-1">
                  <Waveform active={playing || loading} />
                </div>
                <Volume2 className="h-4 w-4 shrink-0 text-text-subtlest" />
              </div>
              {/* Which provider actually synthesised this — the line was
                  hardcoded to Azure once, so auditioning a Cartesia voice
                  reported that Azure had spoken it. Kept, but as one line: it
                  is provenance, and three lines of it in a pinned footer was
                  costing the controls above more height than it was worth. */}
              <p
                title="The selection is saved into deployment tuning as the voice id."
                className="mt-075 truncate text-body-tiny text-text-subtlest"
              >
                {selectedModel?.providerName ?? "Selected provider"}
                {selectedModel ? ` · ${selectedModel.displayName}` : ""}
                {meta ? ` · ${meta}` : ""}
              </p>
            </div>
          </aside>
        </ResizablePanel>
      </ResizablePanelGroup>

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
          <div className="text-body font-semibold text-text">{voice.displayName}</div>
          <div className="text-body-small text-text-subtlest">
            {voice.localName || voice.displayName}
          </div>
        </div>
        <span
          className={cn(
            "rounded border px-075 py-025 text-body-small font-medium",
            badge.className,
          )}
        >
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
        <Row label="Model" value={voice.modelSeries.length ? voice.modelSeries.join(", ") : "—"} />
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
          value={
            [
              voice.wordsPerMinute != null ? `${voice.wordsPerMinute} wpm` : null,
              voice.sampleRateHertz != null ? `${voice.sampleRateHertz} Hz` : null,
            ]
              .filter(Boolean)
              .join(" · ") || "—"
          }
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
