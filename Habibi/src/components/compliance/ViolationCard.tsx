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
import { Lozenge, type LozengeTone } from "@/components/ui/lozenge";

const STATUS_STYLES: Record<Violation["status"], LozengeTone> = {
  open: "danger",
  in_review: "warning",
  acknowledged: "selected",
  resolved: "neutral",
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
    <div className="group flex overflow-hidden rounded-medium border border-border bg-surface transition-shadow">
      {/* Severity ribbon */}
      <div className="w-1.5 shrink-0" style={{ background: severityColor(v.severity) }} />

      <div className="min-w-0 flex-1 p-150">
        <div className="flex flex-wrap items-start gap-100">
          <button onClick={onOpen} className="min-w-0 flex-1 text-left">
            <div className="flex flex-wrap items-center gap-075">
              <span
                className="rounded-full px-075 py-025 text-body-small font-semibold"
                style={{ background: severityBg(v.severity), color: severityColor(v.severity) }}
              >
                {v.severity}
              </span>
              <span className="font-mono text-body-small text-text-subtlest">{rule.code}</span>
              <span className="text-body font-semibold text-text">{rule.label}</span>
            </div>
            <div className="mt-050 flex flex-wrap items-center gap-100 text-body-small text-text-subtle">
              <span className="inline-flex items-center gap-050">
                {v.actor.kind === "bot" ? (
                  <Bot className="h-3 w-3" />
                ) : (
                  <User className="h-3 w-3" />
                )}
                {v.actor.name}
              </span>
              <span>·</span>
              <span>{v.customerName}</span>
              <span>·</span>
              <span className="inline-flex items-center gap-050">
                <Clock className="h-3 w-3" /> {formatWhen(v.occurredAt)} @ {formatAt(v.atSec)}
              </span>
              <span>·</span>
              <span className="font-mono">{v.callId}</span>
            </div>
          </button>

          <Lozenge tone={STATUS_STYLES[v.status]}>{statusLabel(v.status)}</Lozenge>
        </div>

        {/* Evidence */}
        <div className="mt-100 space-y-050 rounded-medium bg-surface-sunken p-100 text-body-small">
          {v.evidence.preceding && (
            <EvidenceLine
              speaker={v.evidence.preceding.speaker}
              t={v.evidence.preceding.t}
              text={v.evidence.preceding.text}
              muted
            />
          )}
          <EvidenceLine
            speaker={v.evidence.offending.speaker}
            t={v.evidence.offending.t}
            text={v.evidence.offending.text}
            highlight
          />
          {v.evidence.following && (
            <EvidenceLine
              speaker={v.evidence.following.speaker}
              t={v.evidence.following.t}
              text={v.evidence.following.text}
              muted
            />
          )}
          {!v.evidence.preceding && !v.evidence.following && (
            <div className="text-body-small italic text-text-subtlest">{v.evidence.snippet}</div>
          )}
        </div>

        {/* Actions */}
        <div className="mt-100 flex flex-wrap items-center gap-075">
          {v.assignee && <Lozenge tone="selected">Assigned: {v.assignee}</Lozenge>}
          <div className="ml-auto flex flex-wrap items-center gap-050">
            <ActionBtn
              icon={UserPlus}
              label="Assign"
              onClick={onAssign}
              disabled={v.status === "resolved"}
            />
            <ActionBtn
              icon={Eye}
              label="Acknowledge"
              onClick={onAcknowledge}
              disabled={v.status === "resolved" || v.status === "acknowledged"}
            />
            <ActionBtn
              icon={CheckCircle2}
              label="Resolve"
              onClick={onResolve}
              disabled={v.status === "resolved"}
              primary
            />
            <Link
              to="/audit"
              className="inline-flex items-center gap-050 rounded-medium border border-border px-100 py-050 text-body-small text-text-subtle hover:bg-surface-sunken"
            >
              <ExternalLink className="h-3 w-3" /> Open in Audit
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}

function EvidenceLine({
  speaker,
  t,
  text,
  muted,
  highlight,
}: {
  speaker: string;
  t: number;
  text: string;
  muted?: boolean;
  highlight?: boolean;
}) {
  return (
    <div className={`flex gap-100 ${muted ? "text-text-subtlest" : "text-text"}`}>
      <span className="w-14 shrink-0 font-mono text-body-small text-text-subtlest">
        {formatAt(t)}
      </span>
      <span
        className={`w-800 shrink-0 text-body-small font-medium ${muted ? "text-text-subtlest" : "text-text"}`}
      >
        {speaker}
      </span>
      <span
        className={
          highlight ? "rounded bg-[color:var(--danger-bg)] px-050 font-medium text-text-danger" : ""
        }
      >
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
      className={`inline-flex items-center gap-050 rounded-medium border px-100 py-050 text-body-small transition-colors ${
        primary
          ? "border-border-brand bg-background-brand-bold text-white hover:bg-background-brand-bold-hovered disabled:opacity-40"
          : "border-border bg-surface text-text-subtle hover:bg-surface-sunken disabled:opacity-40"
      } disabled:cursor-not-allowed`}
    >
      <Icon className="h-3 w-3" /> {label}
    </button>
  );
}
