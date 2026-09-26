import { cn } from "@/lib/utils";

/** Cheap CSS-animated voice-activity waveform. */
export function Waveform({
  active,
  bars = 20,
  className,
}: {
  active: boolean;
  bars?: number;
  className?: string;
}) {
  return (
    <div className={cn("flex h-4 items-end gap-025", className)} aria-hidden>
      {Array.from({ length: bars }).map((_, i) => {
        const h = 30 + ((i * 37) % 65); // pseudo-random static heights
        return (
          <span
            key={i}
            className={cn(
              "block w-025 rounded-full",
              active ? "bg-background-brand-bold" : "bg-text-subtlest/50",
            )}
            // One `animation` shorthand carrying its own delay. Pairing it with a
            // separate `animationDelay` made React warn on every bar each time
            // speech started or stopped (the shorthand resets the longhand).
            style={{
              height: `${h}%`,
              animation: active
                ? `wave-bar 900ms ease-in-out ${(i * 60) % 900}ms infinite`
                : "none",
            }}
          />
        );
      })}
      <style>{`
        @keyframes wave-bar {
          0%, 100% { transform: scaleY(0.35); }
          50%      { transform: scaleY(1); }
        }
      `}</style>
    </div>
  );
}
