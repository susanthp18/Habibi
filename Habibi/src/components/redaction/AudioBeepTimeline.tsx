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
    <div className="rounded-lg border border-[var(--border-token)] bg-surface-sunken p-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2 text-[12px] font-semibold text-brand-navy">
          <Play className="h-3.5 w-3.5" />
          Audio timeline · {formatSec(record.durationSec)}
        </div>
        <div className="text-[11px] text-text-muted">
          {record.audioSegments.filter((s) => s.muted).length} of {record.audioSegments.length} segments beeped
        </div>
      </div>

      <div className="relative h-14 overflow-hidden rounded bg-surface-card">
        <div className="absolute inset-0 flex items-end gap-[1px] px-1">
          {bars.map((h, i) => (
            <div
              key={i}
              className="flex-1 rounded-sm bg-brand-primary/20"
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
                "absolute top-0 bottom-0 rounded-sm border-2 transition-opacity",
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

      <ul className="mt-2 max-h-24 space-y-0.5 overflow-y-auto text-[11px]">
        {record.audioSegments.map((seg) => (
          <li key={seg.findingId} className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full" style={{ background: ENTITY_COLORS[seg.type] }} />
            <span className="font-mono text-text-muted">{formatSec(seg.atSec)}</span>
            <span className="text-text-secondary">{DEFAULT_RULES[seg.type].label}</span>
            <button
              type="button"
              onClick={() => onToggleSegment(seg.findingId)}
              className="ml-auto inline-flex items-center gap-1 text-brand-primary hover:underline"
            >
              {seg.muted ? <><VolumeX className="h-3 w-3" /> Beeped</> : <><Volume2 className="h-3 w-3" /> Audible</>}
            </button>
          </li>
        ))}
        {record.audioSegments.length === 0 && (
          <li className="py-2 text-center text-text-muted">No audio PII detected</li>
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
