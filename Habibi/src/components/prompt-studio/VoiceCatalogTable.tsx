import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ArrowDown, Check, Info, Loader2, Play, Square, Star } from "lucide-react";

import type { TtsCatalogVoice } from "@/api/prompt-studio";
import { providerDot } from "@/api/providers";
import { cn } from "@/lib/utils";

type ColumnKey = "voice" | "provider" | "locale" | "gender" | "styles" | "price";
type SortKey = "voice" | "provider" | "locale" | "gender";

// Sized so the seven columns fit the catalog pane at a normal desktop width
// without a sideways nudge. They are still individually resizable — this is the
// starting point, not a cap.
const DEFAULT_WIDTHS: Record<ColumnKey, number> = {
  voice: 202,
  provider: 104,
  locale: 96,
  gender: 78,
  styles: 112,
  price: 118,
};

const MIN_WIDTHS: Record<ColumnKey, number> = {
  voice: 160,
  provider: 92,
  locale: 96,
  gender: 72,
  styles: 110,
  price: 104,
};

const ACTIONS_WIDTH = 96;
const ROW_HEIGHT = 44;

type Props = {
  items: TtsCatalogVoice[];
  value: string;
  onSelect: (voice: TtsCatalogVoice) => void;
  onPreview?: (voice: TtsCatalogVoice) => void;
  onOpenDetail?: (voice: TtsCatalogVoice) => void;
  favorites: string[];
  onToggleFavorite: (shortName: string, e: MouseEvent) => void;
  previewingShortName?: string | null;
  previewBusy?: boolean;
  disabled?: boolean;
  /**
   * Fixed pixel height for the scroller. Omit to fill the parent instead —
   * the parent then owns the height and this table takes what is left, which
   * is the only arrangement that survives a resizable pane.
   */
  height?: number;
  onEndReached?: () => void;
  tierBadge: (voice: TtsCatalogVoice) => { label: string; className: string };
};

/**
 * Tabular view of the voice catalog.
 *
 * Built as a real `<table>` with a `<colgroup>` rather than a CSS grid, for one
 * structural reason: the header and the body must share a single horizontal
 * scroll container or they drift apart once the columns exceed the pane. The
 * first version put the header *outside* the scroller and positioned rows
 * `absolute inset-x-0`, so rows sized to the container instead of the content —
 * the scroller never learned its own width and the overflow escaped all the way
 * up to the page, scrolling the entire tab sideways.
 *
 * Virtualization survives that by using spacer rows rather than transforms: a
 * `<tr>` with a computed height above and below the window keeps the table's
 * own layout algorithm intact, which `translateY` on a `<tr>` does not.
 *
 * Columns are resizable and every width is explicit, so dragging one column
 * changes that column and the table's total width — never its neighbours.
 */
