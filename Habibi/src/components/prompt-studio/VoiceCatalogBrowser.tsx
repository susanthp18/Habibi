import { useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  Check,
  ChevronDown,
  Info,
  Loader2,
  Play,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Square,
  Star,
} from "lucide-react";
import { toast } from "sonner";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { LoadingState } from "@/components/ui/loading-state";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  fetchTtsVoiceDetail,
  syncTtsVoiceCatalog,
  useInfiniteTtsVoiceCatalog,
  useTtsPricing,
  useTtsSyncRuns,
  type TtsCatalogVoice,
} from "@/api/prompt-studio";
import {
  loadTtsFavorites,
  loadTtsRecent,
  pushTtsRecent,
  toggleTtsFavorite,
} from "@/lib/tts-voice-prefs";
import {
  providerDot,
  useProviderModels,
  useVoiceLocaleCounts,
  useVoiceProviderCounts,
} from "@/api/providers";
import { FilterChips, type FilterChip } from "./FilterChips";
import { SegmentedControl } from "./ScrubField";
import { VoiceCatalogTable } from "./VoiceCatalogTable";
import { cn } from "@/lib/utils";

export const LOCALE_PRESETS: { value: string; label: string }[] = [
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

export function tierBadge(voice: TtsCatalogVoice): { label: string; className: string } {
  const tier = voice.priceTier || "standard";
  // price_tier and its USD band come from tts_price_tiers, which is
  // Azure's published pricing. Every row defaults to "standard", so a
  // Cartesia voice was rendering Azure's "~$15/1M" — a real number
  // attached to the wrong vendor, which is worse than no number. Show the
  // band only for the provider it actually describes.
  const providerId = voice.providerId || "azure";
  const usd = providerId === "azure" ? voice.approxUsdPer1MChars : null;
  const cost = usd != null ? ` · ~$${usd}/1M` : "";
  if (providerId !== "azure") {
    return {
      label: "See provider",
      className: "border-border bg-surface-sunken text-text-subtle",
    };
  }
  if (tier === "standard") {
    return {
      label: `Standard${cost}`,
      className:
        "border-border-success-subtle bg-background-success-subtler text-text-success-bolder",
    };
  }
  if (tier === "hd_flash") {
    return {
      label: `HD Flash${cost}`,
      className:
        "border-border-warning-subtle bg-background-warning-subtler text-text-warning-bolder",
    };
  }
  if (tier === "turbo") {
    return {
      label: `Turbo${cost}`,
      className: "border-border-danger-subtle bg-background-danger-subtler text-text-danger-bolder",
    };
  }
  return {
    label: `HD${cost}`,
    className:
      "border-border-warning-subtle bg-background-warning-subtler text-text-warning-bolder",
  };
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

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return name.slice(0, 2).toUpperCase() || "?";
}

type Props = {
  mode: "full" | "compact";
  value: string;
  onSelect: (voice: TtsCatalogVoice) => void;
  disabled?: boolean;
  /** full mode: open detail dialog */
  onOpenDetail?: (voice: TtsCatalogVoice) => void;
  /** full mode: play demo */
  onPreview?: (voice: TtsCatalogVoice) => void;
  previewingShortName?: string | null;
  previewBusy?: boolean;
  showSyncControls?: boolean;
  className?: string;
  listHeight?: number;
  /**
   * BCP-47 tag to open the locale filter on — the card's persona language.
   * The catalog is alphabetical by locale, so an unfiltered first paint buries
   * every relevant voice under af-ZA and am-ET. "All locales" stays one click
   * away and is still the sentinel the query strips.
   */
  defaultLocale?: string;
};

export function VoiceCatalogBrowser({
  mode,
  value,
  onSelect,
  disabled,
  onOpenDetail,
  onPreview,
  previewingShortName,
  previewBusy,
  showSyncControls = true,
  className,
  listHeight,
  defaultLocale,
}: Props) {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [qDebounced, setQDebounced] = useState("");
  // Initial value only. The browser unmounts with its tab, so reopening it
  // picks up a persona language changed in the meantime — while an operator who
  // has widened the filter mid-session keeps their choice.
  const [locale, setLocale] = useState(defaultLocale || "all");
  const [gender, setGender] = useState("all");
  const [showPremium, setShowPremium] = useState(false);
  const [status, setStatus] = useState("GA");
  const [favorites, setFavorites] = useState<string[]>(() => loadTtsFavorites());
  const [recent, setRecent] = useState<string[]>(() => loadTtsRecent());
  const [selectedDetail, setSelectedDetail] = useState<TtsCatalogVoice | null>(null);
  const [providerFilter, setProviderFilter] = useState("all");
  const [filtersOpen, setFiltersOpen] = useState(false);
  // "GA" and "premium hidden" are the defaults, so neither counts as a filter
  // the operator applied — badging them would make the badge meaningless.
  const activeFilterCount =
    (locale !== "all" ? 1 : 0) +
    (gender !== "all" ? 1 : 0) +
    (status !== "GA" ? 1 : 0) +
    (showPremium ? 1 : 0);
  // Table is the default now that the catalog spans vendors: comparing rows is
  // the job, and cards make comparison a scroll-and-remember exercise.
  const [view, setView] = useState<"table" | "grid">("table");

  const compact = mode === "compact";
  // This used to compute a pixel height from `window.innerHeight - top`, which
  // is the wrong question asked of the wrong element. The list lives inside a
  // scrollable pane, so `getBoundingClientRect().top` moves whenever that pane
  // scrolls — but the ResizeObserver watched `document.body`, which never fires
  // on scroll. The height went stale on the first scroll and stayed stale:
  // sometimes a sliver, sometimes overshooting the pane by 400px.
  //
  // Height is now a layout question answered by layout. `fill` puts this in a
  // `h-full min-h-0 flex-col` box and lets the list take whatever is left, so
  // it is correct at every window size, in a resized pane, and mid-scroll —
  // with no measurement, no floor, and no 24px fudge.
  const fill = listHeight == null && !compact;
  const height = listHeight ?? (compact ? 220 : undefined);

  useEffect(() => {
    const t = window.setTimeout(() => setQDebounced(q.trim()), 250);
    return () => window.clearTimeout(t);
  }, [q]);

  const catalogQuery = useInfiniteTtsVoiceCatalog({
    q: qDebounced || undefined,
    locale: locale === "all" ? undefined : locale,
    gender: gender === "all" ? undefined : gender,
    status: status || "GA",
    providerId: providerFilter === "all" ? undefined : providerFilter,
    includePremium: showPremium,
    limit: compact ? 40 : 50,
  });
  const pricingQuery = useTtsPricing();
  const voiceCountsQuery = useVoiceProviderCounts();
  const ttsModelsQuery = useProviderModels("tts");
  const localeCountsQuery = useVoiceLocaleCounts();
  const syncRunsQuery = useTtsSyncRuns(3);

  const items = useMemo(
    () => catalogQuery.data?.pages.flatMap((p) => p.items) ?? [],
    [catalogQuery.data],
  );
  const total = catalogQuery.data?.pages[0]?.total ?? 0;
  const lastSyncedAt = catalogQuery.data?.pages[0]?.lastSyncedAt ?? null;

  const selectedInList = useMemo(
    () => items.find((v) => v.shortName === value) ?? null,
    [items, value],
  );

  useEffect(() => {
    if (!value || selectedInList) {
      if (selectedInList) setSelectedDetail(selectedInList);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const full = await fetchTtsVoiceDetail(value);
        if (!cancelled) setSelectedDetail(full);
      } catch {
        if (!cancelled) setSelectedDetail(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [value, selectedInList]);

  const syncMutation = useMutation({
    mutationFn: syncTtsVoiceCatalog,
    onSuccess: (run) => {
      // Every read the sync can move, not only the three obvious ones. The
      // counts feeding the provider chips and the locale dropdown are derived
      // from the same table with a 60s staleTime, so "Catalog refreshed"
      // appeared over a locale list and provider tallies still describing the
      // pre-sync catalog — the two numbers an operator presses Refresh to see
      // change were the two that did not.
      void qc.invalidateQueries({ queryKey: ["tts-voice-catalog-infinite"] });
      void qc.invalidateQueries({ queryKey: ["tts-voice-catalog"] });
      void qc.invalidateQueries({ queryKey: ["tts-voice-sync-runs"] });
      void qc.invalidateQueries({ queryKey: ["tts-voice-provider-counts"] });
      void qc.invalidateQueries({ queryKey: ["tts-voice-locale-counts"] });
      void qc.invalidateQueries({ queryKey: ["tts-voices"] });
      if (run.error) toast.error(`Sync failed: ${run.error}`);
      else toast.success(`Catalog refreshed · ${run.fetchedCount} voices`);
    },
    onError: (err) => {
      const msg = err instanceof Error ? err.message : "Sync failed";
      if (/403|admin_required/i.test(msg)) {
        toast.error("Admin role required to refresh the catalog");
      } else {
        toast.error(msg);
      }
    },
  });

  const parentRef = useRef<HTMLDivElement | null>(null);
  // Only the pre-measurement guess — rows carry `virtualizer.measureElement`,
  // so the real height wins once painted. Kept in step with the compact row's
  // actual 52px (it grew a second line: locale · gender · styles) so the
  // scrollbar doesn't visibly resettle on first paint.
  const rowEstimate = compact ? 52 : 108;
  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => rowEstimate,
    overscan: 8,
  });

  useEffect(() => {
    const el = parentRef.current;
    if (!el) return;
    const onScroll = () => {
      if (!catalogQuery.hasNextPage || catalogQuery.isFetchingNextPage) return;
      const remaining = el.scrollHeight - el.scrollTop - el.clientHeight;
      if (remaining < 120) void catalogQuery.fetchNextPage();
    };
    el.addEventListener("scroll", onScroll);
    return () => el.removeEventListener("scroll", onScroll);
  }, [catalogQuery]);

  const selectVoice = (voice: TtsCatalogVoice) => {
    if (disabled) return;
    setRecent(pushTtsRecent(voice.shortName));
    setSelectedDetail(voice);
    onSelect(voice);
  };

  const onStar = (shortName: string, e: MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    setFavorites(toggleTtsFavorite(shortName));
  };

  const otherLocales = useMemo(() => {
    // Presets are a mix of exact locales (`en-IN`) and language prefixes
    // (`ta-`). Testing membership of the exact set let every `ta-*` row through
    // as "other", which is how the dropdown ended up listing Tamil twice.
    const presetValues = LOCALE_PRESETS.map((p) => p.value).filter((v) => v !== "all");
    const covered = (locale: string) =>
      presetValues.some((p) => (p.endsWith("-") ? locale.startsWith(p) : locale === p));
    const seen = new Map<string, string>();
    for (const v of items) {
      if (!v.locale || covered(v.locale)) continue;
      if (!seen.has(v.locale)) seen.set(v.locale, v.localeName || v.locale);
    }
    return [...seen.entries()].slice(0, 8).map(([value, label]) => ({ value, label }));
  }, [items]);

  const chipVoice = (shortName: string): TtsCatalogVoice | null =>
    items.find((v) => v.shortName === shortName) ??
    (selectedDetail?.shortName === shortName ? selectedDetail : null);

  const standardPricing = pricingQuery.data?.find(
    (t) => t.tier === "standard",
  )?.approxUsdPer1MChars;

  // Chips come from the registry, not from the voices present. A provider with
  // no synced voices yet (or no API key) still gets a chip showing 0 — hiding
  // it makes "why can't I pick ElevenLabs?" unanswerable from this screen.
  // Derived from the catalog rather than a constant. LOCALE_PRESETS is kept as
  // the fallback for the mock/offline path and for the language-group shortcuts
  // ("English (all)") that no single locale row can express.
  /**
   * One list, deduped by value. Two were rendered, and they overlapped.
   *
   * `localeOptions` is built from the locale-count endpoint and is exhaustive
   * when that endpoint answers. `otherLocales` was built from whatever voices
   * happened to be on the current PAGE, and excluded a locale only when it
   * matched a preset's value EXACTLY — while half the presets are prefixes
   * (`ta-`, `en-`), which no real locale string ever equals. So it excluded
   * nothing and duplicated everything: `af-ZA`, `am-ET`, `ar` and `ar-AE` each
   * appeared twice on page one, with duplicate React keys to match.
   *
   * Merged here rather than at the two render sites, because the reason the two
   * lists disagreed is that nothing ever compared them. Counts win on a clash —
   * they carry the voice count in the label, which the page-derived entry does
   * not.
   */
  const localeChoices = useMemo(() => {
    const rows = localeCountsQuery.data ?? [];
    const base = rows.length
      ? [
          { value: "all", label: "All locales" },
          ...rows.map((r) => ({
            value: r.locale,
            label: `${r.localeName || r.locale} · ${r.count}`,
          })),
        ]
      : LOCALE_PRESETS;
    const byValue = new Map(base.map((o) => [o.value, o]));
    // Only ever additive. When the counts endpoint answered, it already knows
    // every locale the catalog holds and nothing here can add to it.
    for (const o of otherLocales) if (!byValue.has(o.value)) byValue.set(o.value, o);
    return [...byValue.values()];
  }, [localeCountsQuery.data, otherLocales]);

  const providerChips: FilterChip[] = useMemo(() => {
    const counts = new Map((voiceCountsQuery.data ?? []).map((c) => [c.providerId, c.count]));
    const ttsProviders = Array.from(new Set((ttsModelsQuery.data ?? []).map((m) => m.providerId)));
    const configured = new Set(
      (ttsModelsQuery.data ?? []).filter((m) => m.configured).map((m) => m.providerId),
    );
    // Any provider that already has voices but no TTS model row still shows.
    for (const key of counts.keys()) if (!ttsProviders.includes(key)) ttsProviders.push(key);

    const all = Array.from(counts.values()).reduce((a, b) => a + b, 0);
    return [
      { key: "all", label: "All", count: all },
      ...ttsProviders
        .sort((a, b) => (counts.get(b) ?? 0) - (counts.get(a) ?? 0) || a.localeCompare(b))
        .map((slug) => ({
          key: slug,
          label: slug.charAt(0).toUpperCase() + slug.slice(1),
          dot: providerDot(slug),
          count: counts.get(slug) ?? 0,
          disabled: !configured.has(slug),
          title: configured.has(slug)
            ? undefined
            : `No API key configured for ${slug} — add one in Integrations`,
        })),
    ];
  }, [voiceCountsQuery.data, ttsModelsQuery.data]);
  const pricingLabel = standardPricing != null ? `~$${standardPricing}` : "—";

  const syncRuns = syncRunsQuery.data ?? [];

  return (
    <div className={cn("flex min-w-0 flex-col gap-100", fill && "h-full min-h-0", className)}>
      {/* Filters never scroll and never compress: `shrink-0` keeps the search
          box at full height when the list below is tall. */}
      <div
        className={cn(
          "rounded-xlarge border border-border bg-surface p-150",
          fill && "shrink-0",
          compact && "rounded-medium p-100 shadow-none",
        )}
      >
        <div className="flex flex-wrap items-center gap-100">
          <div className={cn("relative min-w-[10rem] flex-1", compact && "min-w-[7.5rem]")}>
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-subtlest" />
            <Input
              value={q}
              disabled={disabled}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search voices…"
              className={cn("h-9 pl-400 text-body-small", compact && "h-400 text-body-small")}
            />
          </div>
          {/* Search stays; the rest folds away. Six permanent controls plus a
              sync line plus a count plus a chip rail left a 2,113-row catalog
              showing one row on a short window — the filters were costing more
              screen than the thing they filter. The badge is what keeps this
              honest: a fold that hides an active filter without saying so is
              worse than no fold. */}
          {!compact ? (
            <button
              type="button"
              onClick={() => setFiltersOpen((v) => !v)}
              aria-expanded={filtersOpen}
              className={cn(
                "inline-flex h-9 shrink-0 items-center gap-075 rounded-medium border px-150 text-body-small",
                activeFilterCount > 0
                  ? "border-border-brand text-text-brand"
                  : "border-border text-text-subtle hover:border-border-brand hover:text-text-brand",
              )}
            >
              <SlidersHorizontal aria-hidden className="h-3.5 w-3.5" />
              Filters
              {activeFilterCount > 0 ? (
                <span className="rounded-full bg-background-brand-bold px-075 text-body-micro font-semibold text-white tabular-nums">
                  {activeFilterCount}
                </span>
              ) : null}
              <ChevronDown
                aria-hidden
                className={cn(
                  "h-3.5 w-3.5 transition-transform duration-200",
                  filtersOpen && "rotate-180",
                )}
              />
            </button>
          ) : null}
        </div>

        <div
          className={cn(
            "flex flex-wrap items-center gap-100",
            compact ? "mt-100" : filtersOpen ? "mt-100" : "hidden",
          )}
        >
          <Select value={locale} onValueChange={setLocale} disabled={disabled}>
            <SelectTrigger
              className={cn(
                "h-9 w-[9.375rem] text-body-small",
                compact && "h-400 w-[8.125rem] text-body-small",
              )}
            >
              <SelectValue placeholder="Locale" />
            </SelectTrigger>
            <SelectContent>
              {localeChoices.map((o) => (
                <SelectItem key={o.value} value={o.value} className="text-body-small">
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={gender} onValueChange={setGender} disabled={disabled}>
            <SelectTrigger
              className={cn(
                "h-9 w-[6.875rem] text-body-small",
                compact && "h-400 w-[6.25rem] text-body-small",
              )}
            >
              <SelectValue placeholder="Gender" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All genders</SelectItem>
              <SelectItem value="Female">Female</SelectItem>
              <SelectItem value="Male">Male</SelectItem>
              <SelectItem value="Neutral">Neutral</SelectItem>
            </SelectContent>
          </Select>
          {!compact ? (
            <Select value={status} onValueChange={setStatus} disabled={disabled}>
              <SelectTrigger className="h-9 w-[6.875rem] text-body-small">
                <SelectValue placeholder="Status" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="GA">GA</SelectItem>
                <SelectItem value="Preview">Preview</SelectItem>
              </SelectContent>
            </Select>
          ) : null}
          <label className="inline-flex items-center gap-100 rounded-medium border border-border bg-surface-sunken px-150 py-075 text-body-small text-text-subtle">
            <Switch
              aria-label="Show premium voices"
              checked={showPremium}
              onCheckedChange={setShowPremium}
              disabled={disabled}
              className={compact ? "scale-90" : undefined}
            />
            {compact ? "Premium" : "Show premium"}
          </label>
          {showSyncControls && !compact ? (
            <div className="ml-auto flex items-center gap-100 text-body-small text-text-subtlest">
              <span>{relativeSynced(lastSyncedAt)}</span>
              <button
                type="button"
                disabled={syncMutation.isPending || disabled}
                onClick={() => syncMutation.mutate()}
                // Recent sync runs used to occupy a whole row of chips above
                // the table. They are diagnostics you consult when something
                // looks stale, not something to read on every visit.
                title={
                  syncRuns.length
                    ? `Recent syncs — ${syncRuns
                        .slice(0, 3)
                        .map(
                          (r) =>
                            `${r.source || "sync"}: ${r.fetchedCount}${r.error ? " (error)" : ""}`,
                        )
                        .join(" · ")}`
                    : "Re-pull the provider voice catalogs"
                }
                className="inline-flex items-center gap-050 rounded-medium border border-border bg-surface px-100 py-050 font-medium text-text-subtle hover:border-border-brand hover:text-text-brand disabled:opacity-50"
              >
                {syncMutation.isPending ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <RefreshCw className="h-3 w-3" />
                )}
                Refresh
              </button>
            </div>
          ) : null}
        </div>
        <div className="mt-100 flex flex-wrap items-center gap-100 text-body-small text-text-subtlest">
          <span>
            {catalogQuery.isLoading && !items.length
              ? "Loading catalog…"
              : `${items.length}${total ? ` / ${total}` : ""} voices`}
            {!showPremium ? " · premium hidden" : ""}
          </span>
          {!compact && providerFilter === "azure" ? (
            // Only shown when the list is filtered to Azure. The band comes
            // from tts_price_tiers, which is Azure's published pricing —
            // printing it over a mixed-vendor list stated one vendor's rate
            // for another vendor's voices.
            <span className="text-text-subtlest/70">
              Approx. Standard {pricingLabel}/1M chars · verify on Azure Pricing
            </span>
          ) : null}
        </div>
      </div>

      {(favorites.length > 0 || recent.length > 0) && (
        <div className="flex flex-wrap gap-075 px-025">
          {favorites.slice(0, 6).map((sn) => {
            const voice = chipVoice(sn);
            return (
              <button
                key={`fav-${sn}`}
                type="button"
                disabled={disabled}
                onClick={() => {
                  if (voice) selectVoice(voice);
                  else if (selectedDetail?.shortName === sn) selectVoice(selectedDetail);
                  else {
                    void fetchTtsVoiceDetail(sn)
                      .then((v) => selectVoice(v))
                      .catch(() => toast.error("Favorite voice not in catalog"));
                  }
                }}
                className={cn(
                  "inline-flex max-w-[10rem] items-center gap-050 truncate rounded-full border px-100 py-025 text-body-small",
                  value === sn
                    ? "border-border-brand bg-background-brand-subtlest text-text-brand"
                    : "border-border-warning-subtle bg-background-warning-subtler text-text-warning-bolder",
                )}
              >
                <Star className="h-2.5 w-2.5 fill-current" />
                {voice?.displayName || sn.replace(/^.*-/, "").replace(/Neural.*$/, "")}
              </button>
            );
          })}
          {recent
            .filter((sn) => !favorites.includes(sn))
            .slice(0, 4)
            .map((sn) => {
              const voice = chipVoice(sn);
              return (
                <button
                  key={`rec-${sn}`}
                  type="button"
                  disabled={disabled}
                  onClick={() => {
                    if (voice) selectVoice(voice);
                    else {
                      void fetchTtsVoiceDetail(sn)
                        .then((v) => selectVoice(v))
                        .catch(() => toast.error("Recent voice not in catalog"));
                    }
                  }}
                  className={cn(
                    "inline-flex max-w-[8.75rem] truncate rounded-full border border-border bg-surface-sunken px-100 py-025 text-body-small text-text-subtle",
                    value === sn && "border-border-brand text-text-brand",
                  )}
                >
                  {voice?.displayName || sn.replace(/^.*-/, "").replace(/Neural.*$/, "")}
                </button>
              );
            })}
        </div>
      )}

      <div
        className={cn(
          "flex min-h-0 flex-col overflow-hidden rounded-xlarge border border-border bg-surface",
          fill && "flex-1",
          compact && "rounded-medium",
        )}
      >
        {!compact ? (
          <div className="@container flex shrink-0 flex-col gap-050 border-b border-border px-150 py-100">
            <div className="flex items-center justify-between gap-100">
              <div className="shrink-0 text-body-small font-semibold text-text-subtlest">
                Voice catalog
              </div>
              <div className="flex min-w-0 items-center gap-100">
                {/* `sm:` asked the window, so on a 1080p screen this hint stayed
                    on inside a 460px pane and wrapped "Voice catalog" onto two
                    lines to make room. `@lg` asks the pane, which is the only
                    thing that decides whether it fits. */}
                <span className="hidden shrink-0 items-center gap-050 text-body-small text-text-subtlest @lg:flex">
                  Click <Play aria-hidden="true" className="size-3" /> to hear ·{" "}
                  <Info aria-hidden="true" className="size-3" /> for details
                </span>
                <SegmentedControl
                  ariaLabel="Catalog view"
                  className="w-[7.5rem]"
                  value={view}
                  onChange={setView}
                  options={[
                    { value: "table", label: "Table", title: "Compare many voices" },
                    { value: "grid", label: "Cards", title: "Browse a few voices" },
                  ]}
                />
              </div>
            </div>
            <FilterChips
              ariaLabel="Filter by provider"
              chips={providerChips}
              value={providerFilter}
              onChange={setProviderFilter}
            />
          </div>
        ) : null}
        {view === "table" && !compact ? (
          <VoiceCatalogTable
            items={items}
            value={value}
            onSelect={selectVoice}
            onPreview={onPreview}
            onOpenDetail={onOpenDetail}
            favorites={favorites}
            onToggleFavorite={onStar}
            previewingShortName={previewingShortName}
            previewBusy={previewBusy}
            disabled={disabled}
            height={height}
            tierBadge={tierBadge}
            onEndReached={() => {
              if (catalogQuery.hasNextPage && !catalogQuery.isFetchingNextPage) {
                void catalogQuery.fetchNextPage();
              }
            }}
          />
        ) : (
          <div
            ref={parentRef}
            className={cn("overflow-auto", fill && "min-h-0 flex-1")}
            style={fill ? undefined : { height }}
          >
            {catalogQuery.isLoading && !items.length ? (
              <div className="flex items-center justify-center py-600">
                <LoadingState label="Loading catalog" />
              </div>
            ) : null}
            {!catalogQuery.isLoading && !items.length ? (
              <div className="py-600 text-center text-body-small text-text-subtlest">
                No voices match these filters.
              </div>
            ) : null}
            <div
              style={{ height: virtualizer.getTotalSize(), position: "relative", width: "100%" }}
            >
              {virtualizer.getVirtualItems().map((row) => {
                const voice = items[row.index];
                if (!voice) return null;
                const selected = voice.shortName === value;
                const fav = favorites.includes(voice.shortName);
                const badge = tierBadge(voice);
                return (
                  <div
                    key={voice.shortName}
                    data-index={row.index}
                    ref={virtualizer.measureElement}
                    style={{
                      position: "absolute",
                      top: 0,
                      left: 0,
                      width: "100%",
                      transform: `translateY(${row.start}px)`,
                    }}
                    className="px-100 py-050"
                  >
                    {compact ? (
                      // A row, not a button. The favourite/demo/detail controls
                      // are real buttons, and nesting them inside a button (as
                      // this row used to) is invalid HTML — React warns, and the
                      // browser silently unnests it, which is how the star ended
                      // up also selecting the voice.
                      <div
                        className={cn(
                          "flex w-full items-center gap-050 rounded-medium border px-100 py-050 text-left text-body-small transition",
                          selected
                            ? "border-border-brand bg-background-brand-subtlest/40"
                            : "border-border hover:bg-surface-sunken/50",
                        )}
                      >
                        <button
                          type="button"
                          disabled={disabled}
                          onClick={() => selectVoice(voice)}
                          className="min-w-0 flex-1 text-left"
                        >
                          <span className="flex items-center gap-050">
                            <span className="min-w-0 truncate font-medium text-text">
                              {voice.displayName}
                            </span>
                            {voice.isPremium ? (
                              <Badge
                                variant="outline"
                                className="h-4 shrink-0 px-050 text-body-small"
                              >
                                Premium
                              </Badge>
                            ) : null}
                          </span>
                          {/* Enough to choose between two similar names without
                            opening the detail sheet — locale, gender, and
                            whether the voice can act a style at all. */}
                          <span className="mt-025 block truncate text-body-small text-text-subtlest">
                            {[
                              voice.locale,
                              voice.gender,
                              voice.styles.length ? `${voice.styles.length} styles` : null,
                            ]
                              .filter(Boolean)
                              .join(" · ")}
                          </span>
                        </button>
                        <button
                          type="button"
                          title={fav ? "Unfavorite" : "Favorite"}
                          onClick={(e) => onStar(voice.shortName, e)}
                          className={cn(
                            "shrink-0 rounded p-025",
                            fav
                              ? "text-text-warning"
                              : "text-text-subtlest hover:text-text-warning",
                          )}
                        >
                          <Star className={cn("h-3 w-3", fav && "fill-current")} />
                        </button>
                        {onOpenDetail ? (
                          <button
                            type="button"
                            title="Voice details"
                            onClick={() => onOpenDetail(voice)}
                            className="shrink-0 rounded p-025 text-text-subtlest hover:text-text"
                          >
                            <Info className="h-3 w-3" />
                          </button>
                        ) : null}
                        {onPreview ? (
                          <button
                            type="button"
                            title="Play demo"
                            onClick={() => onPreview(voice)}
                            className="shrink-0 rounded p-025 text-text-brand hover:bg-background-brand-bold/10"
                          >
                            {previewingShortName === voice.shortName && previewBusy ? (
                              <Square className="h-3 w-3" />
                            ) : (
                              <Play className="h-3 w-3" />
                            )}
                          </button>
                        ) : null}
                        {selected ? (
                          <Check className="h-3.5 w-3.5 shrink-0 text-text-brand" />
                        ) : null}
                      </div>
                    ) : (
                      <div
                        className={cn(
                          "rounded-large border p-150 transition",
                          selected
                            ? "border-border-brand bg-background-brand-subtlest/40 ring-1 ring-border-brand/30"
                            : "border-border bg-surface hover:border-border-brand/50 hover:bg-surface-sunken/40",
                        )}
                      >
                        <button
                          type="button"
                          disabled={disabled}
                          onClick={() => selectVoice(voice)}
                          className="w-full text-left"
                        >
                          <div className="flex items-start gap-150">
                            <div
                              className={cn(
                                "grid h-9 w-9 shrink-0 place-items-center rounded-full text-body-small font-semibold",
                                selected
                                  ? "bg-background-brand-bold text-white"
                                  : "bg-background-brand-bold/10 text-text-brand",
                              )}
                            >
                              {selected ? (
                                <Check className="h-4 w-4" />
                              ) : (
                                initials(voice.displayName)
                              )}
                            </div>
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-075">
                                <div className="truncate text-body font-semibold text-text">
                                  {voice.displayName}
                                </div>
                                {voice.isPremium ? (
                                  <Badge
                                    variant="outline"
                                    className="h-4 px-050 text-body-small font-semibold"
                                  >
                                    Premium
                                  </Badge>
                                ) : null}
                              </div>
                              <div className="mt-025 truncate text-body-small text-text-subtlest">
                                {voice.gender} · {voice.localeName || voice.locale}
                              </div>
                              <div className="mt-075 flex flex-wrap gap-050">
                                <span
                                  className={cn(
                                    "inline-flex rounded border px-075 py-025 text-body-small font-medium",
                                    badge.className,
                                  )}
                                >
                                  {badge.label}
                                </span>
                                {voice.styles.slice(0, 2).map((s) => (
                                  <span
                                    key={s}
                                    className="rounded border border-border bg-surface-sunken px-075 py-025 text-body-small text-text-subtle"
                                  >
                                    {s}
                                  </span>
                                ))}
                              </div>
                            </div>
                          </div>
                        </button>
                        <div className="mt-100 flex items-center justify-end gap-050">
                          <button
                            type="button"
                            title={fav ? "Unfavorite" : "Favorite"}
                            onClick={(e) => onStar(voice.shortName, e)}
                            className={cn(
                              "inline-flex h-7 w-7 items-center justify-center rounded-medium",
                              fav
                                ? "text-text-warning"
                                : "text-text-subtlest hover:bg-surface-sunken hover:text-text-warning",
                            )}
                          >
                            <Star className={cn("h-3.5 w-3.5", fav && "fill-current")} />
                          </button>
                          {onOpenDetail ? (
                            <button
                              type="button"
                              title="Voice details"
                              onClick={() => onOpenDetail(voice)}
                              className="inline-flex h-7 w-7 items-center justify-center rounded-medium text-text-subtlest hover:bg-surface-sunken hover:text-text"
                            >
                              <Info className="h-3.5 w-3.5" />
                            </button>
                          ) : null}
                          {onPreview ? (
                            <button
                              type="button"
                              title="Play demo"
                              disabled={previewBusy && previewingShortName === voice.shortName}
                              onClick={() => onPreview(voice)}
                              className="inline-flex h-7 items-center gap-050 rounded-medium bg-background-brand-bold/10 px-100 text-body-small font-medium text-text-brand hover:bg-background-brand-bold/20 disabled:opacity-50"
                            >
                              {previewingShortName === voice.shortName && previewBusy ? (
                                <Square className="h-3 w-3" />
                              ) : (
                                <Play className="h-3 w-3" />
                              )}
                              Demo
                            </button>
                          ) : null}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}
        {catalogQuery.hasNextPage && !(view === "table" && !compact) ? (
          <div className="border-t border-border p-100 text-center">
            <button
              type="button"
              disabled={catalogQuery.isFetchingNextPage || disabled}
              onClick={() => void catalogQuery.fetchNextPage()}
              className="text-body-small font-medium text-text-brand hover:underline disabled:opacity-50"
            >
              {catalogQuery.isFetchingNextPage ? "Loading…" : "Load more"}
            </button>
          </div>
        ) : null}
      </div>

      {compact ? (
        <div className="text-body-small text-text-subtlest">
          Selected:{" "}
          <span className="font-medium text-text-subtle">
            {selectedInList?.displayName || selectedDetail?.displayName || value}
          </span>
        </div>
      ) : null}
    </div>
  );
}

/**
 * Which of the four things is true about the stored id, told apart.
 *
 * "unknown" is the one the inspector could not previously express, and the one
 * that matters: a stored id nothing resolves means the runtime will speak the
 * fallback voice, not the one named on screen.
 */
export type SelectedVoiceResolution = "none" | "loading" | "resolved" | "unknown";

/** Resolve selected catalog voice for sticky strip when off-page. */
export function useSelectedCatalogVoice(
  shortName: string,
  items: TtsCatalogVoice[],
): { voice: TtsCatalogVoice | null; resolution: SelectedVoiceResolution } {
  // Keyed on the id it describes. Held loosely, the previously resolved row
  // outlived a change of selection, and for the length of one request the
  // inspector rendered one voice's name, gender and locale under another
  // voice's id — the same substitution the locale guard beside it exists to
  // catch, performed by the panel itself.
  const [detail, setDetail] = useState<{ shortName: string; voice: TtsCatalogVoice | null } | null>(
    null,
  );
  const inList = useMemo(
    () => items.find((v) => v.shortName === shortName) ?? null,
    [items, shortName],
  );
  useEffect(() => {
    if (inList || !shortName) return;
    let cancelled = false;
    void fetchTtsVoiceDetail(shortName)
      .then((v) => {
        if (!cancelled) setDetail({ shortName, voice: v });
      })
      .catch(() => {
        // A rejected lookup is an answer, not an absence: this id is not one
        // the catalog knows. Storing it as such is what lets the caller say so.
        if (!cancelled) setDetail({ shortName, voice: null });
      });
    return () => {
      cancelled = true;
    };
  }, [shortName, inList]);

  if (!shortName) return { voice: null, resolution: "none" };
  if (inList) return { voice: inList, resolution: "resolved" };
  if (detail?.shortName !== shortName) return { voice: null, resolution: "loading" };
  return detail.voice
    ? { voice: detail.voice, resolution: "resolved" }
    : { voice: null, resolution: "unknown" };
}
