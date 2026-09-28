/**
 * The automation switches: what the platform may do on its own.
 *
 * Never renders an unknown state as "off" (a failed read is an error), and
 * turning anything on asks first: each one lets software contact real people.
 */
import { ShieldAlert } from "lucide-react";
import { toast } from "sonner";

import {
  DEMO_IGNORES_WINDOW,
  friendlyOutboundError,
  OUTBOUND_ENABLED,
  RECO_ENABLED,
  TREATMENT_ENACT_ENABLED,
  usePatchPlatformSwitch,
  usePlatformSwitches,
} from "@/api/platform";
import { LoadingState } from "@/components/ui/loading-state";
import { Lozenge } from "@/components/ui/lozenge";
import { Switch } from "@/components/ui/switch";
import { useConfirm } from "@/components/ui/use-confirm";
import { fmtDateTime } from "@/lib/format";

const SWITCHES: { key: string; title: string; body: string; confirm: string }[] = [
  {
    key: OUTBOUND_ENABLED,
    title: "Outbound calling",
    body: "The master gate on every dial: the dialler, campaigns, the bounce autodial, test calls, and calls Voice Studio starts itself (editor test calls, engine campaigns). Consent, DND, calling hours and attempt caps still apply when it is on.",
    confirm:
      "This lets the platform place real calls to real customers, subject to consent, DND and the calling window. Leave it off unless you are running a demo or a supervised campaign.",
  },
  {
    key: TREATMENT_ENACT_ENABLED,
    title: "Carry out next best actions",
    body: "The decision engine acts on its live decisions (calls, messages, follow-ups). Off: it still decides and explains, but nothing is sent.",
    confirm:
      "The decision engine will start contacting customers on its own, within outbound calling and the contact policy.",
  },
  {
    key: RECO_ENABLED,
    title: "Send offers",
    body: "Offers decided from what customers said go out by WhatsApp template or to a relationship manager, only with marketing consent. Off: offers are decided and traced, never sent.",
    confirm: "Offers will be sent to customers who agreed to marketing.",
  },
  {
    key: DEMO_IGNORES_WINDOW,
    title: "Let test calls ring outside calling hours",
    body: "Test numbers only. Waives the statutory hours and the customer's preferred window for a test call; consent, opt-out and DND still refuse. Every waiver is recorded on the customer.",
    confirm: "Test calls may ring a test handset out of hours. Intended for a handset you own.",
  },
];

export function SwitchesSection() {
  const { confirm, confirmDialog } = useConfirm();
  const switches = usePlatformSwitches();
  const patch = usePatchPlatformSwitch();

  const flip = async (key: string, title: string, next: boolean, body: string) => {
    if (next) {
      const ok = await confirm({
        title: `Turn on "${title}"?`,
        description: body,
        confirmLabel: "Turn on",
        cancelLabel: "Keep off",
      });
      if (!ok) return;
    }
    try {
      await patch.mutateAsync({ key, enabled: next });
      toast.success(`${title}: ${next ? "on" : "off"}`);
    } catch (err) {
      toast.error(friendlyOutboundError((err as Error)?.message ?? "switch_failed"));
    }
  };

  return (
    <section>
      <h2 className="text-body font-semibold">Automation switches</h2>
      <p className="mb-200 mt-025 text-body-small text-text-subtle">
        What the platform may do without a person pressing a button. Off by default.
      </p>
      {switches.isPending ? (
        <LoadingState label="Reading switches" />
      ) : switches.isError ? (
        <div className="flex items-start gap-100 rounded-medium border border-border-danger-subtle bg-background-danger-subtler px-150 py-100 text-body-small text-text-danger-bolder">
          <ShieldAlert className="mt-025 h-3.5 w-3.5 shrink-0" />
          Could not read the switches: {(switches.error as Error)?.message ?? "unknown error"}.
          Their state is unknown from here; this screen will not guess.
        </div>
      ) : (
        <ul className="max-w-3xl divide-y divide-border rounded-medium border border-border">
          {SWITCHES.map((s) => {
            const state = switches.data.switches.find((x) => x.key === s.key);
            const on = state?.enabled ?? false;
            return (
              <li key={s.key} className="flex items-start justify-between gap-200 p-200">
                <div className="min-w-0">
                  <div className="flex items-center gap-100">
                    <span className="text-body font-medium text-text">{s.title}</span>
                    {on ? <Lozenge tone="warning">On</Lozenge> : <Lozenge>Off</Lozenge>}
                  </div>
                  <p className="mt-050 text-body-small text-text-subtle">{s.body}</p>
                  {state?.updatedAt ? (
                    <p className="mt-050 text-body-tiny text-text-subtlest">
                      Last changed {fmtDateTime(state.updatedAt)}
                      {state.updatedByUserId ? ` by ${state.updatedByUserId}` : ""}
                      {state.note ? ` · ${state.note}` : ""}
                    </p>
                  ) : null}
                </div>
                <Switch
                  aria-label={s.title}
                  checked={on}
                  disabled={patch.isPending}
                  onCheckedChange={(v) => void flip(s.key, s.title, v, s.confirm)}
                />
              </li>
            );
          })}
        </ul>
      )}
      {confirmDialog}
    </section>
  );
}
