import { Bot, User, Clock, ExternalLink, CheckCircle2, Eye, UserPlus } from "lucide-react";
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

const STATUS_STYLES: Record<Violation["status"], string> = {
  open: "bg-[color:var(--danger-bg)] text-[color:var(--danger)]",
  in_review: "bg-[color:var(--warning-bg)] text-[color:var(--warning)]",
  acknowledged: "bg-brand-tint text-brand-primary-dark",
  resolved: "bg-[color:var(--surface-sunken)] text-text-secondary",
};

export function ViolationCard({
  v,
  onOpen,
  onAssign,
  onAcknowledge,
  onResolve,
}: {
  v: Violation;
  onOpen: () => void;
  onAssign: () => void;
  onAcknowledge: () => void;
  onResolve: () => void;
}) {
  const rule = RULES_BY_ID[v.ruleId];
  if (!rule) return null;

  return (
    <div
      className="group flex overflow-hidden rounded-md border border-[var(--border-token)] bg-surface-card transition-shadow hover:shadow-sm"
    >
      {/* Severity ribbon */}
      <div className="w-1.5 shrink-0" style={{ background: severityColor(v.severity) }} />

      <div className="min-w-0 flex-1 p-3">
        <div className="flex flex-wrap items-start gap-2">
          <button
            onClick={onOpen}
            className="min-w-0 flex-1 text-left"
          >
            <div className="flex flex-wrap items-center gap-1.5">
              <span
                className="rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase"
                style={{ background: severityBg(v.severity), color: severityColor(v.severity) }}
              >
                {v.severity}
              </span>
              <span className="font-mono text-[10px] text-text-muted">{rule.code}</span>
              <span className="text-[13px] font-semibold text-brand-navy">{rule.label}</span>
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-text-secondary">
              <span className="inline-flex items-center gap-1">
                {v.actor.kind === "bot" ? <Bot className="h-3 w-3" /> : <User className="h-3 w-3" />}
                {v.actor.name}
              </span>
              <span>·</span>
              <span>{v.customerName}</span>
              <span>·</span>
              <span className="inline-flex items-center gap-1">
                <Clock className="h-3 w-3" /> {formatWhen(v.occurredAt)} @ {formatAt(v.atSec)}
              </span>
              <span>·</span>
              <span className="font-mono">{v.callId}</span>
            </div>
          </button>

          <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${STATUS_STYLES[v.status]}`}>
            {statusLabel(v.status)}
          </span>
        </div>

        {/* Evidence */}
        <div className="mt-2 space-y-1 rounded-md bg-surface-sunken p-2 text-[12px]">
          {v.evidence.preceding && (
            <EvidenceLine speaker={v.evidence.preceding.speaker} t={v.evidence.preceding.t} text={v.evidence.preceding.text} muted />
          )}
          <EvidenceLine
            speaker={v.evidence.offending.speaker}
            t={v.evidence.offending.t}
            text={v.evidence.offending.text}
            highlight
          />
          {v.evidence.following && (
            <EvidenceLine speaker={v.evidence.following.speaker} t={v.evidence.following.t} text={v.evidence.following.text} muted />
          )}
          {!v.evidence.preceding && !v.evidence.following && (
            <div className="text-[11px] italic text-text-muted">{v.evidence.snippet}</div>
          )}
        </div>

        {/* Actions */}
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {v.assignee && (
            <span className="rounded-full bg-brand-tint px-2 py-0.5 text-[10px] text-brand-primary-dark">
              Assigned: {v.assignee}
            </span>
          )}
          <div className="ml-auto flex flex-wrap items-center gap-1">
            <ActionBtn icon={UserPlus} label="Assign" onClick={onAssign} disabled={v.status === "resolved"} />
            <ActionBtn icon={Eye} label="Acknowledge" onClick={onAcknowledge} disabled={v.status === "resolved" || v.status === "acknowledged"} />
            <ActionBtn icon={CheckCircle2} label="Resolve" onClick={onResolve} disabled={v.status === "resolved"} primary />
            <Link
              to="/audit"
              className="inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] px-2 py-1 text-[11px] text-text-secondary hover:bg-surface-sunken"
            >
              <ExternalLink className="h-3 w-3" /> Open in Audit
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}

function EvidenceLine({ speaker, t, text, muted, highlight }: { speaker: string; t: number; text: string; muted?: boolean; highlight?: boolean }) {
  return (
    <div className={`flex gap-2 ${muted ? "text-text-muted" : "text-text-primary"}`}>
      <span className="w-14 shrink-0 font-mono text-[10px] text-text-muted">
        {formatAt(t)}
      </span>
      <span className={`w-16 shrink-0 text-[11px] font-medium uppercase ${muted ? "text-text-muted" : "text-brand-navy"}`}>
        {speaker}
      </span>
      <span className={highlight ? "rounded bg-[color:var(--danger-bg)] px-1 font-medium text-[color:var(--danger)]" : ""}>
        {text}
      </span>
    </div>
  );
}

function ActionBtn({
  icon: Icon,
  label,
  onClick,
  disabled,
  primary,
}: {
  icon: typeof CheckCircle2;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  primary?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] transition-colors ${
        primary
          ? "border-brand-primary bg-brand-primary text-white hover:bg-brand-primary-hover disabled:opacity-40"
          : "border-[var(--border-token)] bg-surface-card text-text-secondary hover:bg-surface-sunken disabled:opacity-40"
      } disabled:cursor-not-allowed`}
    >
      <Icon className="h-3 w-3" /> {label}
    </button>
  );
}
