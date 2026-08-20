import { Headphones, ShieldAlert } from "lucide-react";
import { Lozenge } from "@/components/ui/lozenge";
import type { HandoffAlert } from "@/api/handoff";
import { ackFloorAlert } from "@/api/floor";
import { useMutation, useQueryClient } from "@tanstack/react-query";

export function HandoffAlerts({
  items,
  mock,
}: {
  items: HandoffAlert[];
  mock?: boolean;
}) {
  const qc = useQueryClient();
  const ack = useMutation({
    mutationFn: (id: string) => ackFloorAlert(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["handoff"] });
    },
  });

  if (!items.length) return null;

  return (
    <div className="rounded-large border border-border-warning bg-background-warning/40">
      <div className="flex items-center gap-075 border-b border-border px-150 py-100 text-body-small font-semibold text-text">
        <ShieldAlert className="h-3.5 w-3.5 text-text-warning" />
        Live alerts
      </div>
      <ul className="divide-y divide-border">
        {items.map((a) => (
          <li key={a.id} className="flex items-start justify-between gap-100 px-150 py-100">
            <div className="min-w-0">
              <div className="text-body-small font-semibold text-text">
                {a.kind.replace(/_/g, " ")}
              </div>
              {a.reason ? (
                <div className="text-body-small text-text-subtle">{a.reason}</div>
              ) : null}
            </div>
            <button
              type="button"
              disabled={mock || ack.isPending}
              onClick={() => ack.mutate(a.id)}
              className="shrink-0 text-body-small font-semibold text-text-brand hover:underline disabled:opacity-50"
            >
              Ack
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function HandoffQueueList({
  items,
  claimingId,
  onClaim,
}: {
  items: {
    interactionId: string;
    customerName: string;
    accountId: string;
    reason: string;
    queue: string | null;
    risk: string;
    waitSec: number;
  }[];
  claimingId?: string | null;
  onClaim: (interactionId: string) => void;
}) {
  if (!items.length) {
    return (
      <div className="grid h-full place-items-center p-400 text-center">
        <div>
          <Headphones className="mx-auto mb-150 h-8 w-8 text-text-subtlest" />
          <p className="text-sm font-semibold text-text">No pending handoffs</p>
          <p className="mt-050 max-w-sm text-body text-text-subtlest">
            Escalated calls for your team will land here. Claim one to open the live cockpit.
          </p>
        </div>
      </div>
    );
  }

  return (
    <ul className="mx-auto w-full max-w-2xl space-y-150 p-200">
      {items.map((item) => (
        <li
          key={item.interactionId}
          className="flex items-center gap-150 rounded-large border border-border bg-surface p-150"
        >
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-100">
              <span className="truncate font-semibold text-text">{item.customerName}</span>
              <RiskLozenge risk={item.risk} />
            </div>
            <div className="mt-025 text-body-small text-text-subtle">
              {item.accountId} · {item.reason.replace(/_/g, " ")}
              {item.queue ? ` · ${item.queue}` : ""}
            </div>
            <div className="mt-025 tabular text-body-small text-text-subtlest">
              waiting {fmtWait(item.waitSec)}
            </div>
          </div>
          <button
            type="button"
            disabled={claimingId === item.interactionId}
            onClick={() => onClaim(item.interactionId)}
            className="shrink-0 rounded-medium bg-background-brand-bold px-150 py-075 text-body-small font-semibold text-white hover:bg-background-brand-bold-hovered disabled:opacity-60"
          >
            {claimingId === item.interactionId ? "Claiming…" : "Claim"}
          </button>
        </li>
      ))}
    </ul>
  );
}

export function RiskLozenge({ risk }: { risk: string }) {
  const r = risk.toLowerCase();
  const tone = r === "critical" || r === "high" ? "danger" : r === "medium" ? "warning" : "success";
  return <Lozenge tone={tone}>{risk} risk</Lozenge>;
}

function fmtWait(sec: number) {
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return s ? `${m}m ${s}s` : `${m}m`;
}
