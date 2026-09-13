import { useEffect, useRef, type MouseEvent } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Check, Info, Play, Square, Star } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { LoadingState } from "@/components/ui/loading-state";
import { type TtsCatalogVoice } from "@/api/prompt-studio";
import { VoiceCatalogTable } from "./VoiceCatalogTable";
import { cn } from "@/lib/utils";
import { tierBadge } from "./VoiceCatalogBrowser";

/**
 * The catalogue as rows: the compact list the Voice tab embeds, or the cards
 * the full browser shows. Virtualised, and it pages the query in as you
 * scroll. The table view lives in VoiceCatalogTable.
 */
export function VoiceCatalogGrid({
  items,
  value,
  compact,
  fill,
  height,
  favorites,
  disabled,
  loading,
  hasNextPage,
  fetchingNextPage,
  fetchNextPage,
  onSelect,
  onStar,
  onOpenDetail,
  onPreview,
  previewingShortName,
  previewBusy,
}: {
  items: TtsCatalogVoice[];
  value: string;
  compact: boolean;
  fill: boolean;
  height: number | undefined;
  favorites: string[];
  disabled?: boolean;
  loading: boolean;
  hasNextPage: boolean;
  fetchingNextPage: boolean;
  fetchNextPage: () => void;
  onSelect: (voice: TtsCatalogVoice) => void;
  onStar: (shortName: string, e: MouseEvent) => void;
  onOpenDetail?: (voice: TtsCatalogVoice) => void;
  onPreview?: (voice: TtsCatalogVoice) => void;
  previewingShortName?: string | null;
  previewBusy?: boolean;
}) {
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
      if (!hasNextPage || fetchingNextPage) return;
      const remaining = el.scrollHeight - el.scrollTop - el.clientHeight;
      if (remaining < 120) fetchNextPage();
    };
    el.addEventListener("scroll", onScroll);
    return () => el.removeEventListener("scroll", onScroll);
  }, [hasNextPage, fetchingNextPage, fetchNextPage]);

  return (
    <div
      ref={parentRef}
      className={cn("overflow-auto", fill && "min-h-0 flex-1")}
      style={fill ? undefined : { height }}
    >
      {loading && !items.length ? (
        <div className="flex items-center justify-center py-600">
          <LoadingState label="Loading catalog" />
        </div>
      ) : null}
      {!loading && !items.length ? (
        <div className="py-600 text-center text-body-small text-text-subtlest">
          No voices match these filters.
        </div>
      ) : null}
      <div style={{ height: virtualizer.getTotalSize(), position: "relative", width: "100%" }}>
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
                    onClick={() => onSelect(voice)}
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
                  {selected ? <Check className="h-3.5 w-3.5 shrink-0 text-text-brand" /> : null}
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
                    onClick={() => onSelect(voice)}
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
  );
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return name.slice(0, 2).toUpperCase() || "?";
}
