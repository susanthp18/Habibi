import { useEffect, useMemo, useRef } from "react";
import { Play, Pause, SkipBack, SkipForward, Gauge } from "lucide-react";
import { Button } from "@/components/ui/button";
import { formatDuration } from "@/lib/format";
import { cn } from "@/lib/utils";

interface Props {
  duration: number;
  currentTime: number;
  playing: boolean;
  speed: number;
  onSeek: (t: number) => void;
  onPlayPause: () => void;
  onSpeedChange: (s: number) => void;
  /** Loudness per bucket (0..1) from the real recording. */
  peaks?: number[];
  /** Object URL for the recording. Without one there is nothing to play. */
  src?: string | null;
  /** What is (or is not) playing, shown under the controls. */
  status?: string;
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
  peaks,
  src,
  status,
}: Props) {
  const barRef = useRef<HTMLDivElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);

  // Draw the real loudness, bucketed down to 80 bars; flat until it loads.
  const bars = useMemo(() => {
    if (!peaks?.length) return Array.from({ length: 80 }, () => 0.08);
    const per = peaks.length / 80;
    return Array.from({ length: 80 }, (_, i) => {
      const slice = peaks.slice(
        Math.floor(i * per),
        Math.max(Math.floor(i * per) + 1, Math.floor((i + 1) * per)),
      );
      return Math.max(0.06, Math.min(1, Math.max(...slice) * 1.4));
    });
  }, [peaks]);

  const pct = Math.max(0, Math.min(1, currentTime / Math.max(duration, 0.001)));

  const handleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!barRef.current) return;
    const rect = barRef.current.getBoundingClientRect();
    const p = (e.clientX - rect.left) / rect.width;
    onSeek(Math.max(0, Math.min(duration, p * duration)));
  };

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.code !== "Space") return;
      const target = e.target as HTMLElement | null;
      const inField = Boolean(
        target?.closest("input, textarea, select, [contenteditable=true], button, [role=button]"),
      );
      if (inField) return;
      e.preventDefault();
      onPlayPause();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onPlayPause]);

  useEffect(() => {
    const el = audioRef.current;
    if (!el || !src) return;
    el.playbackRate = speed;
    if (playing) {
      void el.play().catch(() => undefined);
    } else {
      el.pause();
    }
  }, [playing, speed, src]);

  useEffect(() => {
    const el = audioRef.current;
    if (!el || !src) return;
    if (Math.abs(el.currentTime - currentTime) > 0.4) {
      el.currentTime = currentTime;
    }
  }, [currentTime, src]);

  return (
    <div className="rounded-medium border border-border bg-surface p-150">
      {src ? (
        // The call's transcript, shown beside the player, is its caption track.
        // eslint-disable-next-line jsx-a11y/media-has-caption
        <audio
          ref={audioRef}
          src={src}
          className="sr-only"
          onTimeUpdate={(e) => onSeek(e.currentTarget.currentTime)}
          onEnded={() => {
            if (playing) onPlayPause();
          }}
        />
      ) : null}
      <div className="flex items-center gap-100">
        <Button
          variant="outline"
          size="icon"
          className="h-400 w-400"
          onClick={() => onSeek(Math.max(0, currentTime - 10))}
          aria-label="Back 10 seconds"
        >
          <SkipBack className="h-4 w-4" />
        </Button>
        <Button
          size="icon"
          className="h-9 w-9"
          disabled={!src}
          onClick={onPlayPause}
          aria-label={playing ? "Pause" : "Play"}
        >
          {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
        </Button>
        <Button
          variant="outline"
          size="icon"
          className="h-400 w-400"
          onClick={() => onSeek(Math.min(duration, currentTime + 10))}
          aria-label="Forward 10 seconds"
        >
          <SkipForward className="h-4 w-4" />
        </Button>

        <div className="mx-100 flex-1">
          <div
            ref={barRef}
            role="slider"
            tabIndex={0}
            aria-label="Seek"
            aria-valuemin={0}
            aria-valuemax={Math.round(duration)}
            aria-valuenow={Math.round(currentTime)}
            className="relative flex h-500 cursor-pointer items-center gap-025 overflow-hidden rounded bg-surface-sunken px-050 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-brand"
            onClick={handleClick}
            onKeyDown={(e) => {
              if (e.key === "ArrowLeft") onSeek(Math.max(0, currentTime - 5));
              else if (e.key === "ArrowRight") onSeek(Math.min(duration, currentTime + 5));
              else return;
              e.preventDefault();
            }}
          >
            {bars.map((v, i) => {
              const barPct = i / bars.length;
              const passed = barPct <= pct;
              return (
                <div
                  key={i}
                  className={cn(
                    "w-[0.1875rem] rounded-small transition-colors",
                    passed ? "bg-background-brand-bold" : "bg-border",
                  )}
                  style={{ height: `${v * 100}%` }}
                />
              );
            })}
            <div
              className="pointer-events-none absolute top-0 h-full w-025 bg-background-brand-bold-pressed"
              style={{ left: `${pct * 100}%` }}
            />
          </div>
          <div className="mt-050 flex justify-between font-mono text-body-small text-text-subtlest">
            <span>{formatDuration(currentTime)}</span>
            {status ? <span className="font-sans">{status}</span> : null}
            <span>{formatDuration(duration)}</span>
          </div>
        </div>

        <div className="flex items-center gap-050 rounded-medium border border-border px-075 py-050 text-body-small text-text-subtle">
          <Gauge className="h-3.5 w-3.5" />
          {SPEEDS.map((s) => (
            <button
              key={s}
              onClick={() => onSpeedChange(s)}
              className={cn(
                "rounded px-075 py-025 font-medium",
                speed === s
                  ? "bg-background-brand-bold text-text-inverse"
                  : "hover:bg-surface-sunken",
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
