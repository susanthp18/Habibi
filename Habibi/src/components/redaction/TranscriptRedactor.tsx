import { Fragment } from "react";
import type { PiiFinding, RedactionRecord, RedactionRules } from "@/api/types/redaction";
import { ENTITY_COLORS } from "@/lib/redaction";
import { cn } from "@/lib/utils";

interface Props {
  record: RedactionRecord;
  rules: RedactionRules;
  onToggleFinding: (findingId: string) => void;
}

export function TranscriptRedactor({ record, rules, onToggleFinding }: Props) {
  return (
    <div className="space-y-150">
      {record.transcript.map((turn) => {
        const turnFindings = record.findings
          .filter((f) => f.turnId === turn.id)
          .sort((a, b) => a.start - b.start);
        return (
          <div key={turn.id} className="flex gap-150">
            <div className="w-14 shrink-0 text-right font-mono text-body-small text-text-subtlest">
              {formatSec(turn.t)}
            </div>
            <div className="flex-1">
              <div className="mb-025 text-body-small font-semibold text-text-subtlest">
                {turn.speaker}
              </div>
              <div className="text-body leading-relaxed text-text">
                {renderWithMarks(turn.text, turnFindings, rules, onToggleFinding)}
              </div>
            </div>
          </div>
        );
      })}
      {record.transcript.length === 0 && (
        <div className="py-400 text-center text-body-small text-text-subtlest">
          No transcript available
        </div>
      )}
    </div>
  );
}

function renderWithMarks(
  text: string,
  findings: PiiFinding[],
  rules: RedactionRules,
  onToggle: (id: string) => void,
) {
  if (findings.length === 0) return text;
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  findings.forEach((f, i) => {
    if (f.start > cursor)
      parts.push(<Fragment key={`t-${i}`}>{text.slice(cursor, f.start)}</Fragment>);
    parts.push(
      <button
        key={f.id}
        type="button"
        onClick={() => onToggle(f.id)}
        title={`${rules[f.type].label} · ${f.source} · click to ${f.accepted ? "unmask" : "re-mask"}`}
        className={cn(
          "mx-025 inline-flex items-baseline gap-050 rounded px-050 py-0 font-mono text-body-small transition-opacity",
          f.accepted ? "text-text-inverse" : "text-text line-through opacity-70",
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
