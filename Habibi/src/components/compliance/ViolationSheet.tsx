import { useState } from "react";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Bot, User, Clock, FileAudio, ExternalLink } from "lucide-react";
import { Link } from "@tanstack/react-router";
import {
  type Violation,
  RULES_BY_ID,
  severityColor,
  severityBg,
  statusLabel,
  formatWhen,
  formatAt,
} from "@/data/compliance-seed";

const REVIEWERS = ["Meera Joshi", "Rohit Verma", "Sara Khan", "Compliance Ops"];

export function ViolationSheet({
  v,
  onClose,
  onAssign,
  onAcknowledge,
  onResolve,
}: {
  v: Violation | null;
  onClose: () => void;
  onAssign: (id: string, assignee: string, note: string) => void;
  onAcknowledge: (id: string, note: string) => void;
  onResolve: (id: string, note: string) => void;
}) {
  const [assignee, setAssignee] = useState(REVIEWERS[0]!);
  const [note, setNote] = useState("");

  if (!v) return null;
  const rule = RULES_BY_ID[v.ruleId];
  if (!rule) return null;

  const handle = (fn: () => void) => {
    fn();
    setNote("");
    onClose();
  };

  return (
    <Sheet open={!!v} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full max-w-[560px] overflow-y-auto p-0 sm:max-w-[560px]">
        <SheetHeader className="sticky top-0 z-10 border-b border-[var(--border-token)] bg-surface-card p-4">
          <div className="flex items-center gap-2">
            <span
              className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase"
              style={{ background: severityBg(v.severity), color: severityColor(v.severity) }}
            >
              {v.severity}
            </span>
            <span className="font-mono text-[10px] text-text-muted">{rule.code}</span>
            <span className="ml-auto rounded-full bg-surface-sunken px-2 py-0.5 text-[10px] font-semibold uppercase text-text-secondary">
              {statusLabel(v.status)}
            </span>
          </div>
          <SheetTitle className="text-left text-[16px] font-semibold text-brand-navy">
            {rule.label}
          </SheetTitle>
          <div className="text-[12px] text-text-secondary">{rule.description}</div>
        </SheetHeader>

        <div className="space-y-4 p-4">
          {/* Context */}
          <section className="rounded-md border border-[var(--border-token)] bg-surface-card p-3">
            <div className="grid grid-cols-2 gap-2 text-[12px]">
              <Field label="Customer" value={v.customerName} />
              <Field label="Call ID" value={v.callId} mono />
              <Field
                label="Actor"
                value={
                  <span className="inline-flex items-center gap-1">
                    {v.actor.kind === "bot" ? <Bot className="h-3 w-3" /> : <User className="h-3 w-3" />}
                    {v.actor.name}
                  </span>
                }
              />
              <Field
                label="Occurred"
                value={
                  <span className="inline-flex items-center gap-1">
                    <Clock className="h-3 w-3" /> {formatWhen(v.occurredAt)} @ {formatAt(v.atSec)}
                  </span>
                }
              />
              {v.assignee && <Field label="Assignee" value={v.assignee} />}
            </div>
          </section>

          {/* Evidence */}
          <section>
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">Transcript evidence</div>
            <div className="space-y-1 rounded-md border border-[var(--border-token)] bg-surface-sunken p-3 text-[12px]">
              {v.evidence.preceding && <Line turn={v.evidence.preceding} muted />}
              <Line turn={v.evidence.offending} highlight />
              {v.evidence.following && <Line turn={v.evidence.following} muted />}
            </div>
            <div className="mt-1 text-[11px] italic text-text-muted">{v.evidence.snippet}</div>
          </section>

          {/* Notes */}
          {v.notes.length > 0 && (
            <section>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-text-muted">Audit trail</div>
              <ul className="space-y-1 text-[12px]">
                {v.notes.map((n, i) => (
                  <li key={i} className="rounded-md border border-[var(--border-token)] bg-surface-card p-2">
                    <div className="text-[11px] text-text-muted">{formatWhen(n.at)} · {n.author}</div>
                    <div>{n.text}</div>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* Actions */}
          {v.status !== "resolved" && (
            <section className="rounded-md border border-[var(--border-token)] bg-surface-card p-3">
              <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-text-muted">Action</div>
              <div className="mb-2 flex flex-wrap gap-2">
                <select
                  value={assignee}
                  onChange={(e) => setAssignee(e.target.value)}
                  className="h-8 flex-1 min-w-[160px] rounded-md border border-[var(--border-token)] bg-surface-card px-2 text-[12px]"
                >
                  {REVIEWERS.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
                <Button size="sm" variant="outline" className="h-8" onClick={() => handle(() => onAssign(v.id, assignee, note || `Assigned to ${assignee}.`))}>
                  Assign for review
                </Button>
              </div>
              <Textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Add a note (required to resolve)…"
                className="mb-2 min-h-[70px] text-[13px]"
              />
              <div className="flex flex-wrap justify-end gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handle(() => onAcknowledge(v.id, note || "Acknowledged."))}
                  disabled={v.status === "acknowledged"}
                >
                  Acknowledge
                </Button>
                <Button
                  size="sm"
                  className="bg-brand-primary hover:bg-brand-primary-hover"
                  onClick={() => handle(() => onResolve(v.id, note || "Resolved after review."))}
                  disabled={!note.trim()}
                >
                  Resolve
                </Button>
              </div>
            </section>
          )}

          <div className="flex flex-wrap gap-2">
            <Link
              to="/audit"
              className="inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] bg-surface-card px-3 py-1.5 text-[12px] text-brand-primary hover:bg-brand-tint"
            >
              <ExternalLink className="h-3.5 w-3.5" /> Open in Audit
            </Link>
            <button className="inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] bg-surface-card px-3 py-1.5 text-[12px] text-text-secondary hover:bg-surface-sunken">
              <FileAudio className="h-3.5 w-3.5" /> Jump to audio {formatAt(v.atSec)}
            </button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}

function Field({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-text-muted">{label}</div>
      <div className={`text-[13px] text-brand-navy ${mono ? "font-mono" : ""}`}>{value}</div>
    </div>
  );
}

function Line({ turn, muted, highlight }: { turn: { t: number; speaker: string; text: string }; muted?: boolean; highlight?: boolean }) {
  return (
    <div className={`flex gap-2 ${muted ? "text-text-muted" : "text-text-primary"}`}>
      <span className="w-12 shrink-0 font-mono text-[10px] text-text-muted">{formatAt(turn.t)}</span>
      <span className={`w-14 shrink-0 text-[11px] font-medium uppercase ${muted ? "text-text-muted" : "text-brand-navy"}`}>
        {turn.speaker}
      </span>
      <span className={highlight ? "rounded bg-[color:var(--danger-bg)] px-1 font-medium text-[color:var(--danger)]" : ""}>
        {turn.text}
      </span>
    </div>
  );
}
