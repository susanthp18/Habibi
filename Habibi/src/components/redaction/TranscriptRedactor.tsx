import { Fragment } from "react";
import type { PiiFinding, RedactionRecord } from "@/data/redaction-seed";
import { ENTITY_COLORS, DEFAULT_RULES } from "@/data/redaction-seed";
import { cn } from "@/lib/utils";

interface Props {
  record: RedactionRecord;
  onToggleFinding: (findingId: string) => void;
}

export function TranscriptRedactor({ record, onToggleFinding }: Props) {
  return (
    <div className="space-y-3">
      {record.transcript.map((turn) => {
        const turnFindings = record.findings
          .filter((f) => f.turnId === turn.id)
          .sort((a, b) => a.start - b.start);
        return (
          <div key={turn.id} className="flex gap-3">
            <div className="w-14 shrink-0 text-right font-mono text-[10px] text-text-muted">
              {formatSec(turn.t)}
            </div>
            <div className="flex-1">
              <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wider text-text-muted">
                {turn.speaker}
              </div>
              <div className="text-[13px] leading-relaxed text-text-primary">
                {renderWithMarks(turn.text, turnFindings, onToggleFinding)}
              </div>
            </div>
          </div>
        );
      })}
      {record.transcript.length === 0 && (
        <div className="py-8 text-center text-[12px] text-text-muted">No transcript available</div>
      )}
    </div>
  );
}

function renderWithMarks(
  text: string,
  findings: PiiFinding[],
  onToggle: (id: string) => void,
) {
  if (findings.length === 0) return text;
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  findings.forEach((f, i) => {
    if (f.start > cursor) parts.push(<Fragment key={`t-${i}`}>{text.slice(cursor, f.start)}</Fragment>);
    parts.push(
      <button
        key={f.id}
        type="button"
        onClick={() => onToggle(f.id)}
        title={`${DEFAULT_RULES[f.type].label} · ${f.source} · click to ${f.accepted ? "unmask" : "re-mask"}`}
        className={cn(
          "mx-0.5 inline-flex items-baseline gap-1 rounded px-1 py-0 font-mono text-[12px] transition-opacity",
          f.accepted ? "text-white" : "text-text-primary line-through opacity-70",
        )}
        style={{
          backgroundColor: f.accepted ? ENTITY_COLORS[f.type] : "transparent",
          borderBottom: f.accepted ? "none" : `1.5px dashed ${ENTITY_COLORS[f.type]}`,
        }}
      >
        {f.accepted ? f.masked : f.text}
      </button>,
    );
    cursor = f.end;
  });
  if (cursor < text.length) parts.push(<Fragment key="tail">{text.slice(cursor)}</Fragment>);
  return parts;
}

function formatSec(s: number) {
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${r.toString().padStart(2, "0")}`;
}
