import { Link } from "@tanstack/react-router";
import { Sparkles } from "lucide-react";
import { Lozenge, type LozengeProps } from "@/components/ui/lozenge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  OFFER_STATUS_LABEL,
  OFFER_STATUS_TONE,
  fmtOfferAmount,
  type OfferPolicy,
} from "@/lib/offer-policy";

export function OfferPolicyBlock({
  policy,
  onCapture,
  capturing,
  className,
}: {
  policy?: OfferPolicy | null;
  onCapture?: () => void;
  capturing?: boolean;
  className?: string;
}) {
  const p = policy;
  const status = p?.status ?? "none";
  const tone = OFFER_STATUS_TONE[status] as LozengeProps["tone"];
  const canCapture =
    Boolean(onCapture) && (status === "ready" || status === "presented") && !p?.leadId && Boolean(p?.productId);
  const leadId = p?.leadId;

  return (
    <div className={cn("border-t border-border px-150 py-150", className)}>
      <div className="flex items-center justify-between gap-075">
        <div className="flex items-center gap-075 text-body-small font-semibold text-text">
          <Sparkles className="h-3.5 w-3.5 text-text-brand" />
          Offer
        </div>
        <Lozenge tone={tone}>{OFFER_STATUS_LABEL[status]}</Lozenge>
      </div>
      {status === "none" ? (
        <p className="mt-075 text-body-small text-text-subtlest">No offer decision on this conversation yet.</p>
      ) : status === "suppressed" || status === "shadow" ? (
        <p className="mt-075 text-body-small text-text-subtle">
          {p?.suppressionLabel ?? p?.suppressionReason ?? "Engine stayed quiet."}
        </p>
      ) : (
        <div className="mt-075 space-y-075">
          <p className="text-body-small font-medium text-text">
            {p?.productName ?? "Eligible product"}
            {p?.suggestedAmount != null ? ` · ${fmtOfferAmount(p.suggestedAmount)}` : ""}
          </p>
          {p?.talkTrack ? (
            <p className="text-body-small leading-snug text-text-subtle">“{p.talkTrack}”</p>
          ) : null}
          {p?.preferredWindow ? (
            <p className="text-body-small text-text-subtlest">Window · {p.preferredWindow}</p>
          ) : null}
        </div>
      )}
      {(leadId || canCapture) ? (
        <div className="mt-100 flex flex-wrap gap-075">
          {leadId ? (
            <Button size="sm" className="h-400 text-body-small" asChild>
              <Link to="/upsell" search={{ id: leadId }}>
                Open lead
              </Link>
            </Button>
          ) : null}
          {canCapture ? (
            <Button size="sm" className="h-400 text-body-small" disabled={capturing} onClick={onCapture}>
              {capturing ? "Capturing…" : "Capture lead"}
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
