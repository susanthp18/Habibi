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

export function AuthorityPolicyBlock({
  policy,
  onApply,
  applying,
  className,
}: {
  policy?: AuthorityPolicy | null;
  onApply?: () => void;
  applying?: boolean;
  className?: string;
}) {
  const p = policy;
  const status = p?.status ?? "none";
  const tone = AUTHORITY_STATUS_TONE[status] as LozengeProps["tone"];
  const canApply = Boolean(onApply) && canApplyAuthority(p);
  const amount = fmtAuthorityAmount(p?.approvedAmount ?? p?.capAmount);
  const shadowMove = status === "shadow" && Boolean(amount);

  return (
    <div className={cn("border-t border-border px-150 py-150", className)}>
      <div className="flex items-center justify-between gap-075">
        <div className="flex items-center gap-075 text-body-small font-semibold text-text">
          <Scale className="h-3.5 w-3.5 text-text-brand" />
          Authority
        </div>
        <Lozenge tone={tone}>{AUTHORITY_STATUS_LABEL[status]}</Lozenge>
      </div>
      {status === "none" ? (
        <p className="mt-075 text-body-small text-text-subtlest">No authority decision on this conversation yet.</p>
      ) : status === "escalate" ? (
        <p className="mt-075 text-body-small text-text-subtle">
          {p?.reasonLabel ?? p?.reason ?? "Out of policy. Do not quote a waiver or settlement figure."}
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
            <p className="text-body-small text-text-subtlest">Shadow — humans see this ceiling. Nothing posts until live.</p>
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
