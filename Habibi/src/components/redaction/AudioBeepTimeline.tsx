import { useRef, useState } from "react";
import { AlertTriangle, Loader2, Play, Volume2, VolumeX } from "lucide-react";

import type { RedactionRecord, RedactionRules } from "@/api/types/redaction";
import { type RecordingVariant, useRecording, useRecordingPeaks } from "@/api/recordings";
import { ENTITY_COLORS } from "@/lib/redaction";
import { cn } from "@/lib/utils";

interface Props {
  record: RedactionRecord;
  rules: RedactionRules;
  onToggleSegment: (findingId: string) => void;
  /** Viewer may hear the unredacted recording (raw-PII permission). */
  canHearOriginal?: boolean;
}

const LANES = [
  { key: "customer", label: "Customer" },
  { key: "agent", label: "Agent" },
] as const;

/**
 * The call's real recording, customer and agent lanes drawn from the audio,
 * with every beeped finding on the lane it was spoken in. Clicking a beep
 * plays from just before it, so a reviewer can hear that it is covered.
 */
export function AudioBeepTimeline({ record, rules, onToggleSegment, canHearOriginal }: Props) {
  const [variant, setVariant] = useState<RecordingVariant>("redacted");
  const recording = useRecording(record.callId, variant);
  const peaks = useRecordingPeaks(record.callId, record.channel === "voice");
  const audioRef = useRef<HTMLAudioElement>(null);
  const total = peaks.data?.durationSec || record.durationSec || 1;
  const muted = record.audioSegments.filter((s) => s.muted);
  const fallback = record.audioSegments.filter((s) => s.aligned === false).length;

  const playAt = (sec: number) => {
    const el = audioRef.current;
    if (!el) return;
    el.currentTime = Math.max(0, sec - 1);
    void el.play();
  };

  return (
    <div className="rounded-large border border-border bg-surface-sunken p-150">
      <div className="mb-100 flex items-center justify-between gap-100">
        <div className="flex items-center gap-100 text-body-small font-semibold text-text">
          <Play className="h-3.5 w-3.5" />
          Recording · {formatSec(total)}
        </div>
        <div className="flex items-center gap-100 text-body-small text-text-subtlest">
          {muted.length} of {record.audioSegments.length} segments beeped
          {fallback > 0 && (
            <span title="Words not timed exactly: a wider stretch is beeped">
              · {fallback} widened
            </span>
          )}
          {canHearOriginal && (
            <div className="ml-100 inline-flex overflow-hidden rounded-medium border border-border">
              {(["redacted", "original"] as const).map((v) => (
                <button
                  key={v}
                  type="button"
                  onClick={() => setVariant(v)}
                  className={cn(
                    "px-100 py-025",
                    variant === v ? "bg-background-brand-bold text-text-inverse" : "text-text",
                  )}
                >
                  {v === "redacted" ? "Redacted" : "Original"}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <RecordingStatus state={recording.kind} processing={record.processing} />
      {recording.kind === "ready" && (
        // The transcript preview below the player is its caption track.
        // eslint-disable-next-line jsx-a11y/media-has-caption
        <audio
          ref={audioRef}
          src={recording.src}
          className="mb-100 w-full"
          controls
          preload="metadata"
          aria-label={`${recording.variant} recording of ${record.callId}`}
        />
      )}

      <div className="space-y-050">
        {LANES.map((lane) => {
          const bars = peaks.data?.channels[lane.key] ?? peaks.data?.channels.mixed ?? [];
          // A segment with no channel (mono recording) is beeped on both.
          const segs = record.audioSegments.filter((s) => !s.channel || s.channel === lane.key);
          return (
            <div key={lane.key} className="flex items-center gap-100">
              <div className="w-16 shrink-0 text-body-small text-text-subtlest">{lane.label}</div>
              <div className="relative h-10 flex-1 overflow-hidden rounded bg-surface">
                <div className="absolute inset-0 flex items-center gap-px px-050">
                  {bars.map((h, i) => (
                    <div
                      key={i}
                      className="flex-1 rounded-small bg-background-brand-bold/30"
                      style={{ height: `${Math.max(4, Math.min(100, h * 140))}%` }}
                    />
                  ))}
                </div>
                {segs.map((seg) => (
                  <button
                    key={seg.findingId}
                    type="button"
                    onClick={() => playAt(seg.atSec)}
                    title={`${rules[seg.type]?.label ?? seg.type} at ${formatSec(seg.atSec)} — play`}
                    className={cn(
                      "absolute top-0 bottom-0 rounded-small border-2",
                      seg.muted ? "opacity-90" : "opacity-30",
                    )}
                    style={{
                      left: `${(seg.atSec / total) * 100}%`,
                      width: `${Math.max(0.6, (seg.durSec / total) * 100)}%`,
                      background: seg.muted ? ENTITY_COLORS[seg.type] : "transparent",
                      borderColor: ENTITY_COLORS[seg.type],
                    }}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>

      <ul className="mt-100 max-h-32 space-y-025 overflow-y-auto text-body-small">
        {record.audioSegments.map((seg) => (
          <li key={seg.findingId} className="flex items-center gap-100">
            <span
              className="h-100 w-100 rounded-full"
              style={{ background: ENTITY_COLORS[seg.type] }}
            />
            <button
              type="button"
              onClick={() => playAt(seg.atSec)}
              className="font-mono text-text-subtlest hover:text-text-brand hover:underline"
            >
              {formatSec(seg.atSec)}
            </button>
            <span className="text-text-subtle">{rules[seg.type]?.label ?? seg.type}</span>
            <span className="text-text-subtlest">· {seg.channel ?? "both"}</span>
            {seg.aligned === false && (
              <span className="text-text-subtlest" title="Beeped over a wider stretch">
                · widened
              </span>
            )}
            <button
              type="button"
              onClick={() => onToggleSegment(seg.findingId)}
              className="ml-auto inline-flex items-center gap-050 text-text-brand hover:underline"
            >
              {seg.muted ? (
                <>
                  <VolumeX className="h-3 w-3" /> Beeped
                </>
              ) : (
                <>
                  <Volume2 className="h-3 w-3" /> Audible
                </>
              )}
            </button>
          </li>
        ))}
        {record.audioSegments.length === 0 && (
          <li className="py-100 text-center text-text-subtlest">
            {record.processing && record.processing !== "done"
              ? "PII detection is still running on this call"
              : "No PII spoken on this call"}
          </li>
        )}
      </ul>
    </div>
  );
}

function RecordingStatus({ state, processing }: { state: string; processing?: string | null }) {
  const message =
    state === "loading"
      ? "Loading recording…"
      : state === "pending"
        ? processing === "failed"
          ? "Redaction failed on this call; the redacted recording is not available yet."
          : "The redacted recording is being made; it will play here in a few minutes."
        : state === "none"
          ? "This call has no recording."
          : state === "forbidden"
            ? "You may not hear the unredacted recording."
            : state === "error"
              ? "The recording could not be loaded."
              : null;
  if (!message) return null;
  return (
    <div className="mb-100 flex items-center gap-075 rounded-medium bg-surface px-100 py-075 text-body-small text-text-subtle">
      {state === "loading" || state === "pending" ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      ) : (
        <AlertTriangle className="h-3.5 w-3.5" />
      )}
      {message}
    </div>
  );
}

function formatSec(s: number) {
  const m = Math.floor(s / 60);
  const r = Math.floor(s % 60);
  return `${m}:${r.toString().padStart(2, "0")}`;
}