export function VoiceCatalogTable({
  items,
  value,
  onSelect,
  onPreview,
  onOpenDetail,
  favorites,
  onToggleFavorite,
  previewingShortName,
  previewBusy,
  disabled,
  height,
  onEndReached,
  tierBadge,
}: Props) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  // Height comes from the parent unless a caller insists on a number. The
  // virtualizer reads `clientHeight` off the scroll element through its own
  // ResizeObserver, so a flex-derived height works exactly like a fixed one —
  // and unlike a fixed one it stays correct when the pane is dragged.
  const fill = height == null;
  const [widths, setWidths] = useState(DEFAULT_WIDTHS);
  const [resizing, setResizing] = useState<ColumnKey | null>(null);
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 } | null>(null);

  const sorted = useMemo(() => {
    if (!sort) return items;
    const pick = (v: TtsCatalogVoice) =>
      sort.key === "voice"
        ? v.displayName
        : sort.key === "provider"
          ? v.providerId || "azure"
          : sort.key === "locale"
            ? v.locale
            : v.gender;
    return [...items].sort((a, b) => pick(a).localeCompare(pick(b)) * sort.dir);
  }, [items, sort]);

  const virtualizer = useVirtualizer({
    count: sorted.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 10,
  });

  const rows = virtualizer.getVirtualItems();
  const totalSize = virtualizer.getTotalSize();
  const padTop = rows.length ? rows[0]!.start : 0;
  const padBottom = rows.length ? totalSize - rows[rows.length - 1]!.end : 0;

  // In an effect, not during render: React may render twice (StrictMode does),
  // which would turn one scroll to the bottom into two page requests.
  const lastIndex = rows.length ? rows[rows.length - 1]!.index : -1;
  useEffect(() => {
    if (onEndReached && lastIndex >= 0 && lastIndex >= sorted.length - 6) onEndReached();
  }, [lastIndex, sorted.length, onEndReached]);

  const tableWidth = Object.values(widths).reduce((a, b) => a + b, 0) + ACTIONS_WIDTH;

  const startResize = useCallback(
    (key: ColumnKey) => (e: ReactPointerEvent<HTMLSpanElement>) => {
      e.preventDefault();
      e.stopPropagation();
      const startX = e.clientX;
      const startW = widths[key];
      const prevCursor = document.body.style.cursor;
      const prevSelect = document.body.style.userSelect;
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      setResizing(key);

      const move = (ev: globalThis.PointerEvent) => {
        setWidths((w) => ({
          ...w,
          [key]: Math.max(MIN_WIDTHS[key], startW + ev.clientX - startX),
        }));
      };
      const done = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", done);
        window.removeEventListener("pointercancel", done);
        document.body.style.cursor = prevCursor;
        document.body.style.userSelect = prevSelect;
        setResizing(null);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", done);
      window.addEventListener("pointercancel", done);
    },
    [widths],
  );

  const toggleSort = (key: SortKey) =>
    setSort((s) => (s?.key === key ? { key, dir: (s.dir * -1) as 1 | -1 } : { key, dir: 1 }));

  const Header = ({
    col,
    label,
    sortKey,
    align,
  }: {
    col: ColumnKey;
    label: string;
    sortKey?: SortKey;
    align?: "right";
  }) => (
    <th
      scope="col"
      className={cn(
        "relative border-b border-border bg-surface-sunken px-3 py-2 text-left",
        "text-body-tiny font-medium tracking-wide text-text-subtlest uppercase select-none",
        align === "right" && "text-right",
      )}
    >
      {sortKey ? (
        <button
          type="button"
          onClick={() => toggleSort(sortKey)}
          className="inline-flex items-center gap-1 hover:text-text-subtle"
        >
          {label}
          <ArrowDown
            aria-hidden
            className={cn(
              "size-3 transition-[opacity,transform] duration-150",
              sort?.key === sortKey ? "opacity-100" : "opacity-0",
              sort?.key === sortKey && sort.dir === -1 && "rotate-180",
            )}
          />
        </button>
      ) : (
        label
      )}
      <span
        role="separator"
        aria-orientation="vertical"
        aria-label={`Resize ${label} column`}
        onPointerDown={startResize(col)}
        className={cn(
          "absolute inset-y-0 -right-px z-10 w-2 cursor-col-resize",
          "after:absolute after:inset-y-1 after:right-[3px] after:w-px after:bg-border",
          "hover:after:bg-border-brand",
          resizing === col && "after:bg-border-brand",
        )}
      />
    </th>
  );

  return (
    <div
      className={cn(
        "flex min-h-0 flex-col overflow-hidden rounded-lg border border-border bg-surface",
        // No pixel height given: inherit the parent's box instead of naming a
        // number. `min-h-0` is what actually lets it shrink — a flex child
        // defaults to `min-height:auto` (= content height), so without it the
        // table would push the pane taller than the viewport and scroll the page.
        fill && "h-full",
      )}
    >
      {/* THE single scroll container. Both axes live here, so the header and
          body can never drift and no overflow escapes to the page. */}
      <div
        ref={scrollRef}
        role="region"
        aria-label="Voice catalog"
        tabIndex={0}
        className={cn("overflow-auto", fill && "min-h-0 flex-1")}
        style={fill ? undefined : { height }}
      >
        <table
          className="border-collapse text-body-small"
          style={{ width: tableWidth, minWidth: tableWidth, tableLayout: "fixed" }}
        >
          <colgroup>
            <col style={{ width: widths.voice }} />
            <col style={{ width: widths.provider }} />
            <col style={{ width: widths.locale }} />
            <col style={{ width: widths.gender }} />
            <col style={{ width: widths.styles }} />
            <col style={{ width: widths.price }} />
            <col style={{ width: ACTIONS_WIDTH }} />
          </colgroup>
          <thead className="sticky top-0 z-20">
            <tr>
              <Header col="voice" label="Voice" sortKey="voice" />
              <Header col="provider" label="Provider" sortKey="provider" />
              <Header col="locale" label="Locale" sortKey="locale" />
              <Header col="gender" label="Gender" sortKey="gender" />
              <Header col="styles" label="Styles" />
              <Header col="price" label="Price" align="right" />
              <th
                scope="col"
                className="border-b border-border bg-surface-sunken px-3 py-2 text-right text-body-tiny font-medium tracking-wide text-text-subtlest uppercase"
              >
                Actions
              </th>
            </tr>
          </thead>
          <tbody>
            {padTop > 0 ? (
              <tr aria-hidden>
                <td colSpan={7} style={{ height: padTop, padding: 0, border: 0 }} />
              </tr>
            ) : null}

            {rows.map((row) => {
              const voice = sorted[row.index];
              if (!voice) return null;
              const selected = voice.shortName === value;
              const starred = favorites.includes(voice.shortName);
              const isPreviewing = previewingShortName === voice.shortName;
              const tier = tierBadge(voice);
              const providerId = voice.providerId || "azure";

              return (
                <tr
                  key={voice.shortName}
                  className={cn(
                    "border-b border-border transition-colors duration-100",
                    selected ? "bg-background-brand-subtlest" : "hover:bg-surface-hovered",
                    disabled && "pointer-events-none opacity-60",
                  )}
                  style={{ height: ROW_HEIGHT }}
                >
                  <td className="px-3">
                    <button
                      type="button"
                      onClick={() => onSelect(voice)}
                      className="flex w-full min-w-0 items-center gap-2 text-left"
                    >
                      {selected ? (
                        <Check aria-hidden className="size-3.5 shrink-0 text-text-brand" />
                      ) : (
                        <span aria-hidden className="size-3.5 shrink-0" />
                      )}
                      <span className="min-w-0">
                        <span className="block truncate font-medium text-text">
                          {voice.displayName}
                        </span>
                        <span className="block truncate text-body-tiny text-text-subtlest">
                          {voice.shortName}
                        </span>
                      </span>
                    </button>
                  </td>

                  <td className="px-3">
                    <span className="flex min-w-0 items-center gap-1.5">
                      <span
                        aria-hidden
                        className="size-1.5 shrink-0 rounded-full"
                        style={{ background: providerDot(providerId) }}
                      />
                      <span className="truncate text-text-subtle capitalize">{providerId}</span>
                    </span>
                  </td>

                  <td className="truncate px-3 text-text-subtle" title={voice.localeName}>
                    {voice.locale === "und" ? (
                      <span className="text-text-subtlest">auto</span>
                    ) : (
                      voice.locale
                    )}
                  </td>

                  <td className="truncate px-3 text-text-subtle">{voice.gender}</td>

                  <td className="truncate px-3 text-text-subtlest">
                    {voice.styles.length
                      ? `${voice.styles.slice(0, 2).join(", ")}${
                          voice.styles.length > 2 ? ` +${voice.styles.length - 2}` : ""
                        }`
                      : "—"}
                  </td>

                  <td className="px-3 text-right">
                    <span
                      className={cn(
                        "inline-flex h-5 items-center rounded border px-1.5 text-body-micro font-medium whitespace-nowrap",
                        tier.className,
                      )}
                    >
                      {tier.label}
                    </span>
                  </td>

                  <td className="px-3">
                    <span className="flex items-center justify-end gap-0.5">
                      {onPreview ? (
                        <button
                          type="button"
                          aria-label={
                            isPreviewing ? "Stop preview" : `Preview ${voice.displayName}`
                          }
                          onClick={(e) => {
                            e.stopPropagation();
                            onPreview(voice);
                          }}
                          className="flex size-6 items-center justify-center rounded text-text-subtle hover:bg-surface-sunken hover:text-text"
                        >
                          {isPreviewing && previewBusy ? (
                            <Loader2 className="size-3.5 animate-spin" />
                          ) : isPreviewing ? (
                            <Square className="size-3.5" />
                          ) : (
                            <Play className="size-3.5" />
                          )}
                        </button>
                      ) : null}
                      <button
                        type="button"
                        aria-label={starred ? "Remove favourite" : "Add favourite"}
                        aria-pressed={starred}
                        onClick={(e) => onToggleFavorite(voice.shortName, e)}
                        className="flex size-6 items-center justify-center rounded text-text-subtle hover:bg-surface-sunken hover:text-text"
                      >
                        <Star
                          className={cn("size-3.5", starred && "fill-current text-text-warning")}
                        />
                      </button>
                      {onOpenDetail ? (
                        <button
                          type="button"
                          aria-label={`Details for ${voice.displayName}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            onOpenDetail(voice);
                          }}
                          className="flex size-6 items-center justify-center rounded text-text-subtle hover:bg-surface-sunken hover:text-text"
                        >
                          <Info className="size-3.5" />
                        </button>
                      ) : null}
                    </span>
                  </td>
                </tr>
              );
            })}

            {padBottom > 0 ? (
              <tr aria-hidden>
                <td colSpan={7} style={{ height: padBottom, padding: 0, border: 0 }} />
              </tr>
            ) : null}
          </tbody>
        </table>

        {sorted.length === 0 ? (
          <div className="px-3 py-8 text-center text-body-small text-text-subtlest">
            No voices match these filters.
          </div>
        ) : null}
      </div>
    </div>
  );
}
