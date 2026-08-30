import { Scale } from "lucide-react";
import { Lozenge, type LozengeProps } from "@/components/ui/lozenge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  AUTHORITY_STATUS_LABEL,
  AUTHORITY_STATUS_TONE,
  canApplyAuthority,
  fmtAuthorityAmount,
  type AuthorityPolicy,
} from "@/lib/authority-policy";

/**
 * Whether there is a verdict to render at all.
 *
 * A verdict in flight is not "no decision", and a verdict that failed to load
 * is not "no decision" either — both used to be indistinguishable from a quiet
 * matrix, which on this block reads as permission. Callers that fetch the
 * verdict pass their query state through so neither can be mistaken for one.
 */
export type AuthorityBlockState = "ready" | "pending" | "unavailable";

export function AuthorityPolicyBlock({
  policy,
  onApply,
  applying,
  className,
  state = "ready",
}: {
  policy?: AuthorityPolicy | null;
  onApply?: () => void;
  applying?: boolean;
  className?: string;
  state?: AuthorityBlockState;
}) {
  const p = policy;
  const status = p?.status ?? "none";
  const tone = AUTHORITY_STATUS_TONE[status] as LozengeProps["tone"];
  const canApply = state === "ready" && Boolean(onApply) && canApplyAuthority(p);
  const amount = fmtAuthorityAmount(p?.approvedAmount ?? p?.capAmount);
  const shadowMove = status === "shadow" && Boolean(amount);
  const chip: { tone: LozengeProps["tone"]; label: string } =
    state === "pending"
      ? { tone: "neutral", label: "Checking" }
      : state === "unavailable"
        ? { tone: "warning", label: "Unavailable" }
        : { tone, label: AUTHORITY_STATUS_LABEL[status] };

  return (
    <div className={cn("border-t border-border px-150 py-150", className)}>
      <div className="flex items-center justify-between gap-075">
        <div className="flex items-center gap-075 text-body-small font-semibold text-text">
          <Scale className="h-3.5 w-3.5 text-text-brand" />
          Authority
        </div>
        <Lozenge tone={chip.tone}>{chip.label}</Lozenge>
      </div>
      {state === "pending" ? (
        <p className="mt-075 text-body-small text-text-subtlest">
          Asking the authority matrix — no ceiling until it answers.
        </p>
      ) : state === "unavailable" ? (
        <p className="mt-075 text-body-small text-text-subtle">
          Authority matrix unavailable — cannot confirm what may be waived. Do not quote a waiver or
          settlement figure.
        </p>
      ) : status === "none" ? (
        <p className="mt-075 text-body-small text-text-subtlest">
          No authority decision on this conversation yet.
        </p>
      ) : status === "escalate" ? (
        <p className="mt-075 text-body-small text-text-subtle">
          {p?.reasonLabel ??
            p?.reason ??
            "Out of policy. Do not quote a waiver or settlement figure."}
        </p>
      ) : (
        <div className="mt-075 space-y-075">
          <p className="text-body-small font-medium text-text">
            {status === "applied" ? "Goodwill posted" : "Allowed move"}
            {amount ? ` · ${amount}` : ""}
          </p>
          {p?.talkTrack ? (
            <p className="text-body-small leading-snug text-text-subtle">“{p.talkTrack}”</p>
          ) : p?.reasonLabel ? (
            <p className="text-body-small text-text-subtle">{p.reasonLabel}</p>
          ) : null}
          {shadowMove ? (
            <p className="text-body-small text-text-subtlest">
              Shadow — humans see this ceiling. Nothing posts until live.
            </p>
          ) : null}
        </div>
      )}
      {canApply ? (
        <div className="mt-100 flex flex-wrap gap-075">
          <Button size="sm" className="h-400 text-body-small" disabled={applying} onClick={onApply}>
            {applying ? "Applying…" : `Apply ${amount || "goodwill"}`}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
