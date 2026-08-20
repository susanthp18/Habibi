import { Mic, MicOff, PauseCircle, PhoneForwarded, PhoneOff, Radio } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ActiveCall } from "@/api/handoff";
import { Lozenge } from "@/components/ui/lozenge";
import { RiskLozenge } from "./HandoffQueue";

function fmt(sec: number) {
  const m = Math.floor(sec / 60).toString().padStart(2, "0");
  const s = Math.floor(sec % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

const MEDIA_HINT = "Voice is callback-queue; live media controls ship with warm transfer.";

type Props = {
  call: ActiveCall;
  elapsed: number;
  muted: boolean;
  onToggleMute: () => void;
  onHold: () => void;
  onTransfer: () => void;
  onEnd: () => void;
  ended: boolean;
  mediaEnabled?: boolean;
  monitor?: boolean;
};

export function CallHeader({
  call: activeCall,
  elapsed,
  muted,
  onToggleMute,
  onHold,
  onTransfer,
  onEnd,
  ended,
  mediaEnabled = false,
  monitor = false,
}: Props) {
  return (
    <header className="shrink-0 border-b border-border bg-surface px-250 py-150">
      <div className="flex items-center gap-200">
        <div className="grid h-500 w-500 place-items-center rounded-full bg-background-brand-subtlest font-semibold text-text-brand">
          {activeCall.customerName
            .split(" ")
            .map((w) => w[0])
            .join("")}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-100">
            <div className="truncate text-[0.875rem] font-semibold text-text">
              {activeCall.customerName}
            </div>
            <RiskLozenge risk={activeCall.risk} />
            {monitor ? <Lozenge tone="information">Monitoring</Lozenge> : <Lozenge tone="warning">Escalated</Lozenge>}
          </div>
          <div className="mt-025 flex items-center gap-150 text-body-small text-text-subtle">
            <span className="tabular">{activeCall.accountId}</span>
            <span>·</span>
            <span>{activeCall.phone}</span>
            <span>·</span>
            <span>{activeCall.channel}</span>
            {activeCall.transferredFrom ? (
              <>
                <span>·</span>
                <span className="text-text-subtlest">from {activeCall.transferredFrom}</span>
              </>
            ) : null}
          </div>
        </div>

        <div className="flex items-center gap-100">
          <Lozenge tone={ended ? "neutral" : "success"}>
            <Radio className={cn(!ended && "pulse-dot rounded-full")} />
            {ended ? "Call ended" : "Live"}
          </Lozenge>
          <div className="tabular rounded-medium bg-surface-sunken px-150 py-050 text-body font-semibold text-text">
            {fmt(elapsed)}
          </div>

          {!monitor && (
          <div className="ml-100 flex items-center gap-050">
            <IconBtn
              label={mediaEnabled ? (muted ? "Unmute" : "Mute") : MEDIA_HINT}
              onClick={onToggleMute}
              active={muted}
              disabled={ended || !mediaEnabled}
            >
              {muted ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
            </IconBtn>
            <IconBtn label={mediaEnabled ? "Hold" : MEDIA_HINT} onClick={onHold} disabled={ended || !mediaEnabled}>
              <PauseCircle className="h-4 w-4" />
            </IconBtn>
            <IconBtn
              label={mediaEnabled ? "Transfer" : MEDIA_HINT}
              onClick={onTransfer}
              disabled={ended || !mediaEnabled}
            >
              <PhoneForwarded className="h-4 w-4" />
            </IconBtn>
            <button
              type="button"
              onClick={onEnd}
              disabled={ended}
              className="ml-050 flex items-center gap-075 rounded-medium bg-background-danger-bold px-150 py-075 text-body-small font-semibold text-white transition-colors hover:bg-background-danger-bold-hovered disabled:cursor-not-allowed disabled:opacity-50"
            >
              <PhoneOff className="h-3.5 w-3.5" />
              End call
            </button>
          </div>
          )}
        </div>
      </div>
    </header>
  );
}

function IconBtn({
  children,
  label,
  onClick,
  active,
  disabled,
}: {
  children: React.ReactNode;
  label: string;
  onClick?: () => void;
  active?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "grid h-400 w-400 place-items-center rounded-medium border border-border transition-colors",
        active ? "bg-background-brand-subtlest text-text-brand" : "bg-surface text-text-subtle hover:bg-surface-sunken",
        disabled && "cursor-not-allowed opacity-50",
      )}
    >
      {children}
    </button>
  );
}
