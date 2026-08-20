import { cn } from "@/lib/utils";

/** Native bar block (px). The Uiverse artboard is 75×100; bars only fill the
 *  bottom 50px. Cropping to this height (plus a sliver of bounce room) is what
 *  stops the mark sitting in the lower half of the sidebar slot. */
const ARTBOARD_W = 75;
const CROP_H = 52;

type Props = {
  className?: string;
  /** Height in px of the cropped mark (bars fill nearly all of it). */
  size?: number;
  /** When false, bars and ball sit at the rest pose with no CSS motion. */
  animated?: boolean;
};

/**
 * In-app brand mark — bouncing-ball equalizer (Uiverse.io / Nawsome).
 *
 * `size` is the height of the visible crop, not the original 100px artboard.
 * Width follows the 75×52 crop. Colors come from `--text` and
 * `--background-brand-bold` so light/dark both read. The previous
 * `BigBoundMark` file is kept on disk and is not imported from shell chrome.
 */
export function EqualizerMark({ className, size = 32, animated = true }: Props) {
  const width = Math.round((size * ARTBOARD_W) / CROP_H);
  const scale = size / CROP_H;

  return (
    <span
      className={cn("eq-mark", animated && "eq-mark--live", className)}
      style={{ width, height: size }}
      role="img"
      aria-label="BigBound AI"
    >
      <span className="eq-mark__stage" style={{ transform: `scale(${scale})` }}>
        <span className="eq-mark__bar" />
        <span className="eq-mark__bar" />
        <span className="eq-mark__bar" />
        <span className="eq-mark__bar" />
        <span className="eq-mark__bar" />
        <span className="eq-mark__ball" />
      </span>
    </span>
  );
}
