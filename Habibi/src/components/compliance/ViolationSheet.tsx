import { useEffect, useState } from "react";
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
import { Lozenge } from "@/components/ui/lozenge";

export function ViolationSheet({
  v,
  onClose,
  onAssign,
  onAcknowledge,
  onResolve,
  assignees,
}: {
  v: Violation | null;
  onClose: () => void;
  onAssign: (id: string, assignee: string, note: string) => void;
  onAcknowledge: (id: string, note: string) => void;
  onResolve: (id: string, note: string) => void;
  /** Live: real people from /staff. Mock: derived from seed + staff roster. */
  assignees: string[];
}) {
  const [assignee, setAssignee] = useState(assignees[0] ?? "");
  const [note, setNote] = useState("");

  useEffect(() => {
    if (assignees.length && !assignees.includes(assignee)) {
      setAssignee(assignees[0]!);
    }
  }, [assignees, assignee]);

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
      <SheetContent side="right" className="w-full max-w-[37.5rem] overflow-y-auto p-0 sm:max-w-[37.5rem]">
        <SheetHeader className="sticky top-0 z-10 border-b border-border bg-surface p-200">
          <div className="flex items-center gap-100">
            <Lozenge
              style={{
                background: severityBg(v.severity),
                color: severityColor(v.severity),
                borderColor: severityColor(v.severity),
              }}
            >
              {v.severity}
            </Lozenge>
            <span className="font-mono text-body-small text-text-subtlest">{rule.code}</span>
            <Lozenge tone="neutral" className="ml-auto">
              {statusLabel(v.status)}
            </Lozenge>
          </div>
          <SheetTitle className="text-left text-[1rem] font-semibold text-text">
            {rule.label}
          </SheetTitle>
          <div className="text-body-small text-text-subtle">{rule.description}</div>
        </SheetHeader>

        <div className="space-y-200 p-200">
          {/* Context */}
          <section className="rounded-medium border border-border bg-surface p-150">
            <div className="grid grid-cols-2 gap-100 text-body-small">
              <Field label="Customer" value={v.customerName} />
              <Field label="Call ID" value={v.callId} mono />
              <Field
                label="Actor"
                value={
                  <span className="inline-flex items-center gap-050">
                    {v.actor.kind === "bot" ? <Bot className="h-3 w-3" /> : <User className="h-3 w-3" />}
                    {v.actor.name}
                  </span>
                }
              />
              <Field
                label="Occurred"
                value={
                  <span className="inline-flex items-center gap-050">
                    <Clock className="h-3 w-3" /> {formatWhen(v.occurredAt)} @ {formatAt(v.atSec)}
                  </span>
                }
              />
              {v.assignee && <Field label="Assignee" value={v.assignee} />}
            </div>
          </section>

          {/* Evidence */}
          <section>
            <div className="mb-050 text-body-small font-semibold text-text-subtlest">Transcript evidence</div>
            <div className="space-y-050 rounded-medium border border-border bg-surface-sunken p-150 text-body-small">
              {v.evidence.preceding && <Line turn={v.evidence.preceding} muted />}
              <Line turn={v.evidence.offending} highlight />
              {v.evidence.following && <Line turn={v.evidence.following} muted />}
            </div>
            <div className="mt-050 text-body-small italic text-text-subtlest">{v.evidence.snippet}</div>
          </section>

          {/* Notes */}
          {v.notes.length > 0 && (
            <section>
              <div className="mb-050 text-body-small font-semibold text-text-subtlest">Audit trail</div>
              <ul className="space-y-050 text-body-small">
                {v.notes.map((n, i) => (
                  <li key={i} className="rounded-medium border border-border bg-surface p-100">
                    <div className="text-body-small text-text-subtlest">{formatWhen(n.at)} · {n.author}</div>
                    <div>{n.text}</div>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* Actions */}
          {v.status !== "resolved" && (
            <section className="rounded-medium border border-border bg-surface p-150">
              <div className="mb-100 text-body-small font-semibold text-text-subtlest">Action</div>
              <div className="mb-100 flex flex-wrap gap-100">
                <select
                  value={assignee}
                  onChange={(e) => setAssignee(e.target.value)}
                  disabled={!assignees.length}
                  className="h-400 flex-1 min-w-[10rem] rounded-medium border border-border bg-surface px-100 text-body-small"
                >
                  {!assignees.length && <option value="">Loading reviewers…</option>}
                  {assignees.map((r) => (
                    <option key={r} value={r}>{r}</option>
                  ))}
                </select>
                <Button
                  size="sm"
                  variant="outline"
                  className="h-400"
                  disabled={!assignee}
                  onClick={() => handle(() => onAssign(v.id, assignee, note || `Assigned to ${assignee}.`))}
                >
                  Assign for review
                </Button>
              </div>
              <Textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Add a note (required to resolve)…"
                className="mb-100 min-h-[4.375rem] text-body"
              />
              <div className="flex flex-wrap justify-end gap-100">
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
                  className="bg-background-brand-bold hover:bg-background-brand-bold-hovered"
                  onClick={() => handle(() => onResolve(v.id, note || "Resolved after review."))}
                  disabled={!note.trim()}
                >
                  Resolve
                </Button>
              </div>
            </section>
          )}

          <div className="flex flex-wrap gap-100">
            <Link
              to="/audit"
              className="inline-flex items-center gap-050 rounded-medium border border-border bg-surface px-150 py-075 text-body-small text-text-brand hover:bg-background-brand-subtlest"
            >
              <ExternalLink className="h-3.5 w-3.5" /> Open in Audit
            </Link>
            <button
              type="button"
              disabled
              title="Audio seek from compliance is not wired yet — open Audit for playback"
              className="inline-flex cursor-not-allowed items-center gap-050 rounded-medium border border-border bg-surface-sunken px-150 py-075 text-body-small text-text-subtlest opacity-60"
            >
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
      <div className="text-body-small text-text-subtlest">{label}</div>
      <div className={`text-body text-text ${mono ? "font-mono" : ""}`}>{value}</div>
    </div>
  );
}

function Line({ turn, muted, highlight }: { turn: { t: number; speaker: string; text: string }; muted?: boolean; highlight?: boolean }) {
  return (
    <div className={`flex gap-100 ${muted ? "text-text-subtlest" : "text-text"}`}>
      <span className="w-600 shrink-0 font-mono text-body-small text-text-subtlest">{formatAt(turn.t)}</span>
      <span className={`w-14 shrink-0 text-body-small font-medium ${muted ? "text-text-subtlest" : "text-text"}`}>
        {turn.speaker}
      </span>
      <span className={highlight ? "rounded bg-[color:var(--danger-bg)] px-050 font-medium text-text-danger" : ""}>
        {turn.text}
      </span>
    </div>
  );
}
