import { useState } from "react";
import { Link } from "@tanstack/react-router";
import {
  ClipboardList,
  Headphones,
  LayoutGrid,
  MessageSquare,
  Mic,
  PhoneOff,
  PhoneForwarded,
  ShieldAlert,
  User,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { ActiveCall, FloorAction } from "@/api/types/floor";
import { actionLabel, channelLabel } from "@/lib/floor";
import { OfferPolicyBlock } from "@/components/offers/OfferPolicyBlock";
import { AuthorityPolicyBlock } from "@/components/offers/AuthorityPolicyBlock";
import { Lozenge, type LozengeProps } from "@/components/ui/lozenge";
import { SentimentBubble } from "./SentimentBubble";
import { useFloorCopilot } from "@/api/floor";
import { formatDuration, inr } from "@/lib/format";
import type { LiveLine } from "@/lib/supervisorLine";

const riskTone = {
  high: "danger",
  medium: "warning",
  low: "success",
} as const satisfies Record<ActiveCall["risk"], LozengeProps["tone"]>;

type Props = {
  call: ActiveCall;
  listening: boolean;
  onClose: () => void;
  onAction: (action: FloorAction, call: ActiveCall) => void;
  onWhisper: (text: string) => void;
  /** The supervisor's live line into this call (Voice Studio calls). */
  line?: LiveLine | null;
  onTalk?: (talking: boolean) => void;
  onRelease?: (note: string) => void;
  onEndCall?: () => void;
};

export function Inspector({
  call,
  listening,
  onClose,
  onAction,
  onWhisper,
  line,
  onTalk,
  onRelease,
  onEndCall,
}: Props) {
  const [whisper, setWhisper] = useState("");
  const [confirmBarge, setConfirmBarge] = useState(false);
  const [handbackNote, setHandbackNote] = useState("");
  const isHuman = call.handler.kind === "human";
  const studio = Boolean(call.engineRunId);
  const holding = line?.mode === "takeover" && line.status !== "closed";
  const isChat = call.channel === "whatsapp" || call.channel === "sms";
  const primary = call.recommendedAction;
  const copilot = useFloorCopilot(call.id);

  return (
    <aside className="flex h-full min-h-0 w-[22rem] shrink-0 flex-col border-l border-border bg-surface">
      <div className="flex items-start justify-between gap-100 border-b border-border px-200 py-150">
        <div className="min-w-0">
          <h2 className="truncate heading-xsmall text-text">{call.customer}</h2>
          <p className="mt-025 text-body-small text-text-subtlest">
            ••{call.accountTail} · {channelLabel[call.channel]} · {call.language}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="focus-ring grid h-400 w-400 place-items-center rounded-medium text-text-subtle hover:bg-surface-sunken"
          aria-label="Close inspector"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="flex flex-wrap items-center gap-075 px-200 py-150">
          <Lozenge tone={riskTone[call.risk]}>{call.risk} risk</Lozenge>
          <Lozenge tone="neutral">{call.topic}</Lozenge>
          <Lozenge tone={isHuman ? "selected" : "warning"}>
            {isHuman ? call.handler.name : "Bot"}
          </Lozenge>
          <span className="ml-auto tabular text-body-small font-semibold text-text">
            {formatDuration(call.durationSec)}
          </span>
        </div>

        <div className="px-200 pb-150">
          <SentimentBubble value={call.sentiment} trend={call.sentimentTrend} size="md" />
        </div>

        <dl className="grid grid-cols-2 gap-x-150 gap-y-100 border-t border-border px-200 py-150">
          <div>
            <dt className="text-body-small text-text-subtlest">Outstanding</dt>
            <dd className="tabular text-body font-semibold text-text">{inr(call.outstanding)}</dd>
          </div>
          <div>
            <dt className="text-body-small text-text-subtlest">Account risk</dt>
            <dd className="text-body font-semibold capitalize text-text">{call.customerRisk}</dd>
          </div>
          <div>
            <dt className="text-body-small text-text-subtlest">DND</dt>
            <dd className="text-body font-semibold text-text">{call.dnd ? "Active" : "Clear"}</dd>
          </div>
          <div>
            <dt className="text-body-small text-text-subtlest">Queue</dt>
            <dd className="text-body font-semibold text-text">
              {call.pendingHandoff ? "Waiting" : "—"}
            </dd>
          </div>
        </dl>

        {call.flags.length > 0 && (
          <div className="border-t border-border px-200 py-150">
            <p className="mb-075 text-body-small font-semibold text-text-subtlest">Flags</p>
            <div className="flex flex-wrap gap-050">
              {call.flags.map((f) => (
                <Lozenge key={f} tone="warning">
                  {f.replace(/-/g, " ")}
                </Lozenge>
              ))}
            </div>
          </div>
        )}

        <OfferPolicyBlock policy={call.offerPolicy} />
        <AuthorityPolicyBlock policy={call.authorityPolicy} />
        {copilot.data?.whisperDraft ? (
          <div className="border-t border-border px-200 py-150">
            <p className="mb-075 text-body-small font-semibold text-text-subtlest">
              Copilot (engines)
            </p>
            {copilot.data.card?.displayName || copilot.data.card?.botId ? (
              <div className="mb-075 flex flex-wrap gap-050">
                <Lozenge tone="neutral">
                  {copilot.data.card.displayName || copilot.data.card.botId}
                </Lozenge>
                {(copilot.data.card.skills ?? []).map((skill) => (
                  <Lozenge key={skill} tone="information">
                    {skill}
                  </Lozenge>
                ))}
              </div>
            ) : null}
            <p className="text-body-small text-text">{copilot.data.whisperDraft}</p>
            {copilot.data.vetoes.length > 0 ? (
              <p className="mt-050 text-body-small text-text-danger">
                Veto: {copilot.data.vetoes.join(" · ")}
              </p>
            ) : null}
            <button
              type="button"
              className="mt-075 text-body-small font-medium text-text-brand"
              onClick={() => {
                if (copilot.data?.whisperDraft) setWhisper(copilot.data.whisperDraft);
              }}
            >
              Use as whisper
            </button>
          </div>
        ) : null}
        {call.liveQa && call.liveQa.status && call.liveQa.status !== "none" ? (
          <div className="border-t border-border px-200 py-150">
            <p className="mb-075 text-body-small font-semibold text-text-subtlest">Live QA</p>
            <p className="text-body-small text-text">
              {call.liveQa.reason?.replace(/-/g, " ") ?? call.liveQa.status}
              {call.liveQa.status === "would_barge" ? " · would barge (shadow)" : ""}
              {call.liveQa.audioCapable ? " · live audio" : " · CRM takeover only"}
            </p>
          </div>
        ) : null}

        {line ? (
          <div className="border-t border-border px-200 py-150" aria-live="polite">
            <p className="mb-075 text-body-small font-semibold text-text-subtlest">
              {line.status === "connecting"
                ? "Joining the call…"
                : line.status === "closed"
                  ? `Line closed${line.reason ? ` — ${line.reason.replace(/_/g, " ")}` : ""}`
                  : line.mode === "takeover"
                    ? "Live — you have the call"
                    : "Live — listening"}
            </p>
            {line.micError ? (
              <p className="mb-075 text-body-small text-text-danger">{line.micError}</p>
            ) : null}
            {line.turns.length === 0 ? (
              <p className="text-body-small italic text-text-subtlest">
                Waiting for someone to speak…
              </p>
            ) : (
              <ul className="max-h-60 space-y-075 overflow-y-auto">
                {line.turns.map((t, i) => (
                  <li key={i} className={cn("text-body-small", !t.final && "text-text-subtlest")}>
                    <span className="font-semibold capitalize text-text-subtle">{t.speaker}: </span>
                    <span className="text-text">{t.text}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : null}

        <div className="border-t border-border px-200 py-150">
          <p className="mb-075 text-body-small font-semibold text-text-subtlest">Recent turns</p>
          {call.recentTurns.length === 0 ? (
            <p className="text-body-small italic text-text-subtlest">“{call.lastLine}”</p>
          ) : (
            <ul className="space-y-075">
              {call.recentTurns.map((t, i) => (
                <li key={`${t.speaker}-${i}`} className="text-body-small">
                  <span className="font-semibold capitalize text-text-subtle">{t.speaker}: </span>
                  <span className="text-text">{t.text}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="border-t border-border px-200 py-150">
          <p className="mb-075 text-body-small font-semibold text-text-subtlest">Open in</p>
          <div className="flex flex-col gap-050">
            {call.customerId && (
              <Link
                to="/customers/$customerId"
                params={{ customerId: call.customerId }}
                className="flex items-center gap-075 rounded-medium px-100 py-075 text-body-small font-medium text-text-brand hover:bg-surface-sunken"
              >
                <User className="h-3.5 w-3.5" />
                Customer 360
              </Link>
            )}
            {isChat && call.conversationId && (
              <Link
                to="/inbox"
                search={{ conversationId: call.conversationId }}
                className="flex items-center gap-075 rounded-medium px-100 py-075 text-body-small font-medium text-text-brand hover:bg-surface-sunken"
              >
                <LayoutGrid className="h-3.5 w-3.5" />
                Conversation inbox
              </Link>
            )}
            {(isHuman || call.pendingHandoff) && (
              <Link
                to="/handoff"
                search={{ interactionId: call.id, customerId: call.customerId, mode: "monitor" }}
                className="flex items-center gap-075 rounded-medium px-100 py-075 text-body-small font-medium text-text-brand hover:bg-surface-sunken"
              >
                <Headphones className="h-3.5 w-3.5" />
                Monitor in handoff
              </Link>
            )}
            <Link
              to="/compliance"
              search={{ callId: call.id }}
              className="flex items-center gap-075 rounded-medium px-100 py-075 text-body-small font-medium text-text-brand hover:bg-surface-sunken"
            >
              <ShieldAlert className="h-3.5 w-3.5" />
              Compliance
            </Link>
            <Link
              to="/audit"
              search={{ id: call.id }}
              className="flex items-center gap-075 rounded-medium px-100 py-075 text-body-small font-medium text-text-brand hover:bg-surface-sunken"
            >
              <ClipboardList className="h-3.5 w-3.5" />
              Audit trail
            </Link>
            <Link
              to="/qa"
              search={{ callId: call.id }}
              className="flex items-center gap-075 rounded-medium px-100 py-075 text-body-small font-medium text-text-brand hover:bg-surface-sunken"
            >
              <ClipboardList className="h-3.5 w-3.5" />
              QA scorecard
            </Link>
          </div>
        </div>
      </div>

      <div className="shrink-0 border-t border-border px-200 py-150">
        {confirmBarge ? (
          <div className="rounded-medium border border-border-danger bg-background-danger p-100 text-body-small">
            <p className="font-semibold text-text-danger">Take over this session?</p>
            <p className="mt-025 text-text-subtle">
              {studio
                ? "The agent is paused and your microphone goes to the caller. Hand the call back when you are done."
                : `${isHuman ? call.handler.name : "Bot"} will be dropped. You land in Handoff${
                    call.liveQa?.audioCapable
                      ? " and join the live Twilio call."
                      : ". Sandbox/WhatsApp has no audio plane."
                  }`}
            </p>
            <div className="mt-075 flex justify-end gap-050">
              <button
                type="button"
                onClick={() => setConfirmBarge(false)}
                className="rounded px-100 py-050 text-text-subtle"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  setConfirmBarge(false);
                  onAction("barge", call);
                }}
                className="rounded bg-background-danger-bold px-100 py-050 font-semibold text-text-inverse"
              >
                Take over
              </button>
            </div>
          </div>
        ) : holding ? (
          <div className="space-y-100">
            <button
              type="button"
              disabled={line?.status !== "live" || Boolean(line?.micError)}
              onPointerDown={() => onTalk?.(true)}
              onPointerUp={() => onTalk?.(false)}
              onPointerLeave={() => line?.talking && onTalk?.(false)}
              onKeyDown={(e) => {
                if (e.key === " " && !e.repeat) onTalk?.(true);
              }}
              onKeyUp={(e) => {
                if (e.key === " ") onTalk?.(false);
              }}
              className={cn(
                "flex w-full items-center justify-center gap-050 rounded-medium px-100 py-100 text-body-small font-semibold disabled:opacity-50",
                line?.talking
                  ? "bg-background-danger-bold text-text-inverse"
                  : "border border-border-brand text-text-brand hover:bg-background-brand-subtlest",
              )}
            >
              <Mic className="h-3.5 w-3.5" />
              {line?.talking ? "Talking — release to mute" : "Hold to talk (or hold Space)"}
            </button>
            <form
              className="flex gap-050"
              onSubmit={(e) => {
                e.preventDefault();
                onRelease?.(handbackNote.trim());
                setHandbackNote("");
              }}
            >
              <input
                value={handbackNote}
                onChange={(e) => setHandbackNote(e.target.value)}
                placeholder="Note for the agent (optional)"
                className="h-400 min-w-0 flex-1 rounded-medium border border-border bg-surface-sunken px-100 text-body-small focus:border-border-brand focus:outline-none"
              />
              <button
                type="submit"
                className="rounded-medium bg-background-brand-bold px-100 text-body-small font-semibold text-text-inverse"
              >
                Hand back
              </button>
            </form>
            <button
              type="button"
              onClick={onEndCall}
              className="flex w-full items-center justify-center gap-050 rounded-medium border border-border-danger px-100 py-075 text-body-small font-medium text-text-danger hover:bg-background-danger"
            >
              <PhoneOff className="h-3 w-3" />
              End call
            </button>
          </div>
        ) : (
          <>
            {(isHuman || studio) && (
              <form
                className="mb-100 flex gap-050"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!whisper.trim()) return;
                  onWhisper(whisper.trim());
                  setWhisper("");
                }}
              >
                <input
                  value={whisper}
                  onChange={(e) => setWhisper(e.target.value)}
                  placeholder={
                    studio && !isHuman ? "Whisper to the AI agent…" : "Whisper to agent…"
                  }
                  className="h-400 min-w-0 flex-1 rounded-medium border border-border bg-surface-sunken px-100 text-body-small focus:border-border-brand focus:outline-none"
                />
                <button
                  type="submit"
                  className="rounded-medium bg-background-brand-bold px-100 text-body-small font-semibold text-text-inverse"
                >
                  Send
                </button>
              </form>
            )}
            <div className="flex gap-050">
              {!isChat && (
                <button
                  type="button"
                  onClick={() => onAction("listen", call)}
                  className={cn(
                    "flex flex-1 items-center justify-center gap-050 rounded-medium px-100 py-075 text-body-small font-medium",
                    listening
                      ? "bg-background-brand-bold text-text-inverse"
                      : "border border-border text-text-subtle hover:bg-surface-sunken",
                  )}
                >
                  <Headphones className="h-3 w-3" />
                  {listening ? "Listening" : "Listen"}
                </button>
              )}
              {isChat ? (
                <button
                  type="button"
                  onClick={() => onAction("inbox", call)}
                  className="flex flex-1 items-center justify-center gap-050 rounded-medium bg-background-brand-bold px-100 py-075 text-body-small font-semibold text-text-inverse"
                >
                  <LayoutGrid className="h-3 w-3" />
                  {actionLabel.inbox}
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() =>
                    primary === "whisper" && isHuman
                      ? onAction("whisper", call)
                      : setConfirmBarge(true)
                  }
                  className="flex flex-1 items-center justify-center gap-050 rounded-medium bg-background-danger-bold px-100 py-075 text-body-small font-semibold text-text-inverse hover:bg-background-danger-bold-hovered"
                >
                  {primary === "whisper" && isHuman ? (
                    <MessageSquare className="h-3 w-3" />
                  ) : (
                    <PhoneForwarded className="h-3 w-3" />
                  )}
                  {primary === "whisper" && isHuman ? actionLabel.whisper : actionLabel.barge}
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </aside>
  );
}
