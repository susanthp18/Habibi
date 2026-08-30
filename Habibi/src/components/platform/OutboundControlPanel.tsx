import { useState } from "react";
import { PhoneCall, PhoneOff, ShieldAlert } from "lucide-react";
import { toast } from "sonner";

import {
  DEMO_IGNORES_WINDOW,
  friendlyOutboundError,
  OUTBOUND_ENABLED,
  useDemoOutboundCall,
  useDemoOutboundTarget,
  usePatchPlatformSwitch,
  usePlatformSwitches,
} from "@/api/platform";
import { LoadingState } from "@/components/ui/loading-state";
import { Lozenge } from "@/components/ui/lozenge";
import { Switch } from "@/components/ui/switch";
import { useConfirm } from "@/components/ui/use-confirm";
import { cn } from "@/lib/utils";

/**
 * The master outbound gate, and the one-click demo dial behind it.
 *
 * Two rules shape this panel, and both are about the same thing — that the
 * side effect here is a real telephone ringing in someone's hand:
 *
 * 1. **Never render an unknown state as "off".** A failed read shows an error.
 *    An operator who believes dialling is off when it is on is worse served
 *    than one who is told the screen does not know.
 * 2. **Both controls confirm.** Turning the switch on authorises the treatment
 *    executor, the campaign runner and the bounce autodial all at once; the
 *    demo button dials a specific person immediately. Neither is a thing to do
 *    by brushing a control.
 */
