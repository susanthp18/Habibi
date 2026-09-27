import type { PiiFinding, RedactionRecord, RedactionRules } from "@/api/types/redaction";
import { ENTITY_COLORS } from "@/lib/redaction";
import { cn } from "@/lib/utils";

interface Props {
  record: RedactionRecord;
  rules: RedactionRules;
  onToggleFinding: (findingId: string) => void;
}

/**
 * The call as spoken, each finding a clickable mask. The server renders the
 * turns: raw words with the findings marked for a raw-PII viewer, the stored
 * masked text for everyone else -- no offsets are applied in the browser.
 */
export function TranscriptRedactor({ record, rules, onToggleFinding }: Props) {
  const byId = new Map(record.findings.map((f) => [f.id, f]));
  return (
    <div className="space-y-150">
      {!record.rawVisible && record.findings.length > 0 && (
        <FindingList findings={record.findings} rules={rules} onToggle={onToggleFinding} />
      )}
      {record.transcript.map((turn) => (
        <div key={turn.id} className="flex gap-150">
          <div className="w-14 shrink-0 text-right font-mono text-body-small text-text-subtlest">
            {formatSec(turn.t)}
          </div>
          <div className="flex-1">
            <div className="mb-025 text-body-small font-semibold text-text-subtlest">
              {turn.speaker}
            </div>
            <div className="text-body leading-relaxed text-text">
              {(turn.segments ?? [{ text: turn.text }]).map((seg, i) => {
                const f = seg.findingId ? byId.get(seg.findingId) : undefined;
                return f ? (
                  <Mark
                    key={f.id}
                    finding={f}
                    raw={seg.text}
                    rules={rules}
                    onToggle={onToggleFinding}
                  />
                ) : (
                  <span key={i}>{seg.text}</span>
                );
              })}
            </div>
          </div>
        </div>
      ))}
      {record.transcript.length === 0 && (
        <div className="py-400 text-center text-body-small text-text-subtlest">
          No transcript available
        </div>
      )}
    </div>
  );
}

function Mark({
  finding: f,
  raw,
  rules,
  onToggle,
}: {
  finding: PiiFinding;
  raw: string;
  rules: RedactionRules;
  onToggle: (id: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onToggle(f.id)}
      title={describe(f, rules)}
      className={cn(
        "mx-025 inline-flex items-baseline gap-050 rounded px-050 py-0 font-mono text-body-small transition-opacity",
        f.accepted ? "text-text-inverse" : "text-text line-through opacity-70",
        f.needsReview && "ring-2 ring-offset-1 ring-border-warning",
      )}
      style={{
        backgroundColor: f.accepted ? ENTITY_COLORS[f.type] : "transparent",
        borderBottom: f.accepted ? "none" : `1.5px dashed ${ENTITY_COLORS[f.type]}`,
      }}
    >
      {f.accepted ? f.masked : raw}
    </button>
  );
}

function FindingList({
  findings,
  rules,
  onToggle,
}: {
  findings: PiiFinding[];
  rules: RedactionRules;
  onToggle: (id: string) => void;
}) {
  return (
    <div className="rounded-medium border border-border bg-surface-sunken p-100">
      <div className="mb-075 text-body-small text-text-subtlest">
        Findings on this call (the transcript below is already masked)
      </div>
      <div className="flex flex-wrap gap-075">
        {findings.map((f) => (
          <button
            key={f.id}
            type="button"
            onClick={() => onToggle(f.id)}
            title={describe(f, rules)}
            className={cn(
              "inline-flex items-center gap-050 rounded-full border px-100 py-025 text-body-small",
              f.accepted ? "border-transparent text-text-inverse" : "border-dashed text-text",
              f.needsReview && "ring-2 ring-border-warning",
            )}
            style={{ backgroundColor: f.accepted ? ENTITY_COLORS[f.type] : "transparent" }}
          >
            {rules[f.type]?.label ?? f.type} · {f.masked}
          </button>
        ))}
      </div>
    </div>
  );
}

const DETECTORS: Record<string, string> = {
  pattern: "validated pattern",
  context: "asked-for secret",
  crm: "customer's own record",
  model: "PII model",
};

function describe(f: PiiFinding, rules: RedactionRules): string {
  const by = f.detector?.startsWith("custom:")
    ? "custom rule"
    : (DETECTORS[f.detector ?? ""] ?? f.detector ?? f.source);
  const review = f.needsReview ? " · needs review" : "";
  return `${rules[f.type]?.label ?? f.type} · ${by} · ${Math.round(f.confidence * 100)}%${review} · click to ${
    f.accepted ? "unmask" : "re-mask"
  }`;
}

function formatSec(s: number) {
  const m = Math.floor(s / 60);
  const r = Math.floor(s % 60);
  return `${m}:${r.toString().padStart(2, "0")}`;
}
