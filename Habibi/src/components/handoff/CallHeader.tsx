import { Mic, MicOff, PauseCircle, PhoneForwarded, PhoneOff, Radio } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ActiveCall } from "@/api/handoff";

function fmt(sec: number) {
  const m = Math.floor(sec / 60).toString().padStart(2, "0");
  const s = Math.floor(sec % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

type Props = {
  call: ActiveCall;
  elapsed: number;
  muted: boolean;
  onToggleMute: () => void;
  onHold: () => void;
  onTransfer: () => void;
  onEnd: () => void;
  ended: boolean;
};

export function CallHeader({ call: activeCall, elapsed, muted, onToggleMute, onHold, onTransfer, onEnd, ended }: Props) {
  return (
    <header className="shrink-0 border-b border-[var(--border-token)] bg-surface-card px-5 py-3">
      <div className="flex items-center gap-4">
        <div className="grid h-10 w-10 place-items-center rounded-full bg-brand-tint font-semibold text-brand-primary-dark">
          {activeCall.customerName.split(" ").map((w) => w[0]).join("")}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <div className="truncate text-[15px] font-semibold text-brand-navy">
              {activeCall.customerName}
            </div>
            <span className="rounded-full bg-danger-bg px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-danger">
              High risk
            </span>
            <span className="rounded-full bg-warning-bg px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-warning">
              Escalated
            </span>
          </div>
          <div className="mt-0.5 flex items-center gap-3 text-[12px] text-text-secondary">
            <span className="tabular">{activeCall.accountId}</span>
            <span>·</span>
            <span>{activeCall.phone}</span>
            <span>·</span>
            <span>{activeCall.channel}</span>
            <span>·</span>
            <span className="text-text-muted">from {activeCall.transferredFrom}</span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <div className={cn(
            "flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold",
            ended ? "bg-surface-sunken text-text-muted" : "bg-success-bg text-success",
          )}>
            <Radio className={cn("h-3 w-3", !ended && "pulse-dot rounded-full")} />
            {ended ? "Call ended" : "Live"}
          </div>
          <div className="tabular rounded-md bg-surface-sunken px-2.5 py-1 text-[13px] font-semibold text-brand-navy">
            {fmt(elapsed)}
          </div>

          <div className="ml-2 flex items-center gap-1">
            <IconBtn label={muted ? "Unmute" : "Mute"} onClick={onToggleMute} active={muted} disabled={ended}>
              {muted ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
            </IconBtn>
            <IconBtn label="Hold" onClick={onHold} disabled={ended}>
              <PauseCircle className="h-4 w-4" />
            </IconBtn>
            <IconBtn label="Transfer" onClick={onTransfer} disabled={ended}>
              <PhoneForwarded className="h-4 w-4" />
            </IconBtn>
            <button
              type="button"
              onClick={onEnd}
              disabled={ended}
              className="ml-1 flex items-center gap-1.5 rounded-md bg-danger px-3 py-1.5 text-[12px] font-semibold text-white transition-colors hover:bg-[#b3271d] disabled:cursor-not-allowed disabled:opacity-50"
            >
              <PhoneOff className="h-3.5 w-3.5" />
              End call
            </button>
          </div>
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
        "grid h-8 w-8 place-items-center rounded-md border border-[var(--border-token)] transition-colors",
        active ? "bg-brand-tint text-brand-primary-dark" : "bg-surface-card text-text-secondary hover:bg-surface-sunken",
        disabled && "cursor-not-allowed opacity-50",
      )}
    >
      {children}
    </button>
  );
}
