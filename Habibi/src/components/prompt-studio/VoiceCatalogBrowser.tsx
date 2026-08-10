import { useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  Check,
  Info,
  Loader2,
  Play,
  RefreshCw,
  Search,
  Square,
  Star,
} from "lucide-react";
import { toast } from "sonner";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
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
  const usd = voice.approxUsdPer1MChars;
  const cost = usd != null ? ` · ~$${usd}/1M` : "";
  if (tier === "standard") {
    return {
      label: `Standard${cost}`,
      className: "border-border-success-subtle bg-background-success-subtler text-text-success-bolder",
    };
  }
  if (tier === "hd_flash") {
    return {
      label: `HD Flash${cost}`,
      className: "border-border-warning-subtle bg-background-warning-subtler text-text-warning-bolder",
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
    className: "border-border-warning-subtle bg-background-warning-subtler text-text-warning-bolder",
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
}: Props) {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [qDebounced, setQDebounced] = useState("");
  const [locale, setLocale] = useState("all");
  const [gender, setGender] = useState("all");
  const [showPremium, setShowPremium] = useState(false);
  const [status, setStatus] = useState("GA");
  const [favorites, setFavorites] = useState<string[]>(() => loadTtsFavorites());
  const [recent, setRecent] = useState<string[]>(() => loadTtsRecent());
  const [selectedDetail, setSelectedDetail] = useState<TtsCatalogVoice | null>(null);

  const compact = mode === "compact";
  const height = listHeight ?? (compact ? 220 : 420);

  useEffect(() => {
    const t = window.setTimeout(() => setQDebounced(q.trim()), 250);
    return () => window.clearTimeout(t);
  }, [q]);

  const catalogQuery = useInfiniteTtsVoiceCatalog({
    q: qDebounced || undefined,
    locale: locale === "all" ? undefined : locale,
    gender: gender === "all" ? undefined : gender,
    status: status || "GA",
    includePremium: showPremium,
    limit: compact ? 40 : 50,
  });
  const pricingQuery = useTtsPricing();
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
      void qc.invalidateQueries({ queryKey: ["tts-voice-catalog-infinite"] });
      void qc.invalidateQueries({ queryKey: ["tts-voice-catalog"] });
      void qc.invalidateQueries({ queryKey: ["tts-voice-sync-runs"] });
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
    const presetValues = new Set(LOCALE_PRESETS.map((p) => p.value));
    const seen = new Map<string, string>();
    for (const v of items) {
      if (!v.locale || presetValues.has(v.locale)) continue;
      if (!seen.has(v.locale)) seen.set(v.locale, v.localeName || v.locale);
    }
    return [...seen.entries()].slice(0, 8).map(([value, label]) => ({ value, label }));
  }, [items]);

  const chipVoice = (shortName: string): TtsCatalogVoice | null =>
    items.find((v) => v.shortName === shortName) ??
    (selectedDetail?.shortName === shortName ? selectedDetail : null);

  const standardPricing = pricingQuery.data?.find((t) => t.tier === "standard")?.approxUsdPer1MChars;
  const pricingLabel = standardPricing != null ? `~$${standardPricing}` : "—";

  const syncRuns = syncRunsQuery.data ?? [];

  return (
    <div className={cn("flex flex-col gap-100", className)}>
      <div
        className={cn(
          "rounded-xlarge border border-border bg-surface p-150",
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
          <Select value={locale} onValueChange={setLocale} disabled={disabled}>
            <SelectTrigger className={cn("h-9 w-[9.375rem] text-body-small", compact && "h-400 w-[8.125rem] text-body-small")}>
              <SelectValue placeholder="Locale" />
            </SelectTrigger>
            <SelectContent>
              {LOCALE_PRESETS.map((o) => (
                <SelectItem key={o.value} value={o.value} className="text-body-small">
                  {o.label}
                </SelectItem>
              ))}
              {otherLocales.map((o) => (
                <SelectItem key={o.value} value={o.value} className="text-body-small">
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={gender} onValueChange={setGender} disabled={disabled}>
            <SelectTrigger className={cn("h-9 w-[6.875rem] text-body-small", compact && "h-400 w-[6.25rem] text-body-small")}>
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
              ? "Loading…"
              : `${items.length}${total ? ` / ${total}` : ""} voices`}
            {!showPremium ? " · premium hidden" : ""}
          </span>
          {!compact ? (
            <span className="text-text-subtlest/70">
              Approx. Standard {pricingLabel}/1M chars · verify on Azure Pricing
            </span>
          ) : null}
        </div>
        {showSyncControls && !compact && syncRuns.length > 0 ? (
          <div className="mt-100 flex flex-wrap gap-075 border-t border-border pt-100">
            {syncRuns.slice(0, 3).map((run) => (
              <span
                key={run.id}
                className={cn(
                  "rounded border px-075 py-025 text-body-small",
                  run.error
                    ? "border-border-danger-subtle bg-background-danger-subtler text-text-danger-bolder"
                    : "border-border bg-surface-sunken text-text-subtle",
                )}
                title={run.error || undefined}
              >
                {run.source || "sync"} · {run.fetchedCount}
                {run.error ? " · err" : ""}
              </span>
            ))}
          </div>
        ) : null}
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
          "min-h-0 overflow-hidden rounded-xlarge border border-border bg-surface",
          compact && "rounded-medium",
        )}
      >
        {!compact ? (
          <div className="flex items-center justify-between border-b border-border px-150 py-100">
            <div className="text-body-small font-semibold text-text-subtlest">
              Voice catalog
            </div>
            <div className="flex items-center gap-050 text-body-small text-text-subtlest">
              Click <Play aria-hidden="true" className="size-3" /> to hear ·{" "}
              <Info aria-hidden="true" className="size-3" /> for details
            </div>
          </div>
        ) : null}
        <div ref={parentRef} className="overflow-auto" style={{ height }}>
          {catalogQuery.isLoading && !items.length ? (
            <div className="flex items-center justify-center gap-100 py-600 text-body-small text-text-subtlest">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading catalog…
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
                            <Badge variant="outline" className="h-4 shrink-0 px-050 text-body-small">
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
                          fav ? "text-text-warning" : "text-text-subtlest hover:text-text-warning",
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
                            {selected ? <Check className="h-4 w-4" /> : initials(voice.displayName)}
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
        {catalogQuery.hasNextPage ? (
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

/** Resolve selected catalog voice for sticky strip when off-page. */
export function useSelectedCatalogVoice(
  shortName: string,
  items: TtsCatalogVoice[],
): TtsCatalogVoice | null {
  const [detail, setDetail] = useState<TtsCatalogVoice | null>(null);
  const inList = useMemo(
    () => items.find((v) => v.shortName === shortName) ?? null,
    [items, shortName],
  );
  useEffect(() => {
    if (inList) {
      setDetail(inList);
      return;
    }
    if (!shortName) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    void fetchTtsVoiceDetail(shortName)
      .then((v) => {
        if (!cancelled) setDetail(v);
      })
      .catch(() => {
        if (!cancelled) setDetail(null);
      });
    return () => {
      cancelled = true;
    };
  }, [shortName, inList]);
  return inList ?? detail;
}
