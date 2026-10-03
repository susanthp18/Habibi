import { ArrowLeft, FileText, PhoneForwarded, PhoneMissed, Radio } from "lucide-react";
import { Link } from "@tanstack/react-router";
import type { ActiveCall } from "@/api/handoff";
import { Lozenge } from "@/components/ui/lozenge";
import { Avatar } from "@/components/inbox/Avatar";
import { fmtDateTime } from "@/lib/format";
import { RiskLozenge } from "./HandoffQueue";
import { waitWords } from "./handoff-words";

type Props = {
  call: ActiveCall;
  monitor: boolean;
  /** Offered once the case is yours and open; reopens a closed wrap-up. */
  onWrapUp?: () => void;
};

/**
 * The case, not a call: this page has no audio. The engine put the caller
 * through to the callback line (or nobody could take them) and its own leg
 * ended or will end; what the operator works here is the follow-up.
 */
export function CaseHeader({ call, monitor, onWrapUp }: Props) {
  const waited = call.requestedAt
    ? Math.max(0, Math.floor((Date.now() - new Date(call.requestedAt).getTime()) / 1000))
    : null;
  return (
    <header className="shrink-0 border-b border-border bg-surface px-250 py-150">
      <Link
        to="/handoff"
        search={{}}
        className="mb-100 inline-flex items-center gap-050 text-body-small text-text-subtle hover:text-text"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Back to queue
      </Link>
      <div className="flex flex-wrap items-center gap-200">
        <Avatar name={call.customerName} size={40} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-100">
            <h1 className="truncate text-body font-semibold text-text">{call.customerName}</h1>
            <RiskLozenge risk={call.risk} />
            <CaseLozenge call={call} monitor={monitor} />
          </div>
          <div className="mt-025 flex flex-wrap items-center gap-x-150 gap-y-025 text-body-small text-text-subtle">
            {call.accountId ? <span className="tabular">{call.accountId}</span> : null}
            <span>{call.channel}</span>
            <span>{call.escalationReason}</span>
            {call.transferredFrom ? (
              <span className="text-text-subtlest">from {call.transferredFrom}</span>
            ) : null}
            {waited != null && call.status === "pending_claim" ? (
              <span className="tabular">waiting {waitWords(waited)}</span>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-100">
          <TransferLozenge outcome={call.transferOutcome} />
          {call.callState === "live" ? (
            <Lozenge tone="information">
              <Radio className="pulse-dot rounded-full" />
              Bot call in progress
            </Lozenge>
          ) : (
            <span className="text-body-small text-text-subtlest">
              Call ended{call.callEndedAt ? ` ${fmtDateTime(call.callEndedAt)}` : ""}
            </span>
          )}
          {onWrapUp ? (
            <button
              type="button"
              onClick={onWrapUp}
              className="flex items-center gap-075 rounded-medium bg-background-brand-bold px-150 py-075 text-body-small font-semibold text-text-inverse hover:bg-background-brand-bold-hovered"
            >
              <FileText className="h-3.5 w-3.5" />
              Wrap up
            </button>
          ) : null}
        </div>
      </div>
    </header>
  );
}

function CaseLozenge({ call, monitor }: { call: ActiveCall; monitor: boolean }) {
  if (call.status === "completed") return <Lozenge tone="success">Wrapped up</Lozenge>;
  if (call.status === "pending_claim")
    return <Lozenge tone="warning">Waiting for an agent</Lozenge>;
  if (monitor) return <Lozenge tone="information">Claimed by {call.agentName}</Lozenge>;
  return <Lozenge tone="selected">Claimed by you</Lozenge>;
}

export function TransferLozenge({ outcome }: { outcome: ActiveCall["transferOutcome"] }) {
  if (outcome === "callback_line") {
    return (
      <Lozenge tone="neutral" title="The caller was put through to the callback line">
        <PhoneForwarded />
        Put through to the callback line
      </Lozenge>
    );
  }
  if (outcome === "no_one_available") {
    return (
      <Lozenge
        tone="danger"
        title="Nobody could take the call: the customer is waiting for a call back"
      >
        <PhoneMissed />
        No one was available — call back
      </Lozenge>
    );
  }
  return null;
}
