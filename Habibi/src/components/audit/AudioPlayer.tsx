import { useEffect, useMemo, useRef } from "react";
import { Play, Pause, SkipBack, SkipForward, Gauge } from "lucide-react";
import { Button } from "@/components/ui/button";
import { formatDuration } from "@/data/audit-seed";
import { cn } from "@/lib/utils";

interface Props {
  duration: number;
  currentTime: number;
  playing: boolean;
  speed: number;
  onSeek: (t: number) => void;
  onPlayPause: () => void;
  onSpeedChange: (s: number) => void;
  seedForBars: string;
}

const SPEEDS = [1, 1.5, 2];

export function AudioPlayer({
  duration,
  currentTime,
  playing,
  speed,
  onSeek,
  onPlayPause,
  onSpeedChange,
  seedForBars,
}: Props) {
  const barRef = useRef<HTMLDivElement>(null);

  // Deterministic waveform bars from a seed
  const bars = useMemo(() => {
    let h = 2166136261;
    for (let i = 0; i < seedForBars.length; i++) {
      h ^= seedForBars.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    const out: number[] = [];
    for (let i = 0; i < 80; i++) {
      h += 0x6d2b79f5;
      let t = h;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      const v = ((t ^ (t >>> 14)) >>> 0) / 4294967296;
      out.push(0.2 + v * 0.8);
    }
    return out;
  }, [seedForBars]);

  const pct = Math.max(0, Math.min(1, currentTime / duration));

  const handleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!barRef.current) return;
    const rect = barRef.current.getBoundingClientRect();
    const p = (e.clientX - rect.left) / rect.width;
    onSeek(Math.max(0, Math.min(duration, p * duration)));
  };

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.code === "Space") {
        e.preventDefault();
        onPlayPause();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onPlayPause]);

  return (
    <div className="rounded-md border border-[var(--border-token)] bg-surface-card p-3">
      <div className="flex items-center gap-2">
        <Button variant="outline" size="icon" className="h-8 w-8" onClick={() => onSeek(Math.max(0, currentTime - 10))}>
          <SkipBack className="h-4 w-4" />
        </Button>
        <Button size="icon" className="h-9 w-9" onClick={onPlayPause}>
          {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
        </Button>
        <Button variant="outline" size="icon" className="h-8 w-8" onClick={() => onSeek(Math.min(duration, currentTime + 10))}>
          <SkipForward className="h-4 w-4" />
        </Button>

        <div className="mx-2 flex-1">
          <div
            ref={barRef}
            className="relative flex h-10 cursor-pointer items-center gap-[2px] overflow-hidden rounded bg-surface-sunken px-1"
            onClick={handleClick}
          >
            {bars.map((v, i) => {
              const barPct = i / bars.length;
              const passed = barPct <= pct;
              return (
                <div
                  key={i}
                  className={cn(
                    "w-[3px] rounded-sm transition-colors",
                    passed ? "bg-brand-primary" : "bg-[var(--border-token)]",
                  )}
                  style={{ height: `${v * 100}%` }}
                />
              );
            })}
            <div
              className="pointer-events-none absolute top-0 h-full w-[2px] bg-brand-primary-dark"
              style={{ left: `${pct * 100}%` }}
            />
          </div>
          <div className="mt-1 flex justify-between font-mono text-[11px] text-text-muted">
            <span>{formatDuration(currentTime)}</span>
            <span>{formatDuration(duration)}</span>
          </div>
        </div>

        <div className="flex items-center gap-1 rounded-md border border-[var(--border-token)] px-1.5 py-1 text-[11px] text-text-secondary">
          <Gauge className="h-3.5 w-3.5" />
          {SPEEDS.map((s) => (
            <button
              key={s}
              onClick={() => onSpeedChange(s)}
              className={cn(
                "rounded px-1.5 py-0.5 font-medium",
                speed === s ? "bg-brand-primary text-white" : "hover:bg-surface-sunken",
              )}
            >
              {s}×
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