export function OutboundControlPanel() {
  const { confirm, confirmDialog } = useConfirm();
  const switches = usePlatformSwitches();
  const target = useDemoOutboundTarget();
  const patch = usePatchPlatformSwitch();
  const demo = useDemoOutboundCall();
  const [lastResult, setLastResult] = useState<string | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);

  const outbound = switches.data?.switches.find((s) => s.key === OUTBOUND_ENABLED);
  const enabled = outbound?.enabled ?? false;
  const ignoresWindow =
    switches.data?.switches.find((s) => s.key === DEMO_IGNORES_WINDOW)?.enabled ?? false;
  const readFailed = switches.isError;
  const busy = patch.isPending || demo.isPending;
  // What the policy engine says right now, and whether the override covers it.
  const blockedNow = target.data?.policyReason ?? null;
  const waivedNow = target.data?.policyWaived ?? null;
  // The waiver covers when and how often, never whether the borrower agreed.
  const timingBlock =
    blockedNow === "outside_calling_hours" ||
    blockedNow === "outside_allowed_window" ||
    blockedNow === "cooling_off" ||
    blockedNow === "daily_cap" ||
    blockedNow === "weekly_cap";

  const onWindowToggle = async (next: boolean) => {
    if (next) {
      const ok = await confirm({
        title: "Let the demo call outside permitted hours?",
        description:
          "This waives the calling-hours check for the demo number only, and only for the demo button. Consent, opt-out, DND and the attempt caps still apply and still refuse. Every call that uses the waiver is recorded against the customer. Intended for a handset you own — not for reaching real borrowers out of hours.",
        confirmLabel: "Allow out-of-hours demo",
        cancelLabel: "Keep hours enforced",
      });
      if (!ok) return;
    }
    setLastError(null);
    try {
      await patch.mutateAsync({ key: DEMO_IGNORES_WINDOW, enabled: next });
      toast.success(next ? "Demo may call out of hours" : "Calling hours enforced");
    } catch (err) {
      const msg = friendlyOutboundError((err as Error)?.message ?? "switch_failed");
      setLastError(msg);
      toast.error(msg);
    }
  };

  const onToggle = async (next: boolean) => {
    if (next) {
      const ok = await confirm({
        title: "Turn on outbound calling?",
        description:
          "This authorises the treatment executor, the campaign runner and the bounce autodial to place real calls to real customers, subject to consent, DND and the statutory calling window. Leave it off unless you are running a demo or a supervised campaign.",
        confirmLabel: "Turn outbound on",
        cancelLabel: "Keep it off",
      });
      if (!ok) return;
    }
    setLastError(null);
    setLastResult(null);
    try {
      await patch.mutateAsync({ key: OUTBOUND_ENABLED, enabled: next });
      toast.success(next ? "Outbound calling is ON" : "Outbound calling is OFF");
    } catch (err) {
      const msg = friendlyOutboundError((err as Error)?.message ?? "switch_failed");
      setLastError(msg);
      toast.error(msg);
    }
  };

  const onDemo = async () => {
    const who = target.data?.customer?.name ?? "the demo contact";
    const phone = target.data?.phone ?? "";
    const ok = await confirm({
      title: `Call ${who} now?`,
      description: `This places a real outbound call to ${phone} and runs the ${
        target.data?.objective ?? "collections"
      } mission — identity verification, the balance conversation, promise-to-pay, hardship, dispute and callback — with every tool call written to the CRM.${
        target.data && !target.data.offersAllowed
          ? " Upsell is not part of it: this card's objective forbids mentioning any offer."
          : ""
      }`,
      confirmLabel: "Place the call",
      cancelLabel: "Not now",
    });
    if (!ok) return;
    setLastError(null);
    setLastResult(null);
    try {
      const res = await demo.mutateAsync();
      setLastResult(
        `Dialling ${res.phone}${res.callSid ? ` · call ${res.callSid}` : ""}${
          res.attemptId ? ` · attempt ${res.attemptId}` : ""
        }`,
      );
      toast.success("Demo call placed");
    } catch (err) {
      const msg = friendlyOutboundError((err as Error)?.message ?? "demo_call_failed");
      setLastError(msg);
      toast.error(msg);
    }
  };

  return (
    <div
      className={cn(
        "rounded-medium border p-200",
        enabled ? "border-border-warning-subtle bg-background-warning-subtler" : "border-border",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-150">
        <div className="min-w-0">
          <div className="flex items-center gap-100">
            {enabled ? (
              <PhoneCall className="h-4 w-4 text-icon-warning" />
            ) : (
              <PhoneOff className="h-4 w-4 text-text-subtlest" />
            )}
            <h2 className="text-body font-semibold text-text">Outbound calling</h2>
            {readFailed ? (
              <Lozenge tone="danger">State unknown</Lozenge>
            ) : enabled ? (
              <Lozenge tone="warning">ON — the dialer is live</Lozenge>
            ) : (
              <Lozenge tone="neutral">OFF</Lozenge>
            )}
          </div>
          <p className="mt-075 max-w-[46rem] text-body-small text-text-subtle">
            The master gate on every outbound dial — the treatment executor, the campaign runner,
            the bounce autodial and the demo button below. Off by default, and off is enforced at
            the carrier boundary, so nothing can route around it. Turning it on does not bypass
            anything: consent, DND, the statutory calling hours, each borrower&apos;s own (narrower)
            preferred window and the daily attempt caps all still apply.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-100">
          {switches.isPending ? (
            <LoadingState label="Reading switch" />
          ) : (
            <Switch
              aria-label="Outbound calling"
              checked={enabled}
              disabled={busy || readFailed}
              onCheckedChange={(v) => void onToggle(v)}
            />
          )}
        </div>
      </div>

      {readFailed && (
        <div className="mt-150 flex items-start gap-100 rounded-medium border border-border-danger-subtle bg-background-danger-subtler px-150 py-100 text-body-small text-text-danger-bolder">
          <ShieldAlert className="mt-025 h-3.5 w-3.5 shrink-0" />
          <span>
            Could not read the outbound switch:{" "}
            {(switches.error as Error)?.message ?? "unknown error"}. The dialer&apos;s state is
            unknown from here — this screen will not guess.
          </span>
        </div>
      )}

      <div className="mt-200 border-t border-border pt-150">
        <div className="flex flex-wrap items-center justify-between gap-150">
          <div className="min-w-0">
            <div className="text-body-small font-semibold text-text">Demo outbound call</div>
            <p className="mt-050 text-body-small text-text-subtle">
              {target.data?.customer ? (
                <>
                  Calls <span className="font-semibold text-text">{target.data.customer.name}</span>{" "}
                  on <span className="font-mono">{target.data.phone}</span> under the{" "}
                  <span className="font-mono">{target.data.objective}</span> objective:
                  verification, account position, promise-to-pay, hardship, dispute, callback —
                  every tool call written to the CRM.
                </>
              ) : target.isPending ? (
                "Loading the demo target…"
              ) : target.isError ? (
                "Could not load the demo target."
              ) : (
                "No customer on file with the demo phone number."
              )}
            </p>
          </div>
          <button
            type="button"
            disabled={!enabled || busy || !target.data?.customer}
            onClick={() => void onDemo()}
            title={enabled ? undefined : "Turn outbound calling on first"}
            className="focus-ring inline-flex h-400 shrink-0 items-center gap-075 rounded-medium bg-background-brand-bold px-150 text-body font-medium text-text-inverse hover:bg-background-brand-bold-hovered active:scale-[0.98] disabled:opacity-50"
          >
            <PhoneCall className="h-3.5 w-3.5" />
            {demo.isPending ? "Dialling…" : "Demo outbound"}
          </button>
        </div>

        {/*
          Always visible, not gated on `enabled`. Hidden until outbound was on,
          the sequence became: turn outbound on, press Demo, get a 409 about
          calling hours, conclude the button is broken — never seeing that the
          control for exactly that case had just appeared further down.
        */}
        {!readFailed && (
          <div className="mt-150 flex flex-wrap items-start justify-between gap-100 rounded-medium border border-border bg-surface-sunken px-150 py-100">
            <div className="min-w-0">
              <div className="text-body-small font-semibold text-text">
                Allow the demo to call outside permitted hours
              </div>
              <p className="mt-025 max-w-[40rem] text-body-small text-text-subtle">
                Demo number only. Waives when and how often the demo may dial — calling hours, the
                borrower&apos;s window, cooling-off and the daily/weekly caps. Consent, opt-out, DND
                and the registry still refuse. Each use is recorded against the customer.
                {blockedNow && timingBlock && !ignoresWindow ? (
                  <span className="font-semibold text-text-warning-bolder">
                    {" "}
                    Right now the call would be refused: {blockedNow}.
                  </span>
                ) : null}
                {waivedNow ? (
                  <span className="font-semibold text-text-warning-bolder">
                    {" "}
                    Overriding {waivedNow} for this call — recorded on the customer&apos;s timeline.
                  </span>
                ) : null}
                {blockedNow && !timingBlock ? (
                  <span className="font-semibold text-text-danger">
                    {" "}
                    Right now the call would be refused for {blockedNow}, which this waiver does not
                    cover.
                  </span>
                ) : null}
              </p>
            </div>
            <Switch
              aria-label="Allow the demo to call outside permitted hours"
              checked={ignoresWindow}
              disabled={busy || readFailed}
              onCheckedChange={(v) => void onWindowToggle(v)}
            />
          </div>
        )}

        {target.data?.customer && !target.data.offersAllowed && (
          <p className="mt-100 text-body-small text-text-subtlest">
            <span className="font-semibold text-text-subtle">No upsell on this call.</span> Every
            outbound objective on this card sets <span className="font-mono">allowed_offers</span>{" "}
            to empty, which makes the mission brief instruct the agent not to mention any product,
            offer or top-up. To demo upsell, author{" "}
            <span className="font-mono">allowed_offers</span> on the objective in Agent Studio and
            publish — it is a card decision, not a setting here.
          </p>
        )}
        {!enabled && !readFailed && (
          <p className="mt-100 text-body-small text-text-subtlest">
            Turn outbound calling on to enable this. The button is gated by the same switch as
            everything else — a kill switch with an exception is not a kill switch.
          </p>
        )}
        {lastResult && (
          <div className="mt-100 rounded-medium border border-border-success-subtle bg-background-success-subtler px-150 py-100 text-body-small text-text-success-bolder">
            {lastResult}
          </div>
        )}
        {lastError && (
          <div className="mt-100 rounded-medium border border-border-warning-subtle bg-background-warning-subtler px-150 py-100 text-body-small text-text-warning-bolder">
            {lastError}
          </div>
        )}
      </div>
      {confirmDialog}
    </div>
  );
}
