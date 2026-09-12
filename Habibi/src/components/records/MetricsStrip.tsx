import { StatTile, type StatTileProps } from "@/components/ui/stat-tile";
import { cn } from "@/lib/utils";

/**
 * A row of figures at the top of a records screen. Five screens declared
 * their own copy of this grid and its tile; they pass the tiles now.
 */
export function MetricsStrip({ tiles, className }: { tiles: StatTileProps[]; className?: string }) {
  return (
    <div
      className={cn("grid shrink-0 grid-cols-2 gap-100 md:grid-cols-3 xl:grid-cols-5", className)}
    >
      {tiles.map((t) => (
        <StatTile key={t.label} {...t} />
      ))}
    </div>
  );
}
