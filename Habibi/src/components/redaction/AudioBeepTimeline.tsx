import type { AudioSegment, RedactionRecord } from "@/data/redaction-seed";
import { ENTITY_COLORS, DEFAULT_RULES } from "@/data/redaction-seed";
import { Volume2, VolumeX, Play } from "lucide-react";
import { cn } from "@/lib/utils";

interface Props {
  record: RedactionRecord;
  onToggleSegment: (findingId: string) => void;
}

export function AudioBeepTimeline({ record, onToggleSegment }: Props) {
  const total = record.durationSec || 1;

  // Deterministic mock waveform bars
  const bars = Array.from({ length: 80 }, (_, i) => {
    const h = 20 + ((i * 37 + record.id.length * 13) % 60);
    return h;
  });

  return (
    <div className="rounded-large border border-border bg-surface-sunken p-150">
      <div className="mb-100 flex items-center justify-between">
        <div className="flex items-center gap-100 text-body-small font-semibold text-text">
          <Play className="h-3.5 w-3.5" />
          Audio timeline · {formatSec(record.durationSec)}
        </div>
        <div className="text-body-small text-text-subtlest">
          {record.audioSegments.filter((s) => s.muted).length} of {record.audioSegments.length} segments beeped
        </div>
      </div>

      <div className="relative h-14 overflow-hidden rounded bg-surface">
        <div className="absolute inset-0 flex items-end gap-025 px-050">
          {bars.map((h, i) => (
            <div
              key={i}
              className="flex-1 rounded-small bg-background-brand-bold/20"
              style={{ height: `${h}%` }}
            />
          ))}
        </div>
        {record.audioSegments.map((seg) => {
          const leftPct = (seg.atSec / total) * 100;
          const widthPct = Math.max(1.2, (seg.durSec / total) * 100);
          return (
            <button
              key={seg.findingId}
              type="button"
              onClick={() => onToggleSegment(seg.findingId)}
              title={`${DEFAULT_RULES[seg.type].label} at ${formatSec(seg.atSec)}`}
              className={cn(
                "absolute top-0 bottom-0 rounded-small border-2 transition-opacity",
                seg.muted ? "opacity-90" : "opacity-30",
              )}
              style={{
                left: `${leftPct}%`,
                width: `${widthPct}%`,
                background: seg.muted ? ENTITY_COLORS[seg.type] : "transparent",
                borderColor: ENTITY_COLORS[seg.type],
              }}
            />
          );
        })}
      </div>

      <ul className="mt-100 max-h-24 space-y-025 overflow-y-auto text-body-small">
        {record.audioSegments.map((seg) => (
          <li key={seg.findingId} className="flex items-center gap-100">
            <span className="h-100 w-100 rounded-full" style={{ background: ENTITY_COLORS[seg.type] }} />
            <span className="font-mono text-text-subtlest">{formatSec(seg.atSec)}</span>
            <span className="text-text-subtle">{DEFAULT_RULES[seg.type].label}</span>
            <button
              type="button"
              onClick={() => onToggleSegment(seg.findingId)}
              className="ml-auto inline-flex items-center gap-050 text-text-brand hover:underline"
            >
              {seg.muted ? <><VolumeX className="h-3 w-3" /> Beeped</> : <><Volume2 className="h-3 w-3" /> Audible</>}
            </button>
          </li>
        ))}
        {record.audioSegments.length === 0 && (
          <li className="py-100 text-center text-text-subtlest">No audio PII detected</li>
        )}
      </ul>
    </div>
  );
}

function formatSec(s: number) {
  const m = Math.floor(s / 60);
  const r = Math.floor(s % 60);
  return `${m}:${r.toString().padStart(2, "0")}`;
}
